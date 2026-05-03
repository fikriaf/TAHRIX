"""Cypher schema bootstrap: constraints + indexes.

Run on app startup (idempotent — `IF NOT EXISTS`).
Source of truth for the full multi-layer property graph:
  - Wallet          : blockchain addresses
  - Transaction     : on-chain transfers
  - BridgeEvent     : cross-chain hops (LayerZero, Wormhole)
  - Entity          : named entities (mixer, exchange, darknet, sanctioned)
  - AnomalyPattern  : detected anomaly flags (P01-P17) per investigation
  - OsintNode       : OSINT artifacts (domain, IP, company, email, social)
  - ThreatIntel     : threat intelligence hits (darkweb mentions, leaked keys)
  - InvestigationCase: case tracking node
  - ChainNetwork    : blockchain network nodes (ETH, SOL, BTC, TRON, ...)
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.db.neo4j import run_query

logger = get_logger(__name__)

# Constraints: uniqueness + node-key
_CONSTRAINTS: list[str] = [
    # Wallet uniqueness scoped per chain
    "CREATE CONSTRAINT wallet_addr_chain IF NOT EXISTS "
    "FOR (w:Wallet) REQUIRE (w.address, w.chain) IS NODE KEY",
    "CREATE CONSTRAINT tx_hash IF NOT EXISTS "
    "FOR (t:Transaction) REQUIRE (t.hash, t.chain) IS NODE KEY",
    "CREATE CONSTRAINT bridge_id IF NOT EXISTS "
    "FOR (b:BridgeEvent) REQUIRE b.id IS UNIQUE",
    "CREATE CONSTRAINT entity_name IF NOT EXISTS "
    "FOR (e:Entity) REQUIRE e.name IS UNIQUE",
    "CREATE CONSTRAINT case_id IF NOT EXISTS "
    "FOR (c:InvestigationCase) REQUIRE c.case_id IS UNIQUE",
    # New node types
    "CREATE CONSTRAINT anomaly_id IF NOT EXISTS "
    "FOR (a:AnomalyPattern) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT osint_id IF NOT EXISTS "
    "FOR (o:OsintNode) REQUIRE o.id IS UNIQUE",
    "CREATE CONSTRAINT threat_id IF NOT EXISTS "
    "FOR (t:ThreatIntel) REQUIRE t.id IS UNIQUE",
    "CREATE CONSTRAINT chain_name IF NOT EXISTS "
    "FOR (c:ChainNetwork) REQUIRE c.name IS UNIQUE",
]

# Indexes for traversal performance
_INDEXES: list[str] = [
    "CREATE INDEX wallet_address IF NOT EXISTS FOR (w:Wallet) ON (w.address)",
    "CREATE INDEX wallet_risk IF NOT EXISTS FOR (w:Wallet) ON (w.risk_score)",
    "CREATE INDEX wallet_sanctioned IF NOT EXISTS FOR (w:Wallet) ON (w.is_sanctioned)",
    "CREATE INDEX wallet_entity IF NOT EXISTS FOR (w:Wallet) ON (w.entity_label)",
    "CREATE INDEX tx_timestamp IF NOT EXISTS FOR (t:Transaction) ON (t.timestamp)",
    "CREATE INDEX tx_value IF NOT EXISTS FOR (t:Transaction) ON (t.value_usd)",
    "CREATE INDEX bridge_protocol IF NOT EXISTS FOR (b:BridgeEvent) ON (b.protocol)",
    "CREATE INDEX bridge_src_chain IF NOT EXISTS FOR (b:BridgeEvent) ON (b.source_chain)",
    "CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.type)",
    "CREATE INDEX entity_risk IF NOT EXISTS FOR (e:Entity) ON (e.risk_level)",
    "CREATE INDEX anomaly_code IF NOT EXISTS FOR (a:AnomalyPattern) ON (a.code)",
    "CREATE INDEX anomaly_case IF NOT EXISTS FOR (a:AnomalyPattern) ON (a.case_id)",
    "CREATE INDEX osint_type IF NOT EXISTS FOR (o:OsintNode) ON (o.type)",
    "CREATE INDEX osint_value IF NOT EXISTS FOR (o:OsintNode) ON (o.value)",
    "CREATE INDEX threat_source IF NOT EXISTS FOR (t:ThreatIntel) ON (t.source)",
    "CREATE INDEX rel_sentto_ts IF NOT EXISTS FOR ()-[r:SENT_TO]-() ON (r.timestamp)",
    "CREATE INDEX rel_flagged_code IF NOT EXISTS FOR ()-[r:FLAGGED_BY]-() ON (r.code)",
]

# Seed static chain network nodes on startup
_CHAIN_SEEDS: list[dict] = [
    {"name": "ETH",     "full_name": "Ethereum",      "type": "EVM",     "color": "#627EEA"},
    {"name": "SOL",     "full_name": "Solana",         "type": "L1",      "color": "#9945FF"},
    {"name": "BTC",     "full_name": "Bitcoin",        "type": "UTXO",    "color": "#F7931A"},
    {"name": "TRON",    "full_name": "TRON",           "type": "EVM",     "color": "#FF0013"},
    {"name": "BASE",    "full_name": "Base",           "type": "EVM-L2",  "color": "#0052FF"},
    {"name": "POLYGON", "full_name": "Polygon",        "type": "EVM-L2",  "color": "#8247E5"},
    {"name": "ARB",     "full_name": "Arbitrum",       "type": "EVM-L2",  "color": "#28A0F0"},
    {"name": "BSC",     "full_name": "BNB Smart Chain","type": "EVM",     "color": "#F3BA2F"},
]


async def init_graph_schema() -> None:
    for stmt in (*_CONSTRAINTS, *_INDEXES):
        await run_query(stmt, write=True)

    # Seed ChainNetwork nodes (idempotent MERGE)
    for chain in _CHAIN_SEEDS:
        await run_query(
            "MERGE (c:ChainNetwork {name: $name}) "
            "SET c.full_name = $full_name, c.type = $type, c.color = $color",
            chain, write=True,
        )

    logger.info(
        "neo4j.schema.initialized",
        constraints=len(_CONSTRAINTS),
        indexes=len(_INDEXES),
        chain_seeds=len(_CHAIN_SEEDS),
    )
