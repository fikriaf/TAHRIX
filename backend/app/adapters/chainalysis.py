"""Chainalysis Free Sanctions Screening API adapter.

Endpoint (verified): GET https://public.chainalysis.com/api/v1/address/{address}
Auth: header `X-API-Key: <key>` (free key issued via Chainalysis form).
Response shape (per public docs):
    {
      "identifications": [
        {"category": "sanctions", "name": "OFAC SDN List", "description": "...",
         "url": "..."}
      ]
    }
An empty `identifications` array means the address is NOT sanctioned.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.adapters.base import BaseHTTPAdapter
from app.core.config import settings
from app.core.exceptions import ConfigurationError, ExternalAPIError
from app.core.logging import get_logger
from app.models.domain import SanctionResult

logger = get_logger(__name__)


class ChainalysisAdapter(BaseHTTPAdapter):
    provider_name = "chainalysis"
    requires_api_key = True

    def __init__(self) -> None:
        if not settings.chainalysis_api_key:
            raise ConfigurationError("CHAINALYSIS_API_KEY missing")
        api_key = settings.chainalysis_api_key.get_secret_value()
        super().__init__(
            base_url=settings.chainalysis_api_url,
            api_key=api_key,
            timeout=15.0,
            max_retries=3,
            default_headers={
                "X-API-Key": api_key,
                "Accept": "application/json",
            },
        )

    async def check_address(self, address: str) -> SanctionResult:
        try:
            data = await self.get_json(f"/{address}")
        except ExternalAPIError:
            raise
        identifications = (data or {}).get("identifications") or []
        return SanctionResult(
            address=address,
            sanctioned=len(identifications) > 0,
            identifications=identifications,
            source="chainalysis",
            checked_at=datetime.now(timezone.utc),
        )
