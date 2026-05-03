"""Etherscan V2 unified multichain adapter (verified against docs.etherscan.io, 2026-04).

Single base URL https://api.etherscan.io/v2/api with `chainid` query param to switch
between 60+ supported chains (1 = Ethereum, 8453 = Base, 137 = Polygon, 56 = BNB).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.adapters.base import BaseHTTPAdapter
from app.core.config import settings
from app.core.exceptions import ConfigurationError, ExternalAPIError
from app.core.logging import get_logger
from app.models.domain import EntityLabel, TransactionNode
from app.models.enums import Chain, EntityType, TxStatus

logger = get_logger(__name__)

CHAIN_IDS: dict[Chain, int] = {
    Chain.ETH: 1,
    Chain.BASE: 8453,
    Chain.POLYGON: 137,
    Chain.BNB: 56,
}


def _ts_to_dt(ts: str | int | None) -> datetime | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


# Light heuristics: map an Etherscan label to an EntityType.
def _label_to_entity_type(labels: list[str]) -> EntityType:
    joined = " ".join(labels).lower()
    if "exchange" in joined or "binance" in joined or "coinbase" in joined or "kraken" in joined:
        return EntityType.EXCHANGE
    if "mixer" in joined or "tornado" in joined or "sinbad" in joined:
        return EntityType.MIXER
    if "darknet" in joined or "ransomware" in joined:
        return EntityType.DARKNET
    if "defi" in joined or "uniswap" in joined or "aave" in joined:
        return EntityType.DEFI
    if "bridge" in joined or "stargate" in joined or "wormhole" in joined:
        return EntityType.BRIDGE
    if "ofac" in joined or "sanction" in joined:
        return EntityType.SANCTIONED
    return EntityType.UNKNOWN


class EtherscanAdapter(BaseHTTPAdapter):
    provider_name = "etherscan"
    requires_api_key = True

    def __init__(self) -> None:
        if not settings.etherscan_api_key:
            raise ConfigurationError("ETHERSCAN_API_KEY missing")
        api_key = settings.etherscan_api_key.get_secret_value()
        super().__init__(
            base_url=settings.etherscan_api_url,
            api_key=api_key,
            timeout=20.0,
            max_retries=4,
        )

    async def _query(self, *, chain: Chain, module: str, action: str, **params: Any) -> Any:
        if chain not in CHAIN_IDS:
            raise ConfigurationError(f"Etherscan: chain {chain} not supported")
        q: dict[str, Any] = {
            "chainid": CHAIN_IDS[chain],
            "module": module,
            "action": action,
            "apikey": self.api_key,
        }
        for k, v in params.items():
            if v is None:
                continue
            q[k] = v
        data = await self.get_json("", params=q)
        # Etherscan: success → status="1", message="OK", result=<...>
        # not-found → status="0", message="No transactions found", result=[]
        # error    → status="0", message="NOTOK", result="<error string>"
        status = str(data.get("status"))
        message = data.get("message", "")
        result = data.get("result")
        if status == "1":
            return result
        if status == "0" and message in ("No transactions found", "No records found"):
            return []
        if status == "0":
            raise ExternalAPIError(
                f"etherscan {module}.{action}: {message} ({result})",
                provider=self.provider_name,
                details={"chain": chain.value, "module": module, "action": action},
            )
        return result

    # ── Transactions ──
    async def list_normal_txs(
        self,
        address: str,
        *,
        chain: Chain = Chain.ETH,
        start_block: int = 0,
        end_block: int = 99_999_999,
        page: int = 1,
        offset: int = 100,
        sort: str = "desc",
    ) -> list[dict[str, Any]]:
        return await self._query(
            chain=chain, module="account", action="txlist",
            address=address, startblock=start_block, endblock=end_block,
            page=page, offset=offset, sort=sort,
        ) or []

    async def list_internal_txs(
        self, address: str, *, chain: Chain = Chain.ETH,
        start_block: int = 0, end_block: int = 99_999_999,
        page: int = 1, offset: int = 100, sort: str = "desc",
    ) -> list[dict[str, Any]]:
        return await self._query(
            chain=chain, module="account", action="txlistinternal",
            address=address, startblock=start_block, endblock=end_block,
            page=page, offset=offset, sort=sort,
        ) or []

    async def list_token_txs(
        self, address: str, *, chain: Chain = Chain.ETH,
        contract_address: str | None = None,
        page: int = 1, offset: int = 100, sort: str = "desc",
    ) -> list[dict[str, Any]]:
        return await self._query(
            chain=chain, module="account", action="tokentx",
            address=address, contractaddress=contract_address,
            page=page, offset=offset, sort=sort,
        ) or []

    # ── Contracts ──
    async def get_contract_source(
        self, address: str, *, chain: Chain = Chain.ETH,
    ) -> dict[str, Any] | None:
        result = await self._query(
            chain=chain, module="contract", action="getsourcecode", address=address,
        )
        if isinstance(result, list) and result:
            return result[0]
        return None

    async def get_contract_abi(
        self, address: str, *, chain: Chain = Chain.ETH,
    ) -> str | None:
        try:
            return await self._query(
                chain=chain, module="contract", action="getabi", address=address,
            )
        except ExternalAPIError:
            return None

    # ── Address tag (Pro Plus) ──
    async def get_address_metadata(
        self, address: str, *, chain: Chain = Chain.ETH,
    ) -> EntityLabel | None:
        """Fetch nametag/labels (Pro Plus tier — gracefully degrade if unavailable)."""
        try:
            result = await self._query(
                chain=chain, module="nametag", action="getaddresstag", address=address,
            )
        except ExternalAPIError as e:
            # Pro Plus required → skip silently
            logger.info("etherscan.nametag.unavailable", error=e.message)
            return None
        if not result or not isinstance(result, list):
            return None
        first = result[0]
        labels = first.get("labels") or []
        nametag = first.get("nametag") or first.get("internal_nametag")
        if not nametag and not labels:
            return None
        return EntityLabel(
            name=nametag or (labels[0] if labels else address[:8]),
            type=_label_to_entity_type(labels),
            source="ETHERSCAN_TAG",
            risk_level=None,
        )

    async def get_balance_wei(
        self, address: str, *, chain: Chain = Chain.ETH,
    ) -> int:
        result = await self._query(
            chain=chain, module="account", action="balance",
            address=address, tag="latest",
        )
        try:
            return int(result)
        except (TypeError, ValueError):
            return 0

    # ── Domain mapping ──
    @staticmethod
    def map_normal_tx(raw: dict[str, Any], chain: Chain) -> TransactionNode:
        ts = _ts_to_dt(raw.get("timeStamp")) or datetime.now(timezone.utc)
        # Native value on Etherscan is in wei (string). Convert to native units.
        try:
            value_native = int(raw.get("value") or 0) / 1e18
        except (TypeError, ValueError):
            value_native = 0.0
        status = TxStatus.SUCCESS
        if raw.get("isError") == "1" or raw.get("txreceipt_status") == "0":
            status = TxStatus.FAILED
        return TransactionNode(
            hash=raw["hash"],
            chain=chain,
            from_address=raw.get("from", ""),
            to_address=raw.get("to") or None,
            value_native=value_native,
            asset=chain.value,
            timestamp=ts,
            block_number=int(raw.get("blockNumber") or 0) or None,
            gas_used=int(raw.get("gasUsed") or 0) or None,
            status=status,
            method=raw.get("functionName") or raw.get("methodId"),
            raw=raw,
        )
