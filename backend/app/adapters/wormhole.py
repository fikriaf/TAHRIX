"""WormholeScan API adapter — public, read-only.

Verified against https://api.wormholescan.io/api/v1/version (2026-04).
Endpoints used:
  • GET /api/v1/operations?address=&pageSize=&page=     — operations by address
  • GET /api/v1/operations/{id}                          — operation detail
  • GET /api/v1/vaas/{chainId}/{emitter}/{seq}           — VAA lookup
  • GET /api/v1/transactions?address=&pageSize=          — alt: TX list

Wormhole chain IDs follow the Wormhole-specific scheme (Solana=1, Ethereum=2,
BSC=4, Polygon=5, Base=30, …). We map a subset here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.adapters.base import BaseHTTPAdapter
from app.core.config import settings
from app.core.logging import get_logger
from app.models.domain import BridgeEvent, CrossChainTrace
from app.models.enums import BridgeProtocol, Chain

logger = get_logger(__name__)

# Wormhole chainId scheme (subset)
_WH_CHAIN: dict[int, Chain] = {
    1: Chain.SOL,
    2: Chain.ETH,
    4: Chain.BNB,
    5: Chain.POLYGON,
    30: Chain.BASE,
}


def _wh_chain(cid: int | None) -> Chain | None:
    if cid is None:
        return None
    return _WH_CHAIN.get(int(cid))


def _parse_iso(ts: str | None) -> datetime:
    if not ts:
        return datetime.now(timezone.utc)
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return datetime.now(timezone.utc)


class WormholeAdapter(BaseHTTPAdapter):
    provider_name = "wormholescan"
    requires_api_key = False

    def __init__(self) -> None:
        super().__init__(
            base_url=settings.wormholescan_api_url,
            api_key=None,
            timeout=20.0,
            max_retries=3,
            default_headers={"Accept": "application/json"},
        )

    async def get_operations_by_address(
        self, address: str, *, page: int = 0, page_size: int = 50,
    ) -> list[dict[str, Any]]:
        params = {"address": address, "page": page, "pageSize": page_size}
        data = await self.get_json("/operations", params=params)
        return (data or {}).get("operations") or []

    async def get_operation(self, op_id: str) -> dict[str, Any] | None:
        return await self.get_json(f"/operations/{op_id}")

    async def get_vaa(self, chain_id: int, emitter: str, sequence: int | str) -> dict[str, Any] | None:
        return await self.get_json(f"/vaas/{chain_id}/{emitter}/{sequence}")

    async def find_by_source_tx(self, tx_hash: str) -> dict[str, Any] | None:
        """Best-effort: lookup operation by source tx hash."""
        data = await self.get_json("/operations", params={"txHash": tx_hash, "pageSize": 1})
        ops = (data or {}).get("operations") or []
        return ops[0] if ops else None

    # ── Mapping ──
    @staticmethod
    def to_cross_chain_trace(op: dict[str, Any]) -> CrossChainTrace | None:
        src = op.get("sourceChain") or {}
        dst = op.get("targetChain") or {}
        src_chain = _wh_chain(src.get("chainId"))
        # destination might come as standarizedProperties
        std = (op.get("content") or {}).get("standarizedProperties") or {}
        dst_chain = _wh_chain(dst.get("chainId") or std.get("toChain"))
        if not src_chain or not dst_chain:
            return None
        return CrossChainTrace(
            protocol=BridgeProtocol.WORMHOLE,
            source_tx=(src.get("transaction") or {}).get("txHash", ""),
            dest_tx=(dst.get("transaction") or {}).get("txHash"),
            source_chain=src_chain,
            dest_chain=dst_chain,
            source_address=src.get("from") or std.get("fromAddress") or None,
            dest_address=(dst.get("to") or std.get("toAddress")),
            value_usd=None,
            message_id=op.get("id"),
            delivered=(dst.get("status") == "completed"),
            raw=op,
        )

    @staticmethod
    def to_bridge_event(op: dict[str, Any]) -> BridgeEvent | None:
        trace = WormholeAdapter.to_cross_chain_trace(op)
        if not trace:
            return None
        ts = _parse_iso((op.get("sourceChain") or {}).get("timestamp"))
        return BridgeEvent(
            id=f"wh:{op.get('id') or trace.source_tx}",
            protocol=BridgeProtocol.WORMHOLE,
            source_chain=trace.source_chain,
            dest_chain=trace.dest_chain,
            source_tx_hash=trace.source_tx,
            dest_tx_hash=trace.dest_tx,
            source_address=trace.source_address,
            dest_address=trace.dest_address,
            message_id=trace.message_id,
            timestamp=ts,
            value_usd=None,
            status=(op.get("targetChain") or {}).get("status"),
        )
