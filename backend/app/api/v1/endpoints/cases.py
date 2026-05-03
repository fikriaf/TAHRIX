"""Investigation case endpoints."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Annotated, Any, AsyncIterator

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.address import Chain as ChainConst
from app.core.address import detect_chain, normalize_address
from app.core.exceptions import BadRequestError, NotFoundError
from app.db.postgres import get_db
from app.db.redis import subscribe_events
from app.models.enums import CaseStatus, Chain
from app.models.schemas import (
    CaseEventOut,
    CaseGraphOut,
    InvestigationCaseOut,
    InvestigationStartRequest,
    ReportRequest,
)
from app.models.sql import CaseEvent, InvestigationCase, User
from app.services.audit import audit

router = APIRouter(prefix="/cases", tags=["cases"])


def _new_case_number() -> str:
    return "TX-" + uuid.uuid4().hex[:10].upper()


@router.post("", response_model=InvestigationCaseOut, status_code=status.HTTP_202_ACCEPTED)
async def start_investigation(
    request: Request,
    body: InvestigationStartRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> InvestigationCaseOut:
    # Detect chain if not provided, with fallback for OSINT-only
    if body.chain:
        chain_name = body.chain.value
    else:
        try:
            chain_name = detect_chain(body.address)
        except Exception:
            chain_name = None  # Will be set below for OSINT
    
    # Try to normalize as wallet address, fallback to OSINT-only label
    try:
        norm = normalize_address(body.address, chain_name if chain_name and chain_name in ChainConst.ALL else None)
        is_osint_only = False
    except Exception:
        # Not a valid wallet - treat as OSINT entity name
        norm = body.address.strip()
        is_osint_only = True
        if not chain_name:
            chain_name = "OSINT"  # More accurate for OSINT-only entities

    case = InvestigationCase(
        case_number=_new_case_number(),
        input_address=norm,
        input_chain=chain_name,
        depth=body.depth,
        iterations=body.iterations,
        status=CaseStatus.PENDING,
        analyst_id=user.id,
        summary=f"[OSINT] {body.address}" if is_osint_only else None,
    )
    db.add(case)
    await db.flush()
    await audit(db, action="case.create", actor_id=user.id,
                resource_type="case", resource_id=str(case.id),
                ip=request.client.host if request.client else None,
                metadata={"address": norm, "chain": chain_name, "depth": body.depth})
    await db.commit()
    await db.refresh(case)

    from app.workers.tasks import run_investigation
    run_investigation.delay(str(case.id))

    return InvestigationCaseOut.model_validate(case)


@router.get("/{case_id}", response_model=InvestigationCaseOut)
async def get_case(
    case_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> InvestigationCaseOut:
    case = await db.get(InvestigationCase, case_id)
    if not case:
        raise NotFoundError("Case not found")
    return InvestigationCaseOut.model_validate(case)


@router.get("", response_model=list[InvestigationCaseOut])
async def list_cases(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    limit: int = 50,
    offset: int = 0,
) -> list[InvestigationCaseOut]:
    stmt = (
        select(InvestigationCase)
        .where(InvestigationCase.analyst_id == user.id)
        .order_by(InvestigationCase.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [InvestigationCaseOut.model_validate(r) for r in rows]


@router.get("/{case_id}/events", response_model=list[CaseEventOut])
async def get_case_events(
    case_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    since_id: int = Query(0, ge=0, description="Return events with id > since_id (for polling)"),
) -> list[CaseEventOut]:
    case = await db.get(InvestigationCase, case_id)
    if not case:
        raise NotFoundError("Case not found")
    stmt = (
        select(CaseEvent)
        .where(CaseEvent.case_id == case_id, CaseEvent.id > since_id)
        .order_by(CaseEvent.id.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [CaseEventOut.model_validate(r) for r in rows]


@router.get("/{case_id}/stream", summary="SSE live stream of agent events")
async def stream_case_events(
    case_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    request: Request,
) -> StreamingResponse:
    """Server-Sent Events stream for a running investigation.

    Clients connect with EventSource and receive one JSON event per message.
    The stream closes automatically when the investigation completes (type=done)
    or after 10 minutes timeout.

    Event shapes:
      {type: "status",  phase: "IN_PROGRESS"|"START"|..., case_id, address, chain}
      {type: "think",   phase: "THINK",   iteration, confidence}
      {type: "act",     phase: "ACT",     iteration, tool, payload}
      {type: "observe", phase: "ACT",     iteration, tool, result, duration_ms, confidence}
      {type: "reflect", phase: "REFLECT", iteration, result: {final, usage}}
      {type: "risk",    risk_score, risk_grade, anomaly_codes, gnn_score, components, ...}
      {type: "ipfs",    ipfs_cid}
      {type: "done",    case_id}
      {type: "error",   message}
    """
    case = await db.get(InvestigationCase, case_id)
    if not case:
        raise NotFoundError("Case not found")

    async def _event_generator() -> AsyncIterator[str]:
        # If case is already done, replay DB events then close
        if case.status == CaseStatus.COMPLETED:
            stmt = select(CaseEvent).where(
                CaseEvent.case_id == case_id
            ).order_by(CaseEvent.id.asc())
            rows = (await db.execute(stmt)).scalars().all()
            for row in rows:
                ev = CaseEventOut.model_validate(row).model_dump(mode="json")
                yield f"data: {json.dumps(ev, default=str)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'case_id': str(case_id)})}\n\n"
            return

        # Live stream: subscribe to Redis channel
        timeout = 600  # 10 min max
        deadline = asyncio.get_event_loop().time() + timeout
        try:
            async for event in subscribe_events(str(case_id)):
                if await request.is_disconnected():
                    break
                yield f"data: {json.dumps(event, default=str)}\n\n"
                if event.get("type") == "done":
                    break
                if asyncio.get_event_loop().time() > deadline:
                    yield f"data: {json.dumps({'type': 'timeout'})}\n\n"
                    break
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/{case_id}/graph", response_model=CaseGraphOut,
            summary="Transaction graph nodes and edges for D3 visualization")
async def get_case_graph(
    case_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    hops: int = Query(2, ge=1, le=4, description="Graph traversal depth"),
    limit: int = Query(300, ge=1, le=1000, description="Max edges to return"),
) -> CaseGraphOut:
    """Return the transaction graph for D3 force-directed visualization.

    Nodes: address, chain, risk_score, entity, sanctioned, gnn_label, is_focal.
    Edges: source, target, tx_hash, value_usd, value_native, timestamp.
    """
    case = await db.get(InvestigationCase, case_id)
    if not case:
        raise NotFoundError("Case not found")

    from app.models.enums import Chain as ChainEnum
    from app.repositories.graph_repository import GraphRepository

    chain = ChainEnum(case.input_chain)
    subgraph = await GraphRepository.get_subgraph(
        case.input_address, chain, max_hops=hops, limit_edges=limit
    )

    edges = []
    for e in subgraph.get("edges", []):
        edges.append({
            "source": e.get("from") or e.get("source"),
            "target": e.get("to") or e.get("target"),
            "tx_hash": e.get("tx_hash"),
            "value_usd": e.get("value_usd"),
            "value_native": e.get("value_native"),
            "timestamp": e.get("timestamp"),
        })

    # Detect OSINT-only case (input is not a wallet address)
    is_osint_case = not case.input_address.startswith("0x") and not (
        case.input_address.startswith("sol:") or len(case.input_address) == 44
    )
    
    nodes = []
    for n in subgraph.get("nodes", []):
        is_focal = n.get("address") == case.input_address
        node_data = {**n, "is_focal": is_focal}
        # Override node type for focal node in OSINT cases
        if is_focal and is_osint_case:
            node_data["node_type"] = "Entity"
            node_data["type"] = "Entity"
        nodes.append(node_data)

    return CaseGraphOut(
        case_id=case_id,
        address=case.input_address,
        chain=case.input_chain,
        nodes=nodes,
        edges=edges,
        node_count=len(nodes),
        edge_count=len(edges),
    )


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete case and all associated data (UU PDP compliance)")
async def delete_case(
    request: Request,
    case_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    case = await db.get(InvestigationCase, case_id)
    if not case:
        raise NotFoundError("Case not found")
    if case.analyst_id != user.id:
        raise BadRequestError("You are not the owner of this case")

    ipfs_cid = case.ipfs_cid
    if ipfs_cid:
        try:
            from app.adapters.ipfs import IPFSAdapter
            async with IPFSAdapter() as ipfs:
                await ipfs.unpin(ipfs_cid)
        except Exception:  # noqa: BLE001
            pass

    await audit(db, action="case.delete", actor_id=user.id,
                resource_type="case", resource_id=str(case_id),
                ip=request.client.host if request.client else None,
                metadata={
                    "case_number": case.case_number,
                    "address": case.input_address,
                    "ipfs_cid": ipfs_cid,
                    "status": case.status.value if hasattr(case.status, "value") else case.status,
                })

    await db.delete(case)
    await db.commit()


@router.post("/{case_id}/report", summary="Download forensic report (PDF / Markdown / DOCX)")
async def download_report(
    case_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    format: str = Query(default="pdf", regex="^(pdf|md|docx)$"),
    body: ReportRequest = None,
) -> StreamingResponse:
    if body is None:
        body = ReportRequest()
    graph_svg: str | None = body.graph_svg  # SVG string from frontend canvas (unused now — table replaces)
    case = await db.get(InvestigationCase, case_id)
    if not case:
        raise NotFoundError("Case not found")
    if case.status != CaseStatus.COMPLETED:
        status_str = case.status.value if hasattr(case.status, 'value') else str(case.status)
        if status_str.upper() != "COMPLETED":
            raise BadRequestError(
                f"Report only available for completed cases (current: {status_str})"
            )

    from app.models.domain import AnomalyFlag, GnnPrediction, RiskAssessment
    from app.models.enums import AnomalyCode, GnnLabel
    from app.repositories.graph_repository import GraphRepository
    from sqlalchemy import select as sa_select

    # ── Fetch events to extract rich tool results ──────────────────────────
    events_rows = (await db.execute(
        sa_select(CaseEvent).where(CaseEvent.case_id == case_id).order_by(CaseEvent.id)
    )).scalars().all()

    # Distil key tool results from events
    tx_info: dict = {}
    gnn_event: dict = {}
    threats: list = []
    anomaly_flags_raw: list = []
    trace_fwd: dict = {}
    trace_bwd: dict = {}
    llm_usage: dict = {}

    for ev in events_rows:
        result = ev.result or {}
        tool = ev.tool or ""
        if not result:
            continue
        if tool == "get_eth_transactions" and not tx_info:
            tx_info = result
        elif tool == "run_gnn_inference" and not gnn_event:
            gnn_event = result
        elif tool == "darkweb_monitor":
            preview = result.get("preview")
            if isinstance(preview, str):
                import json as _json
                try:
                    preview = _json.loads(preview)
                except Exception:
                    preview = {}
            threats = (preview.get("threats") if isinstance(preview, dict) else []) or []
            if not threats:
                threats = result.get("threats", [])
        elif tool == "detect_anomaly":
            anomaly_flags_raw = result.get("flags", [])
        elif tool == "trace_forward" and not trace_fwd:
            trace_fwd = result
        elif tool == "trace_backward" and not trace_bwd:
            trace_bwd = result
        elif ev.phase == "REFLECT" and not ev.tool:
            llm_usage = result.get("usage", {})

    # ── Fetch graph topology ───────────────────────────────────────────────
    try:
        graph_data = await GraphRepository.get_subgraph(
            str(case.input_address), Chain(case.input_chain)
        )
    except Exception:
        graph_data = None

    graph_nodes = graph_data.get("nodes", []) if graph_data else []
    graph_edges = graph_data.get("edges", []) if graph_data else []
    # Count by node type
    node_type_counts: dict[str, int] = {}
    for n in graph_nodes:
        nt = n.get("node_type") or n.get("type") or "Unknown"
        node_type_counts[nt] = node_type_counts.get(nt, 0) + 1
    # Top counterparties (wallets with highest tx_count, excluding focal)
    focal_addr = case.input_address.lower()
    wallet_nodes = [n for n in graph_nodes
                    if (n.get("node_type") or n.get("type")) == "Wallet"
                    and (n.get("address") or "").lower() != focal_addr]
    top_counterparties = sorted(wallet_nodes, key=lambda n: n.get("tx_count") or 0, reverse=True)[:10]

    # ── Build AnomalyFlag objects with real severity + description ─────────
    anomaly_flags: list[AnomalyFlag] = []
    for code_str in (case.anomaly_codes or []):
        try:
            raw = next((f for f in anomaly_flags_raw if f.get("code") == code_str), {})
            anomaly_flags.append(AnomalyFlag(
                code=AnomalyCode(code_str),
                severity=raw.get("severity", 0.5),
                description=raw.get("description", f"Pattern {code_str} detected during investigation."),
            ))
        except ValueError:
            pass

    # ── GNN prediction with full top_features from event ──────────────────
    gnn: GnnPrediction | None = None
    if case.gnn_score is not None:
        p = float(case.gnn_score)
        gnn = GnnPrediction(
            address=case.input_address,
            score=p,
            label=GnnLabel.ILLICIT if p >= 0.55 else GnnLabel.LICIT,
            explanation=gnn_event.get("explanation") or f"GNN illicit-probability {p:.4f}.",
            shap_top_features=gnn_event.get("top_features") or [],
        )

    risk = RiskAssessment(
        address=case.input_address,
        chain=Chain(case.input_chain),
        score=float(case.risk_score or 0),
        grade=case.risk_grade or "low",
        components={
            "gnn": float(case.gnn_score or 0),
            "anomaly": float(case.anomaly_score or 0),
            "sanctions": 1.0 if case.sanctions_hit else 0.0,
            "centrality": 0.0,
            "w_gnn": 0.40, "w_anomaly": 0.30,
            "w_sanctions": 0.20, "w_centrality": 0.10,
        },
        anomaly_flags=anomaly_flags,
        gnn=gnn,
        explanation=case.summary,
    )

    # ── Duration calculation ───────────────────────────────────────────────
    import math
    duration_s: int | None = None
    if case.started_at and case.completed_at:
        delta = case.completed_at - case.started_at
        duration_s = int(delta.total_seconds())

    # Extract OSINT data from graph nodes for OSINT cases
    osint_sources = set()
    osint_details = []
    social_found = 0
    emails_found = 0
    subdomains_found = 0
    
    for n in graph_nodes:
        if n.get("type") == "OsintNode":
            src = n.get("source", "unknown")
            osint_sources.add(src)
            platform = n.get("platform", "")
            if platform in ["github", "twitter", "instagram", "linkedin", "medium"]:
                social_found += 1
            elif platform == "email":
                emails_found += 1
            elif platform == "subdomain":
                subdomains_found += 1
            osint_details.append({
                "source": src,
                "platform": platform,
                "findings": n.get("snippet", n.get("url", ""))[:200],
                "url": n.get("url", ""),
            })
    
    osint_sources = list(osint_sources) if osint_sources else ["sherlock", "theharvester", "web_search"]
    
    agent_result = {
        "iterations": case.iterations or 0,
        "confidence": case.confidence or 0.0,
        "final_text": case.summary or "",
        "transactions_collected": tx_info.get("count", 0),
        "first_seen": tx_info.get("first_seen"),
        "last_seen": tx_info.get("last_seen"),
        "bridge_events": [],
        "threats": threats[:20],
        "trace_fwd_count": trace_fwd.get("count", 0),
        "trace_bwd_count": trace_bwd.get("count", 0),
        "gnn_subgraph_size": gnn_event.get("subgraph_size", 0),
        "node_type_counts": node_type_counts,
        "top_counterparties": top_counterparties,
        "graph_node_count": len(graph_nodes),
        "graph_edge_count": len(graph_edges),
        "ipfs_cid": case.ipfs_cid,
        "depth": case.depth,
        "started_at": case.started_at.strftime("%Y-%m-%d %H:%M:%S UTC") if case.started_at else None,
        "completed_at": case.completed_at.strftime("%Y-%m-%d %H:%M:%S UTC") if case.completed_at else None,
        "duration_s": duration_s,
        "llm_usage": llm_usage,
        "analyst_id": str(case.analyst_id) if case.analyst_id else None,
        # OSINT fields
        "is_osint": case.input_chain == "OSINT",
        "osint_sources": osint_sources,
        "osint_details": osint_details[:10],
        "social_found": social_found,
        "emails_found": emails_found,
        "subdomains_found": subdomains_found,
        "osint_mentions": len([n for n in graph_nodes if n.get("type") == "OsintNode"]),
    }

    import asyncio
    from functools import partial
    from app.services.report_generator import build_pdf_report, build_markdown_report, build_docx_report

    loop = asyncio.get_running_loop()

    if format == "md":
        report_bytes: bytes = await loop.run_in_executor(
            None,
            partial(build_markdown_report, case_id=case.case_number, risk=risk,
                    agent_result=agent_result, graph_svg=graph_svg),
        )
        filename = f"{case.case_number}.md"
        media_type = "text/markdown"
    elif format == "docx":
        report_bytes = await loop.run_in_executor(
            None,
            partial(build_docx_report, case_id=case.case_number, risk=risk,
                    agent_result=agent_result, graph_svg=graph_svg),
        )
        filename = f"{case.case_number}.docx"
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        report_bytes = await loop.run_in_executor(
            None,
            partial(build_pdf_report, case_id=case.case_number, risk=risk,
                    agent_result=agent_result, graph_svg=graph_svg),
        )
        filename = f"{case.case_number}.pdf"
        media_type = "application/pdf"

    return StreamingResponse(
        iter([report_bytes]),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(report_bytes)),
        },
    )
