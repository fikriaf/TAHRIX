"""IPFS adapter via Pinata API.

Docs: https://docs.pinata.cloud/api-reference
  • POST /pinning/pinFileToIPFS   — upload + pin file (multipart)
  • POST /pinning/pinJSONToIPFS   — upload + pin JSON object
  • DELETE /pinning/unpin/{cid}   — unpin a CID
Auth: Bearer JWT (preferred) or pinata_api_key + pinata_secret_api_key headers.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.adapters.base import BaseHTTPAdapter
from app.core.config import settings
from app.core.exceptions import ConfigurationError, ExternalAPIError
from app.core.logging import get_logger

logger = get_logger(__name__)


class IPFSAdapter(BaseHTTPAdapter):
    provider_name = "ipfs_pinata"
    requires_api_key = True

    def __init__(self) -> None:
        if not settings.pinata_jwt and not (settings.pinata_api_key and settings.pinata_api_secret):
            raise ConfigurationError("Pinata credentials missing: set PINATA_JWT or PINATA_API_KEY+PINATA_API_SECRET")

        # Prefer JWT auth
        if settings.pinata_jwt:
            jwt = settings.pinata_jwt.get_secret_value()
            headers = {"Authorization": f"Bearer {jwt}"}
            api_key_val = jwt[:16]
        else:
            headers = {
                "pinata_api_key": settings.pinata_api_key.get_secret_value(),  # type: ignore[union-attr]
                "pinata_secret_api_key": settings.pinata_api_secret.get_secret_value(),  # type: ignore[union-attr]
            }
            api_key_val = settings.pinata_api_key.get_secret_value()  # type: ignore[union-attr]

        super().__init__(
            base_url=settings.pinata_api_url,
            api_key=api_key_val,
            timeout=60.0,
            max_retries=2,
            default_headers=headers,
        )

    async def add_file(self, path: str | Path, *, pin: bool = True) -> str:  # noqa: ARG002
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(p)
        with p.open("rb") as f:
            content = f.read()
        return await self.add_bytes(content, filename=p.name)

    async def add_bytes(self, content: bytes, *, filename: str = "file.bin",
                        pin: bool = True) -> str:  # noqa: ARG002
        """Upload bytes to IPFS via Pinata pinFileToIPFS.

        Returns the IPFS CID (v0 or v1 depending on Pinata config).
        """
        files = {"file": (filename, content, "application/octet-stream")}
        # pinataMetadata is optional JSON string in multipart
        metadata = json.dumps({"name": filename})
        response = await self._client.post(
            "/pinning/pinFileToIPFS",
            files=files,
            data={"pinataMetadata": metadata},
        )
        if response.status_code != 200:
            raise ExternalAPIError(
                f"pinata pinFileToIPFS failed: {response.text[:300]}",
                provider=self.provider_name,
                upstream_status=response.status_code,
            )
        data = response.json()
        cid = data["IpfsHash"]
        logger.info("ipfs.add", cid=cid, size=len(content))
        return cid

    async def pin(self, cid: str) -> bool:
        """Pinata auto-pins on upload; this is a no-op kept for API compat."""
        logger.debug("ipfs.pin.noop", cid=cid)
        return True

    async def unpin(self, cid: str) -> bool:
        response = await self._client.delete(f"/pinning/unpin/{cid}")
        if response.status_code not in (200, 204):
            logger.warning("ipfs.unpin.failed", cid=cid, status=response.status_code)
            return False
        logger.info("ipfs.unpin", cid=cid)
        return True

    @staticmethod
    def sha256_hex(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def public_url(cid: str) -> str:
        return f"{settings.ipfs_public_gateway.rstrip('/')}/{cid}"
