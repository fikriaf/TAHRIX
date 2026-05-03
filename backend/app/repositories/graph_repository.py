"""Neo4j repository: persistence + graph traversal for the full multi-layer graph.

Node types:
  Wallet          — blockchain addresses
  Transaction     — on-chain transfers
  BridgeEvent     — cross-chain hops (LayerZero, Wormhole)
  Entity          — named entities (mixer, exchange, darknet, sanctioned org)
  AnomalyPattern  — detected anomaly flags (P01-P17) per investigation
  OsintNode       — OSINT artifacts (domain, IP, email, company, social handle)
  ThreatIntel     — darkweb / threat-feed mentions
  ChainNetwork    — blockchain network meta-nodes
  InvestigationCase — case tracking node

Edge types:
  SENT_TO         — wallet → wallet (denormalized from Transaction)
  SENT / RECEIVED_BY — wallet ↔ Transaction
  BRIDGE_OUT/IN   — wallet ↔ BridgeEvent
  BRIDGE_TO       — cross-chain wallet→wallet via bridge
  LABELED_AS      — wallet → Entity
  FLAGGED_BY      — wallet → AnomalyPattern
  LINKED_TO       — wallet/entity → OsintNode
  MENTIONED_IN    — wallet/entity → ThreatIntel
  ON_CHAIN        — wallet → ChainNetwork
  INDIRECT_EXPOSURE — wallet → wallet (sanctioned 1-hop)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.logging import get_logger
from app.db.neo4j import run_query
from app.models.domain import (
    AnomalyFlag,
    BridgeEvent,
    OsintNode,
    ThreatIntelHit,
    TransactionNode,
    WalletNode,
)
from app.models.enums import Chain, GnnLabel

logger = get_logger(__name__)


def _addr(address: str | None) -> str | None:
    """Normalize EVM address to lowercase for consistent Neo4j keying.

    Neo4j MERGE is case-sensitive. Alchemy returns lowercase EVM addresses;
    Etherscan returns checksum (mixed-case). Without normalization, the same
    wallet gets two nodes and SENT_TO edges never connect to the focal seed node.

    IMPORTANT: Only lowercases EVM addresses (0x prefix).
    Solana (base58), BTC (bech32/legacy), TRON (T...) are case-sensitive
    in their respective APIs and must NOT be lowercased.
    """
    if address is None:
        return None
    if address.startswith("0x") or address.startswith("0X"):
        return address.lower()
    return address


# ─────────────────────────────────────────────────────────────────────────────
# Write-side
# ─────────────────────────────────────────────────────────────────────────────
class GraphRepository:
    """Stateless repository — all methods are async staticmethods."""

    @staticmethod
    async def upsert_wallet(wallet: WalletNode) -> None:
        await run_query(
            """
            MERGE (w:Wallet {address: $address, chain: $chain})
            ON CREATE SET
                w.first_seen = $now,
                w.tx_count = 0,
                w.gnn_label = 'UNKNOWN',
                w.is_contract = $is_contract
            SET w.last_seen = $now,
                w.balance_usd = coalesce($balance_usd, w.balance_usd),
                w.risk_score = coalesce($risk_score, w.risk_score),
                w.entity_label = coalesce($entity_label, w.entity_label),
                w.is_sanctioned = coalesce($is_sanctioned, w.is_sanctioned),
                w.gnn_label = coalesce($gnn_label, w.gnn_label)
            WITH w
            // Connect to ChainNetwork node
            MERGE (c:ChainNetwork {name: $chain})
            MERGE (w)-[:ON_CHAIN]->(c)
            """,
            {
                "address": _addr(wallet.address),
                "chain": wallet.chain.value,
                "now": (wallet.last_seen or datetime.now(timezone.utc)).isoformat(),
                "is_contract": wallet.is_contract,
                "balance_usd": wallet.balance_usd,
                "risk_score": wallet.risk_score,
                "entity_label": wallet.entity_label,
                "is_sanctioned": wallet.is_sanctioned,
                "gnn_label": wallet.gnn_label.value
                              if wallet.gnn_label != GnnLabel.UNKNOWN else None,
            },
            write=True,
        )

    @staticmethod
    async def upsert_transaction(tx: TransactionNode) -> None:
        await run_query(
            """
            MERGE (t:Transaction {hash: $hash, chain: $chain})
            ON CREATE SET
                t.value_usd = $value_usd,
                t.timestamp = $timestamp,
                t.block_number = $block_number,
                t.gas_used = $gas_used,
                t.status = $status,
                t.value_native = $value_native,
                t.asset = $asset,
                t.method = $method
            WITH t
            MERGE (sender:Wallet {address: $from_addr, chain: $chain})
              ON CREATE SET sender.first_seen = $timestamp, sender.tx_count = 0
              SET sender.last_seen = $timestamp, sender.tx_count = coalesce(sender.tx_count,0)+1
            MERGE (sender)-[:SENT]->(t)
            WITH t
            FOREACH (_ IN CASE WHEN $to_addr IS NULL THEN [] ELSE [1] END |
              MERGE (recv:Wallet {address: $to_addr, chain: $chain})
                ON CREATE SET recv.first_seen = $timestamp, recv.tx_count = 0
                SET recv.last_seen = $timestamp,
                    recv.tx_count = coalesce(recv.tx_count,0)+1
              MERGE (t)-[:RECEIVED_BY]->(recv)
            )
            WITH $from_addr AS f, $to_addr AS to_, $chain AS c, $hash AS h,
                 $value_usd AS vusd, $value_native AS vnat, $timestamp AS ts
            MATCH (a:Wallet {address: f, chain: c})
            OPTIONAL MATCH (b:Wallet {address: to_, chain: c})
            FOREACH (_ IN CASE WHEN b IS NULL THEN [] ELSE [1] END |
              MERGE (a)-[r:SENT_TO {tx_hash: h}]->(b)
              SET r.value_usd = vusd, r.value_native = vnat, r.timestamp = ts
            )
            """,
            {
                "hash": tx.hash,
                "chain": tx.chain.value,
                "value_usd": tx.value_usd,
                "value_native": tx.value_native,
                "asset": tx.asset,
                "timestamp": tx.timestamp.isoformat(),
                "block_number": tx.block_number,
                "gas_used": tx.gas_used,
                "status": tx.status.value,
                "method": tx.method,
                "from_addr": tx.from_address,
                "to_addr": tx.to_address,
            },
            write=True,
        )

    @staticmethod
    async def upsert_transactions_bulk(txs: list[TransactionNode]) -> int:
        rows = [
            {
                "hash": t.hash.lower() if t.hash else t.hash,
                "chain": t.chain.value,
                "value_usd": t.value_usd, "value_native": t.value_native,
                "asset": t.asset, "timestamp": t.timestamp.isoformat(),
                "block_number": t.block_number, "gas_used": t.gas_used,
                "status": t.status.value, "method": t.method,
                "from_addr": _addr(t.from_address),
                "to_addr": _addr(t.to_address),
            }
            for t in txs
        ]
        if not rows:
            return 0
        await run_query(
            """
            UNWIND $rows AS r
            MERGE (t:Transaction {hash: r.hash, chain: r.chain})
              ON CREATE SET t.value_usd = r.value_usd,
                            t.value_native = r.value_native, t.asset = r.asset,
                            t.timestamp = r.timestamp,
                            t.block_number = r.block_number,
                            t.gas_used = r.gas_used, t.status = r.status,
                            t.method = r.method
            MERGE (a:Wallet {address: r.from_addr, chain: r.chain})
              ON CREATE SET a.first_seen = r.timestamp, a.tx_count = 0
              SET a.last_seen = r.timestamp, a.tx_count = coalesce(a.tx_count,0)+1
            MERGE (a)-[:SENT]->(t)
            FOREACH (_ IN CASE WHEN r.to_addr IS NULL THEN [] ELSE [1] END |
              MERGE (b:Wallet {address: r.to_addr, chain: r.chain})
                ON CREATE SET b.first_seen = r.timestamp, b.tx_count = 0
                SET b.last_seen = r.timestamp, b.tx_count = coalesce(b.tx_count,0)+1
              MERGE (t)-[:RECEIVED_BY]->(b)
              MERGE (a)-[rel:SENT_TO {tx_hash: r.hash}]->(b)
              SET rel.value_usd = r.value_usd, rel.value_native = r.value_native,
                  rel.timestamp = r.timestamp
            )
            """,
            {"rows": rows},
            write=True,
        )
        return len(rows)

    @staticmethod
    async def upsert_bridge_event(ev: BridgeEvent) -> None:
        await run_query(
            """
            MERGE (b:BridgeEvent {id: $id})
            SET b.protocol = $protocol,
                b.source_chain = $src_chain,
                b.dest_chain = $dst_chain,
                b.source_tx_hash = $src_tx,
                b.dest_tx_hash = $dst_tx,
                b.message_id = $message_id,
                b.timestamp = $timestamp,
                b.value_usd = $value_usd,
                b.status = $status
            WITH b
            FOREACH (_ IN CASE WHEN $src_addr IS NULL THEN [] ELSE [1] END |
              MERGE (s:Wallet {address: $src_addr, chain: $src_chain})
              MERGE (s)-[:BRIDGE_OUT]->(b)
            )
            FOREACH (_ IN CASE WHEN $dst_addr IS NULL THEN [] ELSE [1] END |
              MERGE (d:Wallet {address: $dst_addr, chain: $dst_chain})
              MERGE (b)-[:BRIDGE_IN]->(d)
            )
            WITH b
            // Cross-chain direct edge: source_wallet -[BRIDGE_TO]-> dest_wallet
            FOREACH (_ IN CASE WHEN $src_addr IS NULL OR $dst_addr IS NULL THEN [] ELSE [1] END |
              MERGE (sw:Wallet {address: $src_addr, chain: $src_chain})
              MERGE (dw:Wallet {address: $dst_addr, chain: $dst_chain})
              MERGE (sw)-[br:BRIDGE_TO {bridge_id: $id}]->(dw)
              SET br.protocol = $protocol,
                  br.source_chain = $src_chain,
                  br.dest_chain = $dst_chain,
                  br.value_usd = $value_usd,
                  br.timestamp = $timestamp
            )
            """,
            {
                "id": ev.id,
                "protocol": ev.protocol.value,
                "src_chain": ev.source_chain.value,
                "dst_chain": ev.dest_chain.value,
                "src_tx": ev.source_tx_hash,
                "dst_tx": ev.dest_tx_hash,
                "message_id": ev.message_id,
                "timestamp": ev.timestamp.isoformat(),
                "value_usd": ev.value_usd,
                "status": ev.status,
                "src_addr": ev.source_address,
                "dst_addr": ev.dest_address,
            },
            write=True,
        )

    @staticmethod
    async def upsert_entity(
        name: str,
        entity_type: str,           # mixer | exchange | darknet | sanctioned_org | cex | dex
        *,
        risk_level: str | None = None,  # low | medium | high | critical
        source: str = "etherscan",
        metadata: dict | None = None,
    ) -> None:
        """Upsert a named Entity node (mixer, exchange, darknet market, etc.)."""
        await run_query(
            """
            MERGE (e:Entity {name: $name})
            SET e.type = $type,
                e.risk_level = coalesce($risk_level, e.risk_level),
                e.source = $source,
                e.metadata = $metadata
            """,
            {
                "name": name,
                "type": entity_type,
                "risk_level": risk_level,
                "source": source,
                "metadata": metadata or {},
            },
            write=True,
        )

    @staticmethod
    async def link_wallet_to_entity(
        address: str, chain: Chain, entity_name: str, *, relationship: str = "LABELED_AS",
    ) -> None:
        """Create (Wallet)-[:LABELED_AS|LINKED_TO]->(Entity) edge."""
        await run_query(
            f"""
            MATCH (w:Wallet {{address: $address, chain: $chain}})
            MERGE (e:Entity {{name: $entity_name}})
            MERGE (w)-[:{relationship}]->(e)
            SET w.entity_label = $entity_name
            """,
            {"address": _addr(address), "chain": chain.value, "entity_name": entity_name},
            write=True,
        )

    @staticmethod
    async def upsert_anomaly_flags(
        address: str, chain: Chain, case_id: str, flags: list[AnomalyFlag],
    ) -> None:
        """Persist anomaly pattern nodes and link them to the flagged wallet.

        Creates: (Wallet)-[:FLAGGED_BY {severity}]->(AnomalyPattern)
        """
        if not flags:
            return
        rows = [
            {
                "id": f"{case_id}:{f.code.value}",
                "code": f.code.value,
                "case_id": case_id,
                "severity": f.severity,
                "description": f.description,
                "evidence_txs": f.evidence_tx_hashes[:10],
                "metadata": f.metadata,
            }
            for f in flags
        ]
        await run_query(
            """
            UNWIND $rows AS r
            MERGE (a:AnomalyPattern {id: r.id})
            SET a.code = r.code,
                a.case_id = r.case_id,
                a.severity = r.severity,
                a.description = r.description,
                a.evidence_txs = r.evidence_txs
            WITH a, r
            MATCH (w:Wallet {address: $address, chain: $chain})
            MERGE (w)-[rel:FLAGGED_BY]->(a)
            SET rel.severity = r.severity, rel.code = r.code
            """,
            {"rows": rows, "address": _addr(address), "chain": chain.value},
            write=True,
        )

    @staticmethod
    async def upsert_osint_node(
        osint: OsintNode,
        *,
        link_chain: Chain | None = None,
    ) -> None:
        """Persist an OSINT artifact node and link it to its wallet via entity_ref."""
        import hashlib
        node_id = hashlib.sha256(f"{osint.entity_ref}:{osint.url or osint.snippet[:40]}".encode()).hexdigest()[:32]
        now_iso = (osint.retrieved_at or datetime.now(timezone.utc)).isoformat()
        await run_query(
            """
            MERGE (o:OsintNode {id: $id})
            SET o.source = $source,
                o.entity_ref = $entity_ref,
                o.url = $url,
                o.snippet = $snippet,
                o.platform = $platform,
                o.retrieved_at = $retrieved_at
            """,
            {
                "id": node_id,
                "source": osint.source,
                "entity_ref": _addr(osint.entity_ref) or osint.entity_ref,
                "url": osint.url,
                "snippet": osint.snippet[:300],
                "platform": osint.platform,
                "retrieved_at": now_iso,
            },
            write=True,
        )
        # Auto-link to Wallet node via entity_ref — try all known chains if no chain given
        chain_values = [link_chain.value] if link_chain else ["ETH", "BASE", "POLYGON", "BNB", "ARB", "BTC", "TRON", "SOL"]
        for ch in chain_values:
            await run_query(
                """
                OPTIONAL MATCH (w:Wallet {address: $address, chain: $chain})
                WITH w WHERE w IS NOT NULL
                MATCH (o:OsintNode {id: $id})
                MERGE (w)-[:LINKED_TO]->(o)
                """,
                {"address": _addr(osint.entity_ref), "chain": ch, "id": node_id},
                write=True,
            )

    @staticmethod
    async def upsert_threat_intel(
        hit: ThreatIntelHit,
        *,
        link_chain: Chain | None = None,
    ) -> None:
        """Persist a ThreatIntel node and link it to its wallet via address field."""
        import hashlib
        node_id = hashlib.sha256(f"{hit.address}:{hit.source}:{hit.threat_type}".encode()).hexdigest()[:32]
        now_iso = (hit.detected_at or datetime.now(timezone.utc)).isoformat()
        await run_query(
            """
            MERGE (t:ThreatIntel {id: $id})
            SET t.source = $source,
                t.address = $address,
                t.threat_type = $threat_type,
                t.description = $description,
                t.severity = $severity,
                t.url = $url,
                t.confirmed = $confirmed,
                t.detected_at = $detected_at
            """,
            {
                "id": node_id,
                "source": hit.source,
                "address": _addr(hit.address),
                "threat_type": hit.threat_type,
                "description": hit.description[:500],
                "severity": hit.severity,
                "url": hit.url,
                "confirmed": hit.confirmed,
                "detected_at": now_iso,
            },
            write=True,
        )
        # Auto-link to Wallet node via address — try all known chains if no chain given
        chain_values = [link_chain.value] if link_chain else ["ETH", "BASE", "POLYGON", "BNB", "ARB", "BTC", "TRON", "SOL"]
        for ch in chain_values:
            await run_query(
                """
                OPTIONAL MATCH (w:Wallet {address: $address, chain: $chain})
                WITH w WHERE w IS NOT NULL
                MATCH (t:ThreatIntel {id: $id})
                MERGE (w)-[:MENTIONED_IN]->(t)
                """,
                {"address": _addr(hit.address), "chain": ch, "id": node_id},
                write=True,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Traversal (Trace Engine queries)
    # ─────────────────────────────────────────────────────────────────────────
    @staticmethod
    async def trace_forward(
        address: str, chain: Chain, *, max_hops: int = 3, limit: int = 200,
    ) -> list[dict[str, Any]]:
        hops = max(1, min(int(max_hops), 5))
        cypher = (
            f"MATCH path=(start:Wallet {{address: $addr, chain: $chain}})"
            f"-[:SENT_TO*1..{hops}]->(target:Wallet) "
            "WITH target, length(path) AS hops "
            "RETURN target.address AS address, target.chain AS chain, "
            "       target.risk_score AS risk_score, "
            "       target.entity_label AS entity, "
            "       target.is_sanctioned AS sanctioned, "
            "       hops "
            "ORDER BY hops ASC, risk_score DESC "
            "LIMIT $limit"
        )
        return await run_query(
            cypher, {"addr": _addr(address), "chain": chain.value, "limit": limit}
        )

    @staticmethod
    async def trace_backward(
        address: str, chain: Chain, *, max_hops: int = 3, limit: int = 200,
    ) -> list[dict[str, Any]]:
        hops = max(1, min(int(max_hops), 5))
        cypher = (
            f"MATCH path=(source:Wallet)-[:SENT_TO*1..{hops}]->"
            f"(target:Wallet {{address: $addr, chain: $chain}}) "
            "WITH source, length(path) AS hops "
            "RETURN source.address AS address, source.chain AS chain, "
            "       source.risk_score AS risk_score, "
            "       source.entity_label AS entity, "
            "       source.is_sanctioned AS sanctioned, "
            "       hops "
            "ORDER BY hops ASC, risk_score DESC "
            "LIMIT $limit"
        )
        return await run_query(
            cypher, {"addr": _addr(address), "chain": chain.value, "limit": limit}
        )

    @staticmethod
    async def get_subgraph(
        address: str, chain: Chain, *, max_hops: int = 2, limit_edges: int = 500,
    ) -> dict[str, Any]:
        """Return the full multi-layer subgraph around an address.

        Includes: Wallet nodes, Entity nodes, BridgeEvent nodes,
                  AnomalyPattern nodes, OsintNode nodes, ThreatIntel nodes,
                  ChainNetwork nodes + all edge types.

        Output shape (D3-compatible):
          {
            "nodes": [...],   # each has {id, label, type, ...props}
            "edges": [...],   # each has {source, target, type, ...props}
          }
        """
        hops = max(1, min(int(max_hops), 4))
        
        # Detect OSINT-only entity (not a wallet address)
        is_osint = not address.startswith("0x") and len(address) != 40

        # 1. Wallet nodes in radius
        wallet_nodes = await run_query(
            f"""
            MATCH (center:Wallet {{address: $addr, chain: $chain}})
            OPTIONAL MATCH (center)-[:SENT_TO*1..{hops}]-(w:Wallet)
            WITH collect(distinct center) + collect(distinct w) AS all_wallets
            UNWIND all_wallets AS wallet
            RETURN DISTINCT
                wallet.address AS id,
                'Wallet' AS node_type,
                wallet.address AS address,
                wallet.chain AS chain,
                wallet.risk_score AS risk_score,
                wallet.entity_label AS entity_label,
                wallet.is_sanctioned AS is_sanctioned,
                wallet.gnn_label AS gnn_label,
                wallet.tx_count AS tx_count,
                wallet.balance_usd AS balance_usd,
                wallet.is_contract AS is_contract
            LIMIT $limit
            """,
            {"addr": _addr(address), "chain": chain.value, "limit": limit_edges},
        )

        # 2. SENT_TO edges
        sent_to_edges = await run_query(
            f"""
            MATCH (center:Wallet {{address: $addr, chain: $chain}})
            MATCH (center)-[r:SENT_TO*1..{hops}]-()
            UNWIND r AS rel
            RETURN DISTINCT
                'SENT_TO' AS edge_type,
                startNode(rel).address AS source,
                endNode(rel).address AS target,
                rel.tx_hash AS tx_hash,
                rel.value_usd AS value_usd,
                rel.value_native AS value_native,
                rel.timestamp AS timestamp
            LIMIT $limit
            """,
            {"addr": _addr(address), "chain": chain.value, "limit": limit_edges},
        )

        # 3. Entity nodes + LABELED_AS edges
        entity_data = await run_query(
            f"""
            MATCH (center:Wallet {{address: $addr, chain: $chain}})
            OPTIONAL MATCH (center)-[:SENT_TO*0..{hops}]-(w:Wallet)-[:LABELED_AS]->(e:Entity)
            WHERE e IS NOT NULL
            RETURN DISTINCT
                e.name AS id,
                'Entity' AS node_type,
                e.name AS name,
                e.type AS entity_type,
                e.risk_level AS risk_level,
                e.source AS source,
                w.address AS linked_wallet
            LIMIT 100
            """,
            {"addr": _addr(address), "chain": chain.value},
        )

        # 4. BridgeEvent nodes + BRIDGE_OUT/IN edges
        bridge_data = await run_query(
            f"""
            MATCH (center:Wallet {{address: $addr, chain: $chain}})
            OPTIONAL MATCH (center)-[:SENT_TO*0..{hops}]-(w:Wallet)-[:BRIDGE_OUT]->(b:BridgeEvent)
            WHERE b IS NOT NULL
            RETURN DISTINCT
                b.id AS id,
                'BridgeEvent' AS node_type,
                b.protocol AS protocol,
                b.source_chain AS source_chain,
                b.dest_chain AS dest_chain,
                b.value_usd AS value_usd,
                b.timestamp AS timestamp,
                b.status AS status,
                w.address AS source_wallet
            LIMIT 50
            """,
            {"addr": _addr(address), "chain": chain.value},
        )

        # 5. BRIDGE_TO edges (direct cross-chain wallet→wallet)
        bridge_edges = await run_query(
            f"""
            MATCH (center:Wallet {{address: $addr, chain: $chain}})
            OPTIONAL MATCH (center)-[:SENT_TO*0..{hops}]-(w:Wallet)-[br:BRIDGE_TO]->(dw:Wallet)
            WHERE br IS NOT NULL
            RETURN DISTINCT
                'BRIDGE_TO' AS edge_type,
                w.address AS source,
                dw.address AS target,
                br.protocol AS protocol,
                br.source_chain AS source_chain,
                br.dest_chain AS dest_chain,
                br.value_usd AS value_usd,
                br.timestamp AS timestamp,
                br.bridge_id AS bridge_id
            LIMIT 50
            """,
            {"addr": _addr(address), "chain": chain.value},
        )

        # 6. AnomalyPattern nodes + FLAGGED_BY edges
        anomaly_data = await run_query(
            f"""
            MATCH (center:Wallet {{address: $addr, chain: $chain}})
            OPTIONAL MATCH (center)-[:SENT_TO*0..{hops}]-(w:Wallet)-[:FLAGGED_BY]->(a:AnomalyPattern)
            WHERE a IS NOT NULL
            RETURN DISTINCT
                a.id AS id,
                'AnomalyPattern' AS node_type,
                a.code AS code,
                a.case_id AS case_id,
                a.severity AS severity,
                a.description AS description,
                w.address AS flagged_wallet
            LIMIT 100
            """,
            {"addr": _addr(address), "chain": chain.value},
        )

        # 7. OsintNode nodes + LINKED_TO edges
        osint_data = await run_query(
            f"""
            MATCH (center:Wallet {{address: $addr, chain: $chain}})
            OPTIONAL MATCH (center)-[:SENT_TO*0..{hops}]-(w:Wallet)-[:LINKED_TO]->(o:OsintNode)
            WHERE o IS NOT NULL
            RETURN DISTINCT
                o.id AS id,
                'OsintNode' AS node_type,
                o.source AS source,
                o.entity_ref AS entity_ref,
                o.url AS url,
                o.snippet AS snippet,
                o.platform AS platform,
                o.retrieved_at AS retrieved_at,
                w.address AS linked_wallet
            LIMIT 50
            """,
            {"addr": _addr(address), "chain": chain.value},
        )

        # 8. ThreatIntel nodes + MENTIONED_IN edges
        threat_data = await run_query(
            f"""
            MATCH (center:Wallet {{address: $addr, chain: $chain}})
            OPTIONAL MATCH (center)-[:SENT_TO*0..{hops}]-(w:Wallet)-[:MENTIONED_IN]->(t:ThreatIntel)
            WHERE t IS NOT NULL
            RETURN DISTINCT
                t.id AS id,
                'ThreatIntel' AS node_type,
                t.source AS source,
                t.threat_type AS threat_type,
                t.description AS description,
                t.severity AS severity,
                t.url AS url,
                t.confirmed AS confirmed,
                w.address AS linked_wallet
            LIMIT 50
            """,
            {"addr": _addr(address), "chain": chain.value},
        )

        # 9. ChainNetwork nodes
        chain_data = await run_query(
            f"""
            MATCH (center:Wallet {{address: $addr, chain: $chain}})
            OPTIONAL MATCH (center)-[:SENT_TO*0..{hops}]-(w:Wallet)-[:ON_CHAIN]->(c:ChainNetwork)
            WHERE c IS NOT NULL
            RETURN DISTINCT
                c.name AS id,
                'ChainNetwork' AS node_type,
                c.name AS name,
                c.full_name AS full_name,
                c.type AS chain_type,
                c.color AS color
            LIMIT 20
            """,
            {"addr": _addr(address), "chain": chain.value},
        )

        # ── Assemble final graph payload ──
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        # Mark focal node (lowercase-normalized)
        focal = _addr(address)

        for n in wallet_nodes:
            nodes.append({**dict(n), "is_focal": n.get("id") == focal})

        for n in entity_data:
            nodes.append(dict(n))
            if n.get("linked_wallet"):
                edges.append({
                    "source": n["linked_wallet"],
                    "target": n["id"],
                    "edge_type": "LABELED_AS",
                })

        for n in bridge_data:
            nodes.append(dict(n))
            if n.get("source_wallet"):
                edges.append({
                    "source": n["source_wallet"],
                    "target": n["id"],
                    "edge_type": "BRIDGE_OUT",
                    "protocol": n.get("protocol"),
                    "value_usd": n.get("value_usd"),
                })

        for n in anomaly_data:
            nodes.append(dict(n))
            if n.get("flagged_wallet"):
                edges.append({
                    "source": n["flagged_wallet"],
                    "target": n["id"],
                    "edge_type": "FLAGGED_BY",
                    "severity": n.get("severity"),
                    "code": n.get("code"),
                })

        for n in osint_data:
            nodes.append(dict(n))
            if n.get("linked_wallet"):
                edges.append({
                    "source": n["linked_wallet"],
                    "target": n["id"],
                    "edge_type": "LINKED_TO",
                })

        for n in threat_data:
            nodes.append(dict(n))
            if n.get("linked_wallet"):
                edges.append({
                    "source": n["linked_wallet"],
                    "target": n["id"],
                    "edge_type": "MENTIONED_IN",
                    "severity": n.get("severity"),
                })

        for n in chain_data:
            nodes.append(dict(n))

        for e in sent_to_edges:
            edges.append({**dict(e)})

        for e in bridge_edges:
            edges.append({**dict(e)})

        # For OSINT-only entities, add Entity node and query OsintNodes directly
        if is_osint:
            # Add focal Entity node
            nodes.append({
                "id": address,
                "node_type": "Entity",
                "name": address,
                "entity_type": "osint_entity",
                "risk_level": None,
                "source": "case_input",
            })
            # Query OsintNodes directly by entity_ref
            osint_direct = await run_query(
                """
                MATCH (o:OsintNode {entity_ref: $entity_ref})
                RETURN DISTINCT
                    o.id AS id,
                    'OsintNode' AS node_type,
                    o.source AS source,
                    o.entity_ref AS entity_ref,
                    o.url AS url,
                    o.snippet AS snippet,
                    o.platform AS platform,
                    o.retrieved_at AS retrieved_at,
                    $entity_ref AS linked_wallet
                LIMIT 100
                """,
                {"entity_ref": address},
            )
            for o in osint_direct:
                o["is_focal"] = False
                nodes.append(o)
            
            # Add edges from Entity to OsintNodes
            for o in osint_direct:
                edges.append({
                    "source": address,
                    "target": o["id"],
                    "edge_type": "LINKED_TO",
                })

        # Deduplicate nodes by id
        seen_ids: set[str] = set()
        unique_nodes = []
        for n in nodes:
            nid = str(n.get("id", ""))
            if nid and nid not in seen_ids:
                seen_ids.add(nid)
                unique_nodes.append(n)

        return {"nodes": unique_nodes, "edges": edges}

    @staticmethod
    async def fan_out_count(
        address: str, chain: Chain, *, window_minutes: int = 60,
    ) -> int:
        cutoff = datetime.now(timezone.utc).timestamp() - window_minutes * 60
        cypher = (
            "MATCH (w:Wallet {address: $addr, chain: $chain})-[r:SENT_TO]->(o:Wallet) "
            "WHERE datetime(r.timestamp) >= datetime($cutoff_iso) "
            "RETURN count(DISTINCT o) AS n"
        )
        rows = await run_query(cypher, {
            "addr": address, "chain": chain.value,
            "cutoff_iso": datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat(),
        })
        return int(rows[0]["n"]) if rows else 0

    @staticmethod
    async def neighbors_with_label(
        address: str, chain: Chain, label: str, *, hops: int = 1,
    ) -> list[dict[str, Any]]:
        h = max(1, min(int(hops), 4))
        cypher = (
            f"MATCH (w:Wallet {{address: $addr, chain: $chain}})"
            f"-[:SENT_TO*1..{h}]-(n:Wallet) "
            "WHERE n.entity_label IS NOT NULL AND "
            "      toLower(n.entity_label) CONTAINS toLower($label) "
            "RETURN DISTINCT n.address AS address, n.chain AS chain, "
            "       n.entity_label AS entity, n.is_sanctioned AS sanctioned"
        )
        return await run_query(cypher, {"addr": address, "chain": chain.value, "label": label})
