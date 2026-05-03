"""Health & readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.db.neo4j import run_query
from app.db.postgres import session_scope
from app.db.redis import ping as redis_ping
from app.models.schemas import HealthResponse
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    components: dict[str, str] = {}

    try:
        async with session_scope() as s:
            await s.execute(text("SELECT 1"))
        components["postgres"] = "ok"
    except Exception as e:  # noqa: BLE001
        components["postgres"] = f"error: {e.__class__.__name__}"

    try:
        await run_query("RETURN 1 AS ok")
        components["neo4j"] = "ok"
    except Exception as e:  # noqa: BLE001
        components["neo4j"] = f"error: {e.__class__.__name__}"

    try:
        ok = await redis_ping()
        components["redis"] = "ok" if ok else "down"
    except Exception as e:  # noqa: BLE001
        components["redis"] = f"error: {e.__class__.__name__}"

    overall = "ok" if all(v == "ok" for v in components.values()) else "degraded"
    return HealthResponse(status=overall, version=__version__, components=components)


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "alive"}
