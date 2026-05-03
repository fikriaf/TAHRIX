"""Investigation Runner — orchestrates the full lifecycle of a single case.

End-to-end flow (per MVP §7):
  1. Load case from Postgres, mark as IN_PROGRESS, init seed wallet in Neo4j.
  2. Run the Agent Orchestrator (Cognitive Loop).
  3. Aggregate evidence: GNN, anomalies, sanctions → Risk Scorer.
  4. Post-run graph enrichment: persist anomaly flags, entity labels, OSINT nodes → Neo4j.
  5. Generate PDF report; pin to IPFS; persist CID.
  6. Send Telegram alert if risk ≥ HIGH.
  7. Mark COMPLETED (or FAILED on exceptions).

This function is invoked from a Celery worker. All heavy IO is async.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from neo4j.exceptions import TransientError as Neo4jTransientError

from app.agent.orchestrator import AgentOrchestrator
from app.core.config import settings
from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger
from app.db.postgres import session_scope
from app.db.redis import publish_event
from app.models.domain import GnnPrediction, OsintNode, SanctionResult, ThreatIntelHit, WalletNode
from app.models.enums import CaseStatus, Chain, RiskGrade
from app.models.sql import CaseEvent, InvestigationCase
from app.repositories.graph_repository import GraphRepository
from app.services.gnn_service import GnnService, GnnUnavailableError
from app.services.risk_scorer import compute_risk

logger = get_logger(__name__)


async def run_case(case_id: uuid.UUID) -> dict[str, Any]:
    logger.info("investigation.start", case_id=str(case_id))

    # 1. Load case
    async with session_scope() as db:
        case = await db.get(InvestigationCase, case_id)
        if not case:
            raise ValueError(f"Case {case_id} not found")
        case.status = CaseStatus.IN_PROGRESS
        case.started_at = datetime.now(timezone.utc)
        chain = Chain(case.input_chain)
        address = case.input_address
        depth = case.depth
        iterations = case.iterations or 5
        case_number = case.case_number
        analyst_id = case.analyst_id
        # Detect OSINT-only (non-wallet entity)
        is_osint_only = address.startswith("[OSINT]") or (
            not address.startswith("0x") and 
            not address.startswith("sol:") and
            len(address) < 40
        )

    # Publish status update: IN_PROGRESS
    await publish_event(str(case_id), {
        "type": "status",
        "phase": "IN_PROGRESS",
        "case_id": str(case_id),
        "case_number": case_number,
        "address": address,
        "chain": chain.value,
    })

    # 2. Seed Neo4j — skip for OSINT-only entities
    if not is_osint_only:
        for _attempt in range(4):
            try:
                await GraphRepository.upsert_wallet(WalletNode(
                    address=address, chain=chain,
                    first_seen=datetime.now(timezone.utc),
                    last_seen=datetime.now(timezone.utc),
                ))
                break
            except Neo4jTransientError as exc:
                if _attempt >= 3:
                    return await _fail_case(case_id, f"neo4j deadlock: {exc}")
                wait = 2 ** _attempt
                logger.warning("investigation.neo4j.retry", attempt=_attempt + 1,
                               case_id=str(case_id), wait=wait)
                await asyncio.sleep(wait)
    else:
        logger.info("investigation.osint_only", case_id=str(case_id), address=address)

    # 3. Build per-step event publisher
    async def _on_event(event: dict[str, Any]) -> None:
        """Called by orchestrator after EVERY step — publishes to Redis + persists to DB."""
        event = {**event, "case_id": str(case_id), "case_number": case_number}
        await publish_event(str(case_id), event)
        # Persist ALL phases live so the /events polling endpoint always has data
        phase = event.get("phase", "")
        if phase in ("ACT", "THINK", "REFLECT") and event.get("type") not in ("status", "done"):
            await _persist_single_event(case_id, event)

    # 4. Run agent with live callback
    try:
        agent = AgentOrchestrator(
            case_id=case_number, address=address, chain=chain, depth=depth,
            is_osint_only=is_osint_only,
        )
        agent_result = await agent.run(max_iterations=iterations, on_event=_on_event)
    except ConfigurationError as e:
        return await _fail_case(case_id, f"agent unavailable: {e.message}")
    except Exception as e:  # noqa: BLE001
        logger.exception("investigation.agent.error", case_id=str(case_id))
        return await _fail_case(case_id, f"agent error: {e}")

    # 5. No-op: all events already persisted live via _on_event callback above.
    # We only need to catch any that slipped through (e.g. START/DONE sentinels).
    await _persist_events(case_id, [
        ev for ev in agent_result["events"]
        if ev.get("type") in ("status", "done") and ev.get("phase") not in ("ACT", "THINK", "REFLECT")
    ])

    # 5.5. Ensure anomaly detection ran.
    if not agent.tool_ctx.anomaly_flags and agent.tool_ctx.transactions:
        from app.services.anomaly_detector import AnomalyContext, run_all
        actx = AnomalyContext(
            address=agent.tool_ctx.address,
            chain=agent.tool_ctx.chain.value,
            transactions=agent.tool_ctx.transactions,
            bridge_events=agent.tool_ctx.bridge_events,
        )
        agent.tool_ctx.anomaly_flags = run_all(actx)
        logger.info("investigation.anomaly.fallback",
                    case_id=str(case_id),
                    flag_count=len(agent.tool_ctx.anomaly_flags))

    # 6. Compute risk score — extract threat/OSINT signals from agent events
    sanctions: SanctionResult | None = _extract_sanctions(agent_result, address)
    if not sanctions:
        sanctions = _extract_sanctions_from_threats(agent_result, address)
    gnn: GnnPrediction | None = await _maybe_run_final_gnn(address, chain)
    threat_hits, max_threat_sev, osint_hits = _extract_threat_signal(agent_result)
    
    # LLM re-audit: check if final_text has JSON with score revision
    llm_score = _extract_llm_verified_score(agent_result)
    if llm_score is not None:
        logger.info("llm_score_audit", llm_score=llm_score, address=address)
    
    risk = compute_risk(
        address=address, chain=chain,
        gnn=gnn,
        anomaly_flags=agent.tool_ctx.anomaly_flags,
        sanctions=sanctions,
        centrality=0.0,
        threat_hits=threat_hits,
        max_threat_severity=max_threat_sev,
        osint_hits=osint_hits,
    )

    # 7. Post-run graph enrichment — wire everything into Neo4j multi-layer graph
    await _enrich_graph(
        case_id=case_id,
        address=address,
        chain=chain,
        agent_result=agent_result,
        anomaly_flags=agent.tool_ctx.anomaly_flags,
        sanctions=sanctions,
        risk_score=risk.score,
    )

    # 8. Update Wallet node with risk results
    await GraphRepository.upsert_wallet(WalletNode(
        address=address, chain=chain,
        risk_score=risk.score / 100.0,
        is_sanctioned=bool(sanctions and sanctions.sanctioned),
    ))

    # 9. Save case results
    async with session_scope() as db:
        case = await db.get(InvestigationCase, case_id)
        if not case:
            return await _fail_case(case_id, "case disappeared")
        case.status = CaseStatus.COMPLETED
        case.risk_score = risk.score
        case.risk_grade = risk.grade
        case.gnn_score = (gnn.score if gnn else None)
        case.anomaly_score = risk.components.get("anomaly")
        case.anomaly_codes = [f.code.value for f in agent.tool_ctx.anomaly_flags]
        case.sanctions_hit = bool(sanctions and sanctions.sanctioned)
        case.iterations = agent_result["iterations"]
        case.confidence = max((h["confidence"] for h in agent_result["hypotheses"]), default=0.0)
        case.summary = agent_result.get("final_text") or risk.explanation
        case.completed_at = datetime.now(timezone.utc)

    # Publish risk result to SSE channel
    await publish_event(str(case_id), {
        "type": "risk",
        "case_id": str(case_id),
        "case_number": case_number,
        "risk_score": risk.score,
        "risk_grade": risk.grade,
        "sanctions_hit": bool(sanctions and sanctions.sanctioned),
        "anomaly_codes": [f.code.value for f in agent.tool_ctx.anomaly_flags],
        "anomaly_flags": [
            {
                "code": f.code.value,
                "severity": f.severity,
                "description": f.description,
            }
            for f in agent.tool_ctx.anomaly_flags
        ],
        "gnn_score": gnn.score if gnn else None,
        "gnn_label": gnn.label.value if gnn else None,
        "components": risk.components,
        "summary": agent_result.get("final_text") or risk.explanation,
        "iterations": agent_result["iterations"],
        "transactions_collected": agent_result.get("transactions_collected", 0),
    })

    # 10. Generate report + pin (best-effort)
    # Enrich agent_result with graph topology for report
    try:
        graph_data = await GraphRepository.get_subgraph(address, chain, max_hops=2)
        if graph_data:
            nodes = graph_data.get("nodes", [])
            edges = graph_data.get("edges", [])
            # node_type_counts
            ntc: dict[str, int] = {}
            for n in nodes:
                nt = n.get("node_type") or n.get("type") or "Unknown"
                ntc[nt] = ntc.get(nt, 0) + 1
            agent_result["node_type_counts"] = ntc
            # top_counterparties (wallets with tx_count, excluding focal)
            focal_lower = address.lower()
            wallet_nodes = [n for n in nodes
                           if (n.get("node_type") or n.get("type")) == "Wallet"
                           and (n.get("address") or "").lower() != focal_lower]
            agent_result["top_counterparties"] = sorted(
                wallet_nodes, key=lambda n: n.get("tx_count") or 0, reverse=True
            )[:10]
            agent_result["graph_node_count"] = len(nodes)
            agent_result["graph_edge_count"] = len(edges)
    except Exception as e:
        logger.warning("investigation.report.graph_enrich.skip", reason=str(e))
        agent_result.setdefault("node_type_counts", {})
        agent_result.setdefault("top_counterparties", [])
        agent_result.setdefault("graph_node_count", 0)
        agent_result.setdefault("graph_edge_count", 0)

    try:
        ipfs_cid, sha256 = await _generate_and_pin_report(case_id, risk, agent_result)
        if ipfs_cid:
            async with session_scope() as db:
                case = await db.get(InvestigationCase, case_id)
                if case:
                    case.ipfs_cid = ipfs_cid
                    case.report_sha256 = sha256
            await publish_event(str(case_id), {
                "type": "ipfs",
                "case_id": str(case_id),
                "ipfs_cid": ipfs_cid,
            })
    except ConfigurationError as e:
        logger.warning("investigation.report.skip", reason=e.message)

    # 11. Telegram alert (best-effort)
    if RiskGrade(risk.grade) in (RiskGrade.HIGH, RiskGrade.CRITICAL):
        try:
            await _send_telegram_alert(case_number, address, chain, risk, analyst_id)
        except ConfigurationError as e:
            logger.warning("investigation.alert.skip", reason=e.message)

    logger.info("investigation.done", case_id=str(case_id),
                score=risk.score, grade=risk.grade)

    # Done sentinel
    await publish_event(str(case_id), {"type": "done", "case_id": str(case_id)})

    return {
        "case_id": str(case_id),
        "case_number": case_number,
        "risk_score": risk.score,
        "risk_grade": risk.grade,
        "iterations": agent_result["iterations"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Post-run graph enrichment
# ─────────────────────────────────────────────────────────────────────────────
async def _enrich_graph(
    *,
    case_id: uuid.UUID,
    address: str,
    chain: Chain,
    agent_result: dict[str, Any],
    anomaly_flags: list,
    sanctions: SanctionResult | None,
    risk_score: float,
) -> None:
    """Wire all collected evidence into the Neo4j multi-layer knowledge graph."""

    # 1. Persist anomaly flags as AnomalyPattern nodes
    if anomaly_flags:
        try:
            await GraphRepository.upsert_anomaly_flags(address, chain, str(case_id), anomaly_flags)
            logger.info("investigation.graph.anomaly_flags",
                        address=address[:12], count=len(anomaly_flags))
        except Exception as e:  # noqa: BLE001
            logger.warning("investigation.graph.anomaly_flags.failed", error=str(e))

    # 2. Wire entity labels (from get_entity_label tool calls) into Neo4j
    for ev in agent_result.get("events", []):
        if ev.get("tool") == "get_entity_label":
            result = ev.get("result") or {}
            label_data = result.get("label")
            if label_data and isinstance(label_data, dict):
                try:
                    entity_address = result.get("address", address)
                    entity_name = label_data.get("name") or label_data.get("label")
                    entity_type = label_data.get("type", "UNKNOWN")
                    if entity_name:
                        # Upsert the Entity node first (with type), then link
                        await GraphRepository.upsert_entity(
                            entity_name, entity_type,
                            source="etherscan",
                        )
                        await GraphRepository.link_wallet_to_entity(
                            wallet_address=entity_address,
                            chain=chain,
                            entity_name=entity_name,
                        )
                except Exception as e:  # noqa: BLE001
                    logger.warning("investigation.graph.entity.failed", error=str(e))

    # 3. Wire sanctions hit as ThreatIntelHit
    if sanctions and sanctions.sanctioned:
        try:
            hit = ThreatIntelHit(
                source="chainalysis_ofac",
                address=address,
                threat_type="SANCTIONED",
                severity=1.0,
                description=f"OFAC sanctioned address. Identifications: {sanctions.identifications}",
                url=None,
                confirmed=True,
                detected_at=datetime.now(timezone.utc),
            )
            await GraphRepository.upsert_threat_intel(hit)
        except Exception as e:  # noqa: BLE001
            logger.warning("investigation.graph.sanctions.failed", error=str(e))

    # 4. Wire OSINT results from web_search / social_media_intel tool calls
    for ev in agent_result.get("events", []):
        if ev.get("tool") in ("web_search", "social_media_intel"):
            result = ev.get("result") or {}
            results_list = result.get("results") or result.get("mentions") or []
            for r in results_list[:3]:
                url = r.get("url", "")
                if not url:
                    continue
                try:
                    node = OsintNode(
                        source=ev.get("tool", "web_search"),
                        entity_ref=address,
                        url=url,
                        snippet=(r.get("text") or r.get("abstract", ""))[:300],
                        platform=r.get("platform", "web"),
                        retrieved_at=datetime.now(timezone.utc),
                    )
                    await GraphRepository.upsert_osint_node(node)
                except Exception as e:  # noqa: BLE001
                    logger.warning("investigation.graph.osint.failed", error=str(e))

    # 5. Wire darkweb_monitor threats
    for ev in agent_result.get("events", []):
        if ev.get("tool") == "darkweb_monitor":
            result = ev.get("result") or {}
            threats = result.get("threats") or []
            for t in threats:
                try:
                    hit = ThreatIntelHit(
                        source=t.get("source", "darkweb_monitor"),
                        address=address,
                        threat_type=t.get("type", "unknown"),
                        severity=float(t.get("severity", 0.5)),
                        description=t.get("description", "")[:500],
                        url=t.get("url"),
                        confirmed=bool(t.get("confirmed", False)),
                        detected_at=datetime.now(timezone.utc),
                    )
                    await GraphRepository.upsert_threat_intel(hit)
                except Exception as e:  # noqa: BLE001
                    logger.warning("investigation.graph.threat.failed", error=str(e))

    logger.info("investigation.graph.enrichment_done", address=address[:12])


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _extract_sanctions(agent_result: dict, address: str) -> SanctionResult | None:
    for ev in agent_result.get("events", []):
        if ev.get("tool") == "check_sanctions":
            r = ev.get("result") or {}
            if isinstance(r, dict) and "sanctioned" in r:
                return SanctionResult(
                    address=address,
                    sanctioned=bool(r.get("sanctioned")),
                    identifications=r.get("identifications") or [],
                    source="chainalysis",
                    checked_at=datetime.now(timezone.utc),
                )
    return None


def _extract_sanctions_from_threats(
    agent_result: dict, address: str
) -> SanctionResult | None:
    """Extract sanctions from LLM final verdict (no keyword matching)."""
    # Check final LLM verdict for CRITICAL/HIGH risk with sanctions mention
    for ev in agent_result.get("events", []):
        if ev.get("phase") == "REFLECT" or ev.get("tool") is None:
            result = ev.get("result") or {}
            final = result.get("final") or ""
            if final:
                final_lower = final.lower()
                # Trust LLM final verdict - if it says CRITICAL with sanctions, mark as sanctioned
                if "critical" in final_lower and ("sanction" in final_lower or "ofac" in final_lower or "sdn" in final_lower):
                    return SanctionResult(
                        address=address,
                        sanctioned=True,
                        identifications=[{"verdict": "CRITICAL", "reason": "LLM confirmed sanctions in final analysis"}],
                        source="llm_final_verdict",
                        checked_at=datetime.now(timezone.utc),
                    )
    
    return None


def _extract_llm_verified_score(agent_result: dict) -> float | None:
    """Extract LLM's re-audited score from audit phase."""
    import re, json
    for ev in agent_result.get("events", []):
        result = ev.get("result") or {}
        audit = result.get("audit") or ""
        if not audit:
            continue
        try:
            json_match = re.search(r'\{[^{}]*\}', audit, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                score_valid = data.get("score_valid", True)
                score = data.get("risk_score")
                if not score_valid and score is not None:
                    logger.info("llm_score_revision", 
                               original_score=score,
                               reason=data.get("score_revision_reason", ""))
                    return float(score)
                verdict = (data.get("risk_verdict") or "").upper()
                if verdict == "CRITICAL":
                    return 90.0
        except Exception:
            pass
    return None


def _extract_threat_signal(agent_result: dict) -> tuple[int, float, int]:
    """Return (threat_hits, max_threat_severity, osint_hits) from agent events."""
    threat_hits = 0
    max_sev = 0.0
    osint_hits = 0
    for ev in agent_result.get("events", []):
        tool = ev.get("tool", "")
        r = ev.get("result") or {}
        if not isinstance(r, dict):
            continue
        if tool == "darkweb_monitor":
            threats = r.get("threats") or []
            threat_hits += len(threats)
            for t in threats:
                sev = float(t.get("severity", 0.0) or 0.0)
                if sev > max_sev:
                    max_sev = sev
            # Also count max_severity directly if threats list not expanded
            ms = float(r.get("max_severity", 0.0) or 0.0)
            if ms > max_sev:
                max_sev = ms
        if tool in ("web_search", "social_media_intel"):
            cnt = int(r.get("count", 0) or 0)
            osint_hits += cnt
    return threat_hits, max_sev, osint_hits


async def _maybe_run_final_gnn(address: str, chain: Chain) -> GnnPrediction | None:
    """Run a definitive GNN inference once the graph is fully populated."""
    svc = GnnService.instance()
    if not svc.available:
        return None
    sub = await GraphRepository.get_subgraph(address, chain, max_hops=2)
    if not sub.get("nodes"):
        return None
    try:
        return svc.predict(address, sub["nodes"], sub.get("edges", []))
    except GnnUnavailableError as e:
        logger.warning("investigation.gnn.unavailable", reason=e.message)
        return None
    except Exception as e:  # noqa: BLE001
        logger.exception("investigation.gnn.error", error=str(e))
        return None


async def _persist_single_event(case_id: uuid.UUID, event: dict[str, Any]) -> None:
    """Persist one event immediately to DB (called per-step during live run)."""
    try:
        async with session_scope() as db:
            db.add(CaseEvent(
                case_id=case_id,
                iteration=int(event.get("iteration") or 0),
                phase=str(event.get("phase") or "ACT"),
                tool=event.get("tool"),
                payload=event.get("payload"),
                result=event.get("result"),
                duration_ms=event.get("duration_ms"),
            ))
    except Exception:  # noqa: BLE001
        logger.warning("investigation.event.persist_failed", case_id=str(case_id))


async def _persist_events(case_id: uuid.UUID, events: list[dict[str, Any]]) -> None:
    if not events:
        return
    async with session_scope() as db:
        for ev in events:
            phase = str(ev.get("phase") or "ACT")
            if phase not in ("ACT", "REFLECT", "THINK"):
                continue
            db.add(CaseEvent(
                case_id=case_id,
                iteration=int(ev.get("iteration") or 0),
                phase=phase,
                tool=ev.get("tool"),
                payload=ev.get("payload"),
                result=ev.get("result"),
                duration_ms=ev.get("duration_ms"),
            ))


async def _fail_case(case_id: uuid.UUID, message: str) -> dict[str, Any]:
    async with session_scope() as db:
        case = await db.get(InvestigationCase, case_id)
        if case:
            case.status = CaseStatus.FAILED
            case.error_message = message
            case.completed_at = datetime.now(timezone.utc)
    await publish_event(str(case_id), {
        "type": "error",
        "case_id": str(case_id),
        "message": message,
    })
    await publish_event(str(case_id), {"type": "done", "case_id": str(case_id)})
    return {"case_id": str(case_id), "status": "failed", "error": message}


def _fail_case_sync(case_id: uuid.UUID, message: str) -> None:
    """Synchronous wrapper for _fail_case — for use from Celery task error handler."""
    import asyncio

    async def _run():
        async with session_scope() as db:
            case = await db.get(InvestigationCase, case_id)
            if case and case.status == CaseStatus.IN_PROGRESS:
                case.status = CaseStatus.FAILED
                case.error_message = message
                case.completed_at = datetime.now(timezone.utc)

    try:
        asyncio.run(_run())
    except Exception:  # noqa: BLE001
        pass


async def _generate_and_pin_report(
    case_id: uuid.UUID, risk, agent_result: dict[str, Any],
) -> tuple[str | None, str | None]:
    from app.services.report_generator import build_pdf_report
    from app.adapters.ipfs import IPFSAdapter

    pdf_bytes = build_pdf_report(case_id=str(case_id),
                                 risk=risk, agent_result=agent_result)
    sha = IPFSAdapter.sha256_hex(pdf_bytes)
    try:
        async with IPFSAdapter() as ipfs:
            cid = await ipfs.add_bytes(pdf_bytes,
                                       filename=f"tahrix_{case_id}.pdf",
                                       pin=True)
            return cid, sha
    except ConfigurationError:
        return None, sha


async def _send_telegram_alert(
    case_number: str, address: str, chain: Chain, risk, analyst_id: uuid.UUID | None,
) -> None:
    from app.adapters.telegram import TelegramAdapter
    from app.services.telegram_link import resolve_chat_id_for_user

    async with session_scope() as db:
        chat_id = await resolve_chat_id_for_user(db, analyst_id)
    if not chat_id:
        logger.info("investigation.alert.no_chat", case=case_number)
        return

    grade_emoji = {"critical": "🚨", "high": "⚠️", "medium": "🟡", "low": "✅"}
    text = (
        f"{grade_emoji.get(risk.grade, '🔍')} <b>{risk.grade.upper()} RISK ALERT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Case:</b> {case_number}\n"
        f"<b>Wallet:</b> <code>{address}</code>\n"
        f"<b>Chain:</b> {chain.value}\n"
        f"<b>Risk Score:</b> {risk.score:.1f}/100\n"
        f"<b>Anomalies:</b> {', '.join(f.code.value for f in risk.anomaly_flags) or '-'}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{risk.explanation or ''}"
    )
    async with TelegramAdapter() as tg:
        await tg.send_message(text, chat_id=chat_id)
