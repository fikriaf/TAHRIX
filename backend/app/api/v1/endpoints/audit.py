"""Audit log endpoint — append-only, admin-only read access."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.db.postgres import get_db
from app.models.enums import UserRole
from app.models.sql import AuditLog, User

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", summary="List audit log entries (own entries; admin sees all)")
async def list_audit_log(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    action: str | None = Query(None, description="Filter by action prefix, e.g. 'case.'"),
    resource_type: str | None = Query(None),
    actor_id: str | None = Query(None),
) -> dict[str, Any]:
    stmt = select(AuditLog).order_by(AuditLog.timestamp.desc())

    # Non-admins can only see their own log entries
    if current_user.role != UserRole.ADMIN:
        stmt = stmt.where(AuditLog.actor_id == current_user.id)
    elif actor_id:
        stmt = stmt.where(AuditLog.actor_id.cast(str) == actor_id)

    if action:
        stmt = stmt.where(AuditLog.action.startswith(action))
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [
            {
                "id": row.id,
                "timestamp": row.timestamp.isoformat(),
                "actor_id": str(row.actor_id) if row.actor_id else None,
                "actor_type": row.actor_type,
                "action": row.action,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "ip_address": row.ip_address,
                "metadata": row.metadata_json,
            }
            for row in rows
        ],
    }
