"""Stream ingestion: webhook payload → canonical TransactionNode → Neo4j.

Two entrypoints:
  - `ingest_helius_events(payload)`  — Helius enhanced-transaction webhook
  - `ingest_alchemy_events(payload)` — Alchemy activity / address webhook

Both convert provider-specific JSON to canonical `TransactionNode` objects and
bulk-upsert them to Neo4j via `GraphRepository`. Returns the count of
transactions successfully persisted.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.models.domain import TransactionNode
from app.repositories.graph_repository import GraphRepository

logger = get_logger(__name__)


# ── Helius (Solana) ────────────────────────────────────────────────────────────

async def ingest_helius_events(payload: Any) -> int:
    """Process a Helius enhanced-transaction webhook payload.

    Helius sends a JSON array of enhanced transaction objects. Each object is
    mapped to a `TransactionNode` and upserted into Neo4j.

    Docs: https://docs.helius.dev/webhooks-and-websockets/enhanced-transactions-api
    """
    if not isinstance(payload, list):
        payload = [payload]  # single-tx payloads are sometimes sent as a dict

    logger.info("ingest.helius.received", count=len(payload))

    txs: list[TransactionNode] = []
    try:
        from app.adapters.helius import HeliusAdapter
        for raw in payload:
            tx = HeliusAdapter.map_enhanced_to_tx(raw)
            if tx:
                txs.append(tx)
    except Exception as exc:  # noqa: BLE001
        logger.exception("ingest.helius.map_error", error=str(exc))

    if not txs:
        return 0

    try:
        await GraphRepository.upsert_transactions_bulk(txs)
        logger.info("ingest.helius.persisted", count=len(txs))
    except Exception as exc:  # noqa: BLE001
        logger.exception("ingest.helius.neo4j_error", error=str(exc))
        return 0

    return len(txs)


# ── Alchemy (Ethereum / EVM) ──────────────────────────────────────────────────

def _parse_alchemy_activity(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract raw transfer objects from an Alchemy webhook payload.

    Alchemy wraps activity in different shapes depending on webhook type:
      - `ACTIVITY` (address webhook): payload["event"]["activity"] list
      - `ADDRESS_ACTIVITY` (older format): payload["activity"] list
      - Direct array (rare): payload itself is a list
    """
    if isinstance(payload, list):
        return payload

    event = payload.get("event") or {}
    # ADDRESS_ACTIVITY / NFT_ACTIVITY webhooks
    activities = event.get("activity") or payload.get("activity") or []
    if activities:
        return activities

    # MINED_TRANSACTION webhook
    tx = event.get("transaction")
    if tx:
        return [tx]

    return []


async def ingest_alchemy_events(payload: Any) -> int:
    """Process an Alchemy webhook payload (address activity or mined-tx).

    Maps each activity entry to a `TransactionNode` and bulk-upserts to Neo4j.

    Docs: https://docs.alchemy.com/reference/address-activity-webhook
    """
    if not isinstance(payload, dict):
        logger.warning("ingest.alchemy.unexpected_type", type=type(payload).__name__)
        return 0

    webhook_type = payload.get("type", "UNKNOWN")
    logger.info("ingest.alchemy.received", webhook_type=webhook_type)

    raw_activities = _parse_alchemy_activity(payload)
    if not raw_activities:
        logger.info("ingest.alchemy.no_activity")
        return 0

    txs: list[TransactionNode] = []
    try:
        from app.adapters.alchemy import AlchemyAdapter
        # AlchemyAdapter is chain-aware; default ETH for webhook ingestion.
        # The chain is overridden per-activity if `network` field is present.
        adapter = AlchemyAdapter(chain="ETH")
        for raw in raw_activities:
            # Alchemy activity items have slightly different shape than
            # getAssetTransfers — normalise to match map_transfer_to_tx expectations.
            normalised = _normalise_activity(raw)
            try:
                tx = adapter.map_transfer_to_tx(normalised)
                txs.append(tx)
            except Exception as item_exc:  # noqa: BLE001
                logger.warning("ingest.alchemy.item_skip",
                               error=str(item_exc), hash=raw.get("hash") or raw.get("txHash"))
    except Exception as exc:  # noqa: BLE001
        logger.exception("ingest.alchemy.map_error", error=str(exc))

    if not txs:
        return 0

    try:
        await GraphRepository.upsert_transactions_bulk(txs)
        logger.info("ingest.alchemy.persisted", count=len(txs))
    except Exception as exc:  # noqa: BLE001
        logger.exception("ingest.alchemy.neo4j_error", error=str(exc))
        return 0

    return len(txs)


def _normalise_activity(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise an Alchemy activity entry to the shape expected by
    `AlchemyAdapter.map_transfer_to_tx`.

    Activity entries use `fromAddress`/`toAddress` (camelCase), while
    getAssetTransfers uses `from`/`to`. We bridge that here.
    """
    return {
        "hash": raw.get("hash") or raw.get("txHash") or "",
        "from": raw.get("fromAddress") or raw.get("from") or "",
        "to": raw.get("toAddress") or raw.get("to"),
        "value": raw.get("value"),
        "asset": raw.get("asset"),
        "category": raw.get("category", "external"),
        "blockNum": raw.get("blockNum"),
        "metadata": {
            "blockTimestamp": raw.get("blockTimestamp"),
        },
        "rawContract": raw.get("rawContract") or {},
    }
