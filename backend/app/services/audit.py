"""Audit log service — writes tamper-evident action records to PostgreSQL.

Every security-relevant action (login, register, case create, case delete,
API key create/revoke, Telegram link/unlink) is recorded here. The table is
append-only — no delete/update path is exposed to the application layer.

Usage (non-blocking fire-and-forget in endpoints):
    import asyncio
    asyncio.ensure_future(
        audit(db, actor_id=user.id, action="case.create", resource_type="case",
              resource_id=str(case.id), ip=request.client.host)
    )
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.sql import AuditLog

logger = get_logger(__name__)


async def audit(
    db: AsyncSession,
    *,
    action: str,
    actor_id: uuid.UUID | str | None = None,
    actor_type: str = "user",
    resource_type: str | None = None,
    resource_id: str | None = None,
    ip: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Write one audit log entry. Never raises — log failures are swallowed so
    they cannot break the primary request path."""
    try:
        entry = AuditLog(
            actor_id=uuid.UUID(str(actor_id)) if actor_id else None,
            actor_type=actor_type,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            ip_address=ip,
            metadata_json=metadata,
        )
        db.add(entry)
        await db.flush()   # write to DB within the current transaction
        logger.debug("audit.written", action=action, actor_id=str(actor_id))
    except Exception:  # noqa: BLE001
        logger.exception("audit.write.failed", action=action)
