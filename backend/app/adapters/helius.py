"""Helius adapter — Solana data + webhooks.

Endpoints (verified against helius.dev docs, 2026-04):
  • GET  {api}/v0/addresses/{address}/transactions          — Enhanced parsed history
  • POST {api}/v0/transactions                              — Parse N signatures (≤100)
  • POST {rpc}/?api-key=…  (JSON-RPC: getSignaturesForAddress, getTokenAccountsByOwner,
                            getBalance, getTransaction, …) — standard Solana RPC
  • POST {api}/v0/webhooks?api-key=…                        — webhook CRUD
  • GET  /v1/getAssetsByOwner via DAS API (also POST JSON-RPC method on RPC URL)

Auth: API key as `?api-key=` query param.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.adapters.base import BaseHTTPAdapter
from app.core.config import settings
from app.core.exceptions import ConfigurationError, ExternalAPIError
from app.core.logging import get_logger
from app.models.domain import TransactionNode
from app.models.enums import Chain, TxStatus

logger = get_logger(__name__)

LAMPORTS_PER_SOL = 1_000_000_000


class HeliusAdapter(BaseHTTPAdapter):
    provider_name = "helius"
    requires_api_key = True

    def __init__(self) -> None:
        if not settings.helius_api_key:
            raise ConfigurationError("HELIUS_API_KEY missing")
        api_key = settings.helius_api_key.get_secret_value()
        super().__init__(
            base_url=settings.helius_api_url,
            api_key=api_key,
            timeout=30.0,
            max_retries=4,
            default_headers={"Content-Type": "application/json"},
        )
        self._rpc_url = f"{settings.helius_rpc_url.rstrip('/')}/?api-key={api_key}"
        self._req_id = 0

    @property
    def _key_qs(self) -> dict[str, str]:
        return {"api-key": self.api_key or ""}

    # ── Enhanced Transactions API ──
    async def get_transactions_for_address(
        self,
        address: str,
        *,
        limit: int = 100,
        before_signature: str | None = None,
        after_signature: str | None = None,
        type_filter: str | None = None,
        source_filter: str | None = None,
        commitment: str = "finalized",
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            **self._key_qs,
            "limit": min(max(limit, 1), 100),
            "commitment": commitment,
        }
        if before_signature:
            params["before-signature"] = before_signature
        if after_signature:
            params["after-signature"] = after_signature
        if type_filter:
            params["type"] = type_filter
        if source_filter:
            params["source"] = source_filter
        data = await self.get_json(f"/v0/addresses/{address}/transactions", params=params)
        if isinstance(data, dict) and "error" in data:
            raise ExternalAPIError(
                f"helius: {data['error']}", provider=self.provider_name
            )
        return data or []

    async def iter_transactions_for_address(
        self,
        address: str,
        *,
        page_size: int = 100,
        max_pages: int = 5,
        **kwargs,
    ) -> list[dict[str, Any]]:
        all_txs: list[dict[str, Any]] = []
        before: str | None = None
        for _ in range(max_pages):
            batch = await self.get_transactions_for_address(
                address, limit=page_size, before_signature=before, **kwargs
            )
            if not batch:
                break
            all_txs.extend(batch)
            before = batch[-1].get("signature")
            if len(batch) < page_size:
                break
        return all_txs

    async def parse_transactions(
        self,
        signatures: list[str],
        *,
        commitment: str = "finalized",
    ) -> list[dict[str, Any]]:
        if not signatures:
            return []
        if len(signatures) > 100:
            raise ValueError("Helius: max 100 signatures per parse_transactions call")
        body = {"transactions": signatures, "commitment": commitment}
        return await self.post_json("/v0/transactions", params=self._key_qs, json=body)

    # ── Standard Solana RPC (via dedicated mainnet RPC URL) ──
    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    async def _rpc(self, method: str, params: list[Any] | None = None) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params or [],
        }
        # rpc lives on a different host than self.base_url; use the underlying httpx client
        # but pass an absolute URL — httpx supports that when base_url is set.
        response = await self._client.post(self._rpc_url, json=payload)
        if response.status_code != 200:
            raise ExternalAPIError(
                f"helius RPC {method} HTTP {response.status_code}",
                provider=self.provider_name,
                upstream_status=response.status_code,
            )
        data = response.json()
        if "error" in data and data["error"]:
            err = data["error"]
            raise ExternalAPIError(
                f"helius RPC error {method}: {err.get('message')}",
                provider=self.provider_name,
                details={"code": err.get("code"), "rpc_method": method},
            )
        return data.get("result")

    async def get_balance_lamports(self, address: str) -> int:
        result = await self._rpc("getBalance", [address])
        if isinstance(result, dict):
            return int(result.get("value", 0))
        return int(result or 0)

    async def get_balance_sol(self, address: str) -> float:
        return await self.get_balance_lamports(address) / LAMPORTS_PER_SOL

    async def get_token_accounts_by_owner(self, owner: str) -> list[dict[str, Any]]:
        result = await self._rpc(
            "getTokenAccountsByOwner",
            [owner, {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
             {"encoding": "jsonParsed"}],
        )
        return (result or {}).get("value", []) if isinstance(result, dict) else []

    async def get_assets_by_owner(self, owner: str, *, page: int = 1, limit: int = 100) -> dict:
        """DAS API method `getAssetsByOwner` (NFTs + tokens)."""
        result = await self._rpc(
            "getAssetsByOwner",
            [{"ownerAddress": owner, "page": page, "limit": limit,
              "displayOptions": {"showFungible": True}}],
        )
        return result or {}

    # ── Webhooks management ──
    async def create_webhook(
        self,
        *,
        webhook_url: str,
        addresses: list[str],
        transaction_types: list[str] | None = None,
        webhook_type: str = "enhanced",
        auth_header: str | None = None,
    ) -> dict[str, Any]:
        body = {
            "webhookURL": webhook_url,
            "transactionTypes": transaction_types or ["Any"],
            "accountAddresses": addresses,
            "webhookType": webhook_type,
        }
        if auth_header:
            body["authHeader"] = auth_header
        return await self.post_json("/v0/webhooks", params=self._key_qs, json=body)

    async def list_webhooks(self) -> list[dict[str, Any]]:
        return await self.get_json("/v0/webhooks", params=self._key_qs)

    async def delete_webhook(self, webhook_id: str) -> bool:
        await self.request("DELETE", f"/v0/webhooks/{webhook_id}",
                           params=self._key_qs, expect_status=(200, 204))
        return True

    async def edit_webhook(
        self,
        webhook_id: str,
        *,
        addresses: list[str] | None = None,
        transaction_types: list[str] | None = None,
        webhook_url: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if addresses is not None:
            body["accountAddresses"] = addresses
        if transaction_types is not None:
            body["transactionTypes"] = transaction_types
        if webhook_url is not None:
            body["webhookURL"] = webhook_url
        r = await self.request("PUT", f"/v0/webhooks/{webhook_id}",
                               params=self._key_qs, json=body)
        return r.json()

    # ── Domain mapping (static so it can be called without a live adapter) ──
    @staticmethod
    def map_enhanced_to_tx(raw: dict[str, Any]) -> TransactionNode | None:
        """Map an Enhanced Transactions API entry → canonical TransactionNode.

        Returns None if the tx has no usable transfer information.
        We collapse the multi-leg parsed event into one canonical node by picking
        the first native or token transfer and tagging the rest into `raw`.
        """
        sig = raw.get("signature")
        ts_unix = raw.get("timestamp")
        if not sig:
            return None
        ts = datetime.fromtimestamp(ts_unix, tz=timezone.utc) if ts_unix else \
            datetime.now(timezone.utc)

        from_addr: str | None = raw.get("feePayer")
        to_addr: str | None = None
        value: float = 0.0
        asset = "SOL"

        natives = raw.get("nativeTransfers") or []
        tokens = raw.get("tokenTransfers") or []
        if natives:
            first = natives[0]
            from_addr = first.get("fromUserAccount") or from_addr
            to_addr = first.get("toUserAccount")
            value = (first.get("amount") or 0) / LAMPORTS_PER_SOL
        elif tokens:
            first = tokens[0]
            from_addr = first.get("fromUserAccount") or from_addr
            to_addr = first.get("toUserAccount")
            value = float(first.get("tokenAmount") or 0)
            asset = first.get("mint") or "SPL"

        return TransactionNode(
            hash=sig,
            chain=Chain.SOL,
            from_address=from_addr or "",
            to_address=to_addr,
            value_native=value,
            asset=asset,
            timestamp=ts,
            block_number=raw.get("slot"),
            status=TxStatus.SUCCESS if not raw.get("transactionError") else TxStatus.FAILED,
            method=raw.get("type"),
            raw=raw,
        )
