"""Bitcoin adapter via Blockstream.info public API (no API key required).

Endpoints verified against https://blockstream.info/api/
  • GET /address/{address}                      — address stats
  • GET /address/{address}/txs                  — transactions (25 per page)
  • GET /address/{address}/txs/chain/{last_txid} — paginate
  • GET /tx/{txid}                              — single transaction
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

SATOSHI = 100_000_000  # sats per BTC


class BlockstreamAdapter(BaseHTTPAdapter):
    provider_name = "blockstream"
    requires_api_key = False

    def __init__(self) -> None:
        super().__init__(
            base_url="https://blockstream.info/api",
            api_key=None,
            timeout=30.0,
            max_retries=3,
        )

    async def get_address_info(self, address: str) -> dict[str, Any]:
        data = await self.get_json(f"/address/{address}")
        if "error" in data:
            raise ExternalAPIError(
                f"Blockstream address error: {data['error']}",
                provider=self.provider_name,
            )
        return data

    async def get_transactions(
        self, address: str, *, limit: int = 25, last_txid: str | None = None,
    ) -> list[dict[str, Any]]:
        path = f"/address/{address}/txs"
        if last_txid:
            path += f"/chain/{last_txid}"
        data = await self.get_json(path)
        if isinstance(data, list):
            return data[:limit]
        return []

    async def iter_transactions(
        self, address: str, *, max_pages: int = 3,
    ) -> list[dict[str, Any]]:
        all_txs: list[dict[str, Any]] = []
        last_txid: str | None = None
        for _ in range(max_pages):
            page = await self.get_transactions(address, last_txid=last_txid)
            if not page:
                break
            all_txs.extend(page)
            last_txid = page[-1].get("txid")
        return all_txs

    def map_tx_to_node(self, raw: dict[str, Any], address: str) -> TransactionNode | None:
        """Map a Blockstream tx dict → canonical TransactionNode.

        BTC is UTXO — we look for the first output NOT going back to the
        same address as the 'to' address, and sum inputs from `address` as value.
        """
        txid = raw.get("txid")
        if not txid:
            return None

        status = raw.get("status") or {}
        block_time = status.get("block_time")
        ts = datetime.fromtimestamp(block_time, tz=timezone.utc) if block_time \
            else datetime.now(timezone.utc)

        # Find inputs from our address (spending)
        value_out_sat = 0
        to_address: str | None = None
        is_sender = False

        for inp in raw.get("vin", []):
            prev = inp.get("prevout") or {}
            if prev.get("scriptpubkey_address") == address:
                is_sender = True

        for out in raw.get("vout", []):
            out_addr = out.get("scriptpubkey_address")
            out_val = out.get("value", 0)  # satoshis
            if out_addr and out_addr != address:
                to_address = out_addr
                value_out_sat = out_val
                break

        if is_sender:
            from_address = address
        else:
            # We are receiver — find first input address as sender
            first_inp = (raw.get("vin") or [{}])[0]
            from_address = (first_inp.get("prevout") or {}).get("scriptpubkey_address") or "unknown"
            to_address = address
            value_out_sat = sum(
                o.get("value", 0) for o in raw.get("vout", [])
                if o.get("scriptpubkey_address") == address
            )

        return TransactionNode(
            hash=txid,
            chain=Chain.BTC,
            from_address=from_address,
            to_address=to_address,
            value_native=value_out_sat / SATOSHI,
            asset="BTC",
            timestamp=ts,
            block_number=status.get("block_height"),
            status=TxStatus.SUCCESS if status.get("confirmed") else TxStatus.PENDING,
            raw=raw,
        )
