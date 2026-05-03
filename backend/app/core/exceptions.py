"""Domain exceptions used across the codebase.

Mapped to HTTP responses by `app.api.v1.error_handlers`.
"""

from __future__ import annotations


class TahrixError(Exception):
    """Base class for all domain exceptions."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


# ── 4xx ──
class BadRequestError(TahrixError):
    status_code = 400
    code = "bad_request"


class ValidationError(TahrixError):
    status_code = 422
    code = "validation_error"


class NotFoundError(TahrixError):
    status_code = 404
    code = "not_found"


class UnauthorizedError(TahrixError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(TahrixError):
    status_code = 403
    code = "forbidden"


class RateLimitError(TahrixError):
    status_code = 429
    code = "rate_limited"


# ── 5xx ──
class ExternalAPIError(TahrixError):
    """An upstream external API failed (Alchemy, Helius, etc.)."""

    status_code = 502
    code = "external_api_error"

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        upstream_status: int | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, details={**(details or {}), "provider": provider,
                                           "upstream_status": upstream_status})
        self.provider = provider
        self.upstream_status = upstream_status


class ConfigurationError(TahrixError):
    """A required env var or runtime config is missing."""

    status_code = 500
    code = "configuration_error"


class CircuitBreakerOpenError(ExternalAPIError):
    code = "circuit_breaker_open"
    status_code = 503
