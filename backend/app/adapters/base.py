"""Base HTTP client for external API adapters.

Features:
  • Shared `httpx.AsyncClient` per adapter instance with sane timeouts
  • Retry + exponential backoff on transient errors (5xx, 429, network)
  • Per-provider circuit breaker (in-memory) — fails open after N consecutive errors
  • Structured logging with provider name + duration

NOT a mock layer. If an API key is missing for an adapter that requires one,
constructing the adapter raises `ConfigurationError`.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.exceptions import (
    CircuitBreakerOpenError,
    ConfigurationError,
    ExternalAPIError,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

# Errors we consider retryable
_RETRYABLE_NETWORK = (
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.RemoteProtocolError,
    httpx.PoolTimeout,
)


class CircuitBreaker:
    """Minimal in-memory circuit breaker.

    States: CLOSED → OPEN (after `threshold` failures) → HALF_OPEN (after `cooldown`).
    """

    def __init__(self, *, threshold: int = 5, cooldown_seconds: int = 30) -> None:
        self.threshold = threshold
        self.cooldown = cooldown_seconds
        self._fail_count = 0
        self._opened_at: float | None = None
        self._lock = asyncio.Lock()

    async def before(self) -> None:
        async with self._lock:
            if self._opened_at is None:
                return
            elapsed = time.monotonic() - self._opened_at
            if elapsed < self.cooldown:
                raise CircuitBreakerOpenError(
                    f"Circuit open ({elapsed:.0f}s/{self.cooldown}s)",
                    provider="?",
                )
            # half-open: allow one trial
            self._opened_at = None
            self._fail_count = self.threshold - 1

    async def on_success(self) -> None:
        async with self._lock:
            self._fail_count = 0
            self._opened_at = None

    async def on_failure(self) -> None:
        async with self._lock:
            self._fail_count += 1
            if self._fail_count >= self.threshold and self._opened_at is None:
                self._opened_at = time.monotonic()


class BaseHTTPAdapter:
    """Inherit from this class for each external provider."""

    provider_name: str = "base"
    requires_api_key: bool = False

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 20.0,
        max_retries: int = 3,
        circuit_threshold: int = 8,
        circuit_cooldown: int = 30,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        if self.requires_api_key and not api_key:
            raise ConfigurationError(
                f"{self.provider_name}: API key not configured",
            )

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.max_retries = max_retries
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout, connect=10.0),
            headers=default_headers or {},
            follow_redirects=True,
        )
        self._cb = CircuitBreaker(threshold=circuit_threshold, cooldown_seconds=circuit_cooldown)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.aclose()

    # ── Core request ──
    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        expect_status: tuple[int, ...] = (200,),
    ) -> httpx.Response:
        await self._cb.before()

        async def _send() -> httpx.Response:
            t0 = time.perf_counter()
            response = await self._client.request(
                method, url, params=params, json=json, data=data, headers=headers,
            )
            dur = int((time.perf_counter() - t0) * 1000)
            logger.debug(
                "external.api.call",
                provider=self.provider_name, method=method, url=url,
                status=response.status_code, duration_ms=dur,
            )
            # Retry on 5xx + 429
            if response.status_code in (429, 500, 502, 503, 504):
                raise _RetryableHTTPError(response.status_code, response.text[:500])
            return response

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.max_retries),
                wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
                retry=retry_if_exception_type((_RetryableHTTPError, *_RETRYABLE_NETWORK)),
                reraise=True,
            ):
                with attempt:
                    response = await _send()
        except (RetryError, _RetryableHTTPError, *_RETRYABLE_NETWORK) as e:  # type: ignore[misc]
            await self._cb.on_failure()
            raise ExternalAPIError(
                f"{self.provider_name} request failed after retries: {e}",
                provider=self.provider_name,
            ) from e

        if response.status_code not in expect_status:
            await self._cb.on_failure()
            raise ExternalAPIError(
                f"{self.provider_name} unexpected status {response.status_code}",
                provider=self.provider_name,
                upstream_status=response.status_code,
                details={"body": response.text[:500]},
            )

        await self._cb.on_success()
        return response

    async def get_json(self, url: str, **kw) -> Any:
        r = await self.request("GET", url, **kw)
        return r.json()

    async def post_json(self, url: str, **kw) -> Any:
        r = await self.request("POST", url, **kw)
        return r.json()


class _RetryableHTTPError(Exception):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
