"""Alchemy adapter — Ethereum + EVM L2 (Base, Polygon).

Endpoints used (verified against official docs at docs.alchemy.com, 2026-04):
  • alchemy_getAssetTransfers          — historical transfers (ext, int, erc20/721/1155)
  • trace_transaction                  — full execution trace (Pay-as-you-go+ tier)
  • eth_getTransactionByHash           — single tx detail
  • eth_getBalance                     — native balance (wei, hex)
  • alchemy_getTokenBalances           — ERC-20 holdings

All endpoints share a single JSON-RPC POST to https://{network}.g.alchemy.com/v2/{KEY}.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from app.adapters.base import BaseHTTPAdapter
from app.core.config import settings
from app.core.exceptions import ConfigurationError, ExternalAPIError
from app.core.logging import get_logger
from app.models.domain import TransactionNode
from app.models.enums import Chain, TxStatus

logger = get_logger(__name__)

# Map our Chain enum → Alchemy network host (taken from settings so they stay configurable)
_NETWORK_URLS = {
    Chain.ETH: "alchemy_eth_url",
    Chain.BASE: "alchemy_base_url",
    Chain.POLYGON: "alchemy_polygon_url",
}

# Categories supported per chain (per OpenRPC: 'internal' is ETH+Polygon only)
_CATEGORY_BY_CHAIN: dict[Chain, list[str]] = {
    Chain.ETH: ["external", "internal", "erc20", "erc721", "erc1155"],
    Chain.BASE: ["external", "erc20", "erc721", "erc1155"],
    Chain.POLYGON: ["external", "internal", "erc20", "erc721", "erc1155"],
}


def _hex_to_int(h: str | None) -> int | None:
    if h is None:
        return None
    try:
        return int(h, 16)
    except (TypeError, ValueError):
        return None


def _wei_to_eth(hex_wei: str | None) -> float | None:
    n = _hex_to_int(hex_wei)
    return None if n is None else n / 1e18


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    # Alchemy uses 2024-…Z form
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


class AlchemyAdapter(BaseHTTPAdapter):
    provider_name = "alchemy"
    requires_api_key = True

    def __init__(self, chain: Chain = Chain.ETH) -> None:
        if chain not in _NETWORK_URLS:
            raise ConfigurationError(f"Alchemy: unsupported chain {chain}")
        api_key_secret = settings.alchemy_api_key
        if not api_key_secret:
            raise ConfigurationError("ALCHEMY_API_KEY missing")
        api_key = api_key_secret.get_secret_value()

        base_root = getattr(settings, _NETWORK_URLS[chain]).rstrip("/")
        # Append API key path-segment style
        url = f"{base_root}/{api_key}"
        super().__init__(
            base_url=url,
            api_key=api_key,
            timeout=30.0,
            max_retries=4,
            default_headers={"Content-Type": "application/json"},
        )
        self.chain = chain
        self._req_id = 0

    # ── JSON-RPC envelope ──
    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    async def _rpc(self, method: str, params: list[Any]) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params,
        }
        data = await self.post_json("", json=payload)
        if "error" in data and data["error"]:
            err = data["error"]
            raise ExternalAPIError(
                f"alchemy.{method} error: {err.get('message')}",
                provider=self.provider_name,
                details={"code": err.get("code"), "rpc_method": method},
            )
        return data.get("result")

    # ── Public methods ──
    async def get_balance_wei(self, address: str, *, block: str = "latest") -> int:
        result = await self._rpc("eth_getBalance", [address, block])
        return _hex_to_int(result) or 0

    async def get_balance_eth(self, address: str) -> float:
        wei = await self.get_balance_wei(address)
        return wei / 1e18

    async def get_token_balances(
        self,
        address: str,
        *,
        contracts: list[str] | None = None,
        max_count: int = 100,
    ) -> list[dict[str, Any]]:
        token_spec: Any = contracts if contracts else "erc20"
        params: list[Any] = [address, token_spec]
        if not contracts:
            params.append({"maxCount": max_count})
        result = await self._rpc("alchemy_getTokenBalances", params)
        return (result or {}).get("tokenBalances", [])

    async def get_transaction(self, tx_hash: str) -> dict[str, Any] | None:
        return await self._rpc("eth_getTransactionByHash", [tx_hash])

    async def trace_transaction(self, tx_hash: str) -> list[dict[str, Any]]:
        """Full execution trace (requires Pay-as-you-go+ tier)."""
        result = await self._rpc("trace_transaction", [tx_hash])
        # Alchemy sometimes returns nested {result: [...]} envelope around the value.
        if isinstance(result, dict) and "result" in result:
            result = result["result"]
        if not isinstance(result, list):
            return []
        # Some examples wrap items as {name, value:{...}} — flatten.
        flat: list[dict[str, Any]] = []
        for item in result:
            if isinstance(item, dict) and "value" in item and "action" not in item:
                flat.append(item["value"])
            else:
                flat.append(item)
        return flat

    async def get_asset_transfers(
        self,
        *,
        from_address: str | None = None,
        to_address: str | None = None,
        from_block: str = "0x0",
        to_block: str = "latest",
        categories: Iterable[str] | None = None,
        contract_addresses: list[str] | None = None,
        max_count: int = 1000,
        order: str = "desc",
        page_key: str | None = None,
        with_metadata: bool = True,
        exclude_zero_value: bool = True,
    ) -> dict[str, Any]:
        """Single page of transfers. Use `iter_asset_transfers` for full history."""
        if not from_address and not to_address:
            raise ValueError("at least one of from_address/to_address required")

        cats = list(categories) if categories else _CATEGORY_BY_CHAIN[self.chain]
        params_obj: dict[str, Any] = {
            "fromBlock": from_block,
            "toBlock": to_block,
            "category": cats,
            "withMetadata": with_metadata,
            "excludeZeroValue": exclude_zero_value,
            "maxCount": hex(max_count),
            "order": order,
        }
        if from_address:
            params_obj["fromAddress"] = from_address
        if to_address:
            params_obj["toAddress"] = to_address
        if contract_addresses:
            params_obj["contractAddresses"] = contract_addresses
        if page_key:
            params_obj["pageKey"] = page_key

        result = await self._rpc("alchemy_getAssetTransfers", [params_obj])
        return result or {"transfers": [], "pageKey": ""}

    async def iter_asset_transfers(
        self,
        address: str,
        *,
        direction: str = "both",  # 'in', 'out', 'both'
        max_pages: int = 5,
        **kwargs,
    ) -> list[dict[str, Any]]:
        """Aggregate transfers (in + out) across pages."""
        directions: list[tuple[str, str]] = []
        if direction in ("out", "both"):
            directions.append(("from", address))
        if direction in ("in", "both"):
            directions.append(("to", address))

        all_transfers: list[dict[str, Any]] = []
        seen: set[str] = set()
        for kind, addr in directions:
            page_key: str | None = None
            for _ in range(max_pages):
                kw = dict(kwargs)
                if kind == "from":
                    kw["from_address"] = addr
                else:
                    kw["to_address"] = addr
                kw["page_key"] = page_key
                page = await self.get_asset_transfers(**kw)
                for t in page.get("transfers", []):
                    uid = t.get("uniqueId") or t.get("hash")
                    if uid and uid not in seen:
                        seen.add(uid)
                        all_transfers.append(t)
                page_key = page.get("pageKey") or None
                if not page_key:
                    break
        return all_transfers

    # ── Domain mapping ──
    def map_transfer_to_tx(self, raw: dict[str, Any]) -> TransactionNode:
        """Map an alchemy_getAssetTransfers item → canonical TransactionNode."""
        block = _hex_to_int(raw.get("blockNum"))
        ts = _parse_iso((raw.get("metadata") or {}).get("blockTimestamp")) \
            or datetime.now(timezone.utc)
        value = raw.get("value")
        if value is None:
            value = 0.0
        return TransactionNode(
            hash=raw["hash"],
            chain=self.chain,
            from_address=raw["from"],
            to_address=raw.get("to"),
            value_native=float(value or 0),
            asset=raw.get("asset"),
            timestamp=ts,
            block_number=block,
            status=TxStatus.SUCCESS,  # transfers are post-confirmation
            raw=raw,
        )
