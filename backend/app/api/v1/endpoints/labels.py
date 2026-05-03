"""labels.py — Address label submission with LLM audit.

POST /labels          → submit a label (tags + chronology + PoC file)
GET  /labels          → list labels (filter by address/chain)
GET  /labels/{id}     → single label detail
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.db.postgres import get_db
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.schemas import AddressLabelCreate, AddressLabelOut
from app.models.sql import AddressLabel, User
from app.services.audit import audit

logger = get_logger(__name__)

router = APIRouter(prefix="/labels", tags=["labels"])


# ─────────────────────────────────────────────────────────────────────────────
# LLM audit helper
# ─────────────────────────────────────────────────────────────────────────────
async def _llm_audit_label(
    address: str,
    chain: str,
    tags: list[str],
    chronology: str | None,
    poc_filename: str | None,
    poc_content: str | None,
) -> dict:
    """Ask the LLM to audit analyst-submitted label intelligence.

    Returns dict: {verdict, confidence, summary, flags}
    """
    from app.agent.llm import get_llm

    # Build context for the LLM
    tag_str = ", ".join(tags) if tags else "none"
    poc_block = ""
    if poc_content:
        snippet = poc_content[:1500]
        poc_block = f"\n\nPROOF-OF-CONCEPT FILE ({poc_filename or 'unnamed'}):\n{snippet}"

    chron_trunc = (chronology or "")[:1000]
    chron_block = f"\n\nCHRONOLOGY:\n{chron_trunc}" if chron_trunc else ""

    prompt = f"""You are a blockchain forensics auditor reviewing an analyst-submitted label.

SUBMISSION:
- Address: {address} (Chain: {chain})
- Analyst tags: {tag_str}{chron_block}{poc_block}

Evaluate the evidence. Respond ONLY with this JSON (no markdown, no extra text):
{{"verdict":"CONFIRMED"|"DISPUTED"|"INCONCLUSIVE","confidence":<0.0-1.0>,"summary":"<2-3 sentences>","flags":["<concern>"]}}"""

    llm = get_llm()
    try:
        resp = await llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1000,
        )
        raw = (resp.content or "").strip()
        # Try to extract JSON object from anywhere in the response
        import re
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if json_match:
            raw = json_match.group(0)
        data = json.loads(raw)
        return {
            "verdict": str(data.get("verdict", "INCONCLUSIVE")).upper()[:32],
            "confidence": float(min(max(data.get("confidence", 0.5), 0.0), 1.0)),
            "summary": str(data.get("summary", ""))[:2000],
            "flags": [str(f) for f in (data.get("flags") or [])[:20]],
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("label_audit_failed", error=str(exc))
        return {
            "verdict": "INCONCLUSIVE",
            "confidence": 0.0,
            "summary": f"LLM audit failed: {exc}",
            "flags": ["audit_error"],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────
@router.post("", response_model=AddressLabelOut, status_code=201,
             summary="Submit address label with LLM audit")
async def submit_label(
    body: AddressLabelCreate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> AddressLabel:
    """Submit analyst intelligence label for an address.

    - **address** – blockchain address being labelled
    - **chain** – chain identifier (ETH, BTC, SOL, …)
    - **tags** – list of category tags (mixer, scam, defi, exchange, …)
    - **chronology** – free-text incident timeline / PoC narrative
    - **poc_filename** / **poc_content** / **poc_mimetype** – optional evidence file
    - **case_id** – optional associated investigation case

    After storing the submission the LLM audits the evidence and writes its
    verdict (CONFIRMED / DISPUTED / INCONCLUSIVE) back to the same row.
    """
    # ── 1. Persist label (unaudited first so we have an ID)
    label = AddressLabel(
        id=uuid.uuid4(),
        address=body.address.strip(),
        chain=body.chain.upper(),
        tags=body.tags or [],
        chronology=body.chronology,
        poc_filename=body.poc_filename,
        poc_content=body.poc_content,
        poc_mimetype=body.poc_mimetype,
        submitted_by=user.id,
        case_id=body.case_id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(label)
    await db.flush()  # get id without committing

    # ── 2. LLM audit (async, same request — usually <5s)
    audit_result = await _llm_audit_label(
        address=label.address,
        chain=label.chain,
        tags=label.tags or [],
        chronology=label.chronology,
        poc_filename=label.poc_filename,
        poc_content=label.poc_content,
    )

    label.audit_verdict = audit_result["verdict"]
    label.audit_confidence = audit_result["confidence"]
    label.audit_summary = audit_result["summary"]
    label.audit_flags = audit_result["flags"]
    label.audited_at = datetime.now(timezone.utc)
    label.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(label)

    # ── 3. Audit log
    await audit(
        db, action="label.submit", actor_id=user.id,
        resource_type="address_label", resource_id=str(label.id),
        ip=request.client.host if request.client else None,
        metadata={
            "address": label.address,
            "chain": label.chain,
            "tags": label.tags,
            "verdict": label.audit_verdict,
            "confidence": label.audit_confidence,
        },
    )

    return label


@router.get("", response_model=list[AddressLabelOut],
            summary="List address labels")
async def list_labels(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    address: str | None = Query(default=None, description="Filter by address (exact)"),
    chain: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[AddressLabel]:
    """List submitted labels, optionally filtered by address / chain."""
    q = select(AddressLabel).order_by(AddressLabel.created_at.desc())
    if address:
        q = q.where(AddressLabel.address == address.strip())
    if chain:
        q = q.where(AddressLabel.chain == chain.upper())
    q = q.offset(offset).limit(limit)
    rows = await db.scalars(q)
    return list(rows.all())


@router.get("/{label_id}", response_model=AddressLabelOut,
            summary="Get single address label")
async def get_label(
    label_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> AddressLabel:
    label = await db.get(AddressLabel, label_id)
    if not label:
        raise NotFoundError("Label not found")
    return label
