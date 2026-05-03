"""LayerZero Scan API adapter (mainnet, public read-only).

Verified against https://docs.layerzero.network/v2/tools/layerzeroscan/api (2026-04).
Endpoints used:
  • GET /v1/messages/tx/{txHash}        — lookup by source/dest tx hash
  • GET /v1/messages/guid/{guid}        — by message GUID
  • GET /v1/messages/wallet/{address}   — by source wallet
  • GET /v1/messages/oapp/{eid}/{addr}  — by OApp address

Each message response contains: source/destination chains, status (lifecycle),
DVN verification details, and execution status — exactly what we need to build
a `BridgeEvent` node in the graph.
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


# LayerZero "endpoint id" (eid) → our Chain enum (subset; extend as needed).
_EID_TO_CHAIN: dict[int, Chain] = {
    101: Chain.ETH, 30101: Chain.ETH,
    109: Chain.POLYGON, 30109: Chain.POLYGON,
    102: Chain.BNB, 30102: Chain.BNB,
    184: Chain.BASE, 30184: Chain.BASE,
    168: Chain.SOL, 30168: Chain.SOL,
}


def _eid_to_chain(eid: int | None) -> Chain | None:
    if eid is None:
        return None
    return _EID_TO_CHAIN.get(int(eid))


def _parse_iso(ts: str | None) -> datetime:
    if not ts:
        return datetime.now(timezone.utc)
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return datetime.now(timezone.utc)


class LayerZeroAdapter(BaseHTTPAdapter):
    provider_name = "layerzero_scan"
    requires_api_key = False  # public read-only

    def __init__(self) -> None:
        super().__init__(
            base_url=settings.layerzero_scan_url,
            api_key=None,
            timeout=20.0,
            max_retries=3,
            default_headers={"Accept": "application/json"},
        )

    async def get_messages_by_tx(self, tx_hash: str) -> list[dict[str, Any]]:
        data = await self.get_json(f"/messages/tx/{tx_hash}")
        return (data or {}).get("data") or []

    async def get_messages_by_wallet(self, address: str) -> list[dict[str, Any]]:
        data = await self.get_json(f"/messages/wallet/{address}")
        return (data or {}).get("data") or []

    async def get_message_by_guid(self, guid: str) -> dict[str, Any] | None:
        data = await self.get_json(f"/messages/guid/{guid}")
        items = (data or {}).get("data") or []
        return items[0] if items else None

    # ── Mapping ──
    @staticmethod
    def to_cross_chain_trace(msg: dict[str, Any]) -> CrossChainTrace | None:
        src = msg.get("source") or {}
        dst = msg.get("destination") or {}
        src_eid = (msg.get("pathway") or {}).get("srcEid")
        dst_eid = (msg.get("pathway") or {}).get("dstEid")
        src_chain = _eid_to_chain(src_eid)
        dst_chain = _eid_to_chain(dst_eid)
        if not src_chain or not dst_chain:
            return None
        return CrossChainTrace(
            protocol=BridgeProtocol.LAYERZERO,
            source_tx=src.get("tx", {}).get("txHash") or msg.get("guid", ""),
            dest_tx=dst.get("tx", {}).get("txHash"),
            source_chain=src_chain,
            dest_chain=dst_chain,
            source_address=(msg.get("pathway") or {}).get("sender", {}).get("address"),
            dest_address=(msg.get("pathway") or {}).get("receiver", {}).get("address"),
            message_id=msg.get("guid"),
            delivered=(msg.get("status", {}).get("name") == "DELIVERED"),
            raw=msg,
        )

    @staticmethod
    def to_bridge_event(msg: dict[str, Any]) -> BridgeEvent | None:
        trace = LayerZeroAdapter.to_cross_chain_trace(msg)
        if not trace:
            return None
        ts = _parse_iso((msg.get("source") or {}).get("tx", {}).get("blockTimestamp"))
        return BridgeEvent(
            id=f"lz:{msg.get('guid') or trace.source_tx}",
            protocol=BridgeProtocol.LAYERZERO,
            source_chain=trace.source_chain,
            dest_chain=trace.dest_chain,
            source_tx_hash=trace.source_tx,
            dest_tx_hash=trace.dest_tx,
            source_address=trace.source_address,
            dest_address=trace.dest_address,
            message_id=trace.message_id,
            timestamp=ts,
            value_usd=None,
            status=msg.get("status", {}).get("name"),
        )
