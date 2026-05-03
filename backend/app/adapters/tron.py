"""TRON adapter via TronGrid public API (free, no API key required for basic calls).

Docs: https://developers.tron.network/reference
  • GET /v1/accounts/{address}/transactions      — TRC20 + TRX txs
  • GET /v1/accounts/{address}                   — account info
  • GET /v1/contracts/{contract}/tokens          — TRC20 token info
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.adapters.base import BaseHTTPAdapter
from app.core.exceptions import ExternalAPIError
from app.core.logging import get_logger
from app.models.domain import TransactionNode
from app.models.enums import Chain, TxStatus

logger = get_logger(__name__)

SUN = 1_000_000  # 1 TRX = 1,000,000 SUN


class TronAdapter(BaseHTTPAdapter):
    provider_name = "trongrid"
    requires_api_key = False

    def __init__(self) -> None:
        super().__init__(
            base_url="https://api.trongrid.io",
            api_key=None,
            timeout=30.0,
            max_retries=3,
            default_headers={"Accept": "application/json"},
        )

    async def get_account(self, address: str) -> dict[str, Any]:
        return await self.get_json(f"/v1/accounts/{address}")

    async def get_transactions(
        self,
        address: str,
        *,
        limit: int = 50,
        min_timestamp: int | None = None,
        only_confirmed: bool = True,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "limit": min(limit, 200),
            "order_by": "block_timestamp,desc",
            "only_confirmed": str(only_confirmed).lower(),
        }
        if min_timestamp:
            params["min_timestamp"] = min_timestamp
        data = await self.get_json(f"/v1/accounts/{address}/transactions", params=params)
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return []

    async def get_trc20_transactions(
        self, address: str, *, limit: int = 50,
    ) -> list[dict[str, Any]]:
        params = {"limit": min(limit, 200), "order_by": "block_timestamp,desc"}
        data = await self.get_json(
            f"/v1/accounts/{address}/transactions/trc20", params=params
        )
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return []

    def map_tx_to_node(self, raw: dict[str, Any]) -> TransactionNode | None:
        """Map a TronGrid TRX transaction → canonical TransactionNode."""
        txid = raw.get("txID")
        if not txid:
            return None

        ts_ms = raw.get("block_timestamp", 0)
        ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)

        raw_data = raw.get("raw_data") or {}
        contract = ((raw_data.get("contract") or [{}])[0])
        param = contract.get("parameter", {}).get("value", {})

        from_addr = param.get("owner_address", "")
        to_addr = param.get("to_address") or param.get("contract_address")
        amount_sun = param.get("amount", 0)

        return TransactionNode(
            hash=txid,
            chain=Chain.TRON,
            from_address=from_addr,
            to_address=to_addr,
            value_native=amount_sun / SUN,
            asset="TRX",
            timestamp=ts,
            status=TxStatus.SUCCESS if raw.get("ret", [{}])[0].get("contractRet") == "SUCCESS"
                   else TxStatus.FAILED,
            raw=raw,
        )

    def map_trc20_to_node(self, raw: dict[str, Any]) -> TransactionNode | None:
        """Map a TronGrid TRC20 transfer → canonical TransactionNode."""
        txid = raw.get("transaction_id")
        if not txid:
            return None

        ts_ms = raw.get("block_timestamp", 0)
        ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)

        token_info = raw.get("token_info") or {}
        decimals = int(token_info.get("decimals", 6))
        symbol = token_info.get("symbol", "TRC20")
        amount_raw = float(raw.get("value", 0))

        return TransactionNode(
            hash=txid,
            chain=Chain.TRON,
            from_address=raw.get("from", ""),
            to_address=raw.get("to"),
            value_native=amount_raw / (10 ** decimals),
            asset=symbol,
            timestamp=ts,
            status=TxStatus.SUCCESS,
            raw=raw,
        )
