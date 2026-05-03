from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


async def _dispose_loop_resources() -> None:
    """Close async resources bound to the current event loop."""
    from app.db.postgres import dispose_engine
    from app.db.neo4j import close_driver
    from app.db.redis import close_redis

    for fn, name in (
        (close_driver, "neo4j"),
        (close_redis, "redis"),
        (dispose_engine, "postgres"),
    ):
        try:
            await fn()
        except Exception:  # noqa: BLE001
            logger.exception("task.cleanup", resource=name)


def _run_async(coro):
    """Run an async coroutine in a fresh event loop, then dispose loop-bound resources."""
    async def _wrapped():
        try:
            return await coro
        finally:
            await _dispose_loop_resources()

    return asyncio.run(_wrapped())


@celery_app.task(name="tahrix.run_investigation", bind=True, max_retries=2)
def run_investigation(self, case_id: str) -> dict[str, Any]:
    from app.services.investigation_runner import run_case  # local import: avoid cycles

    logger.info("task.investigation.start", case_id=case_id, task_id=self.request.id)
    try:
        return _run_async(run_case(uuid.UUID(case_id)))
    except Exception as e:  # noqa: BLE001
        logger.exception("task.investigation.error", case_id=case_id, error=str(e))
        # On SoftTimeLimitExceeded or any fatal error: mark case failed before retry
        try:
            from app.services.investigation_runner import _fail_case_sync
            _fail_case_sync(uuid.UUID(case_id), f"task timeout or error: {type(e).__name__}")
        except Exception:  # noqa: BLE001
            pass
        raise self.retry(exc=e, countdown=10)


@celery_app.task(name="tahrix.ingest_helius_webhook")
def ingest_helius_webhook(payload: Any) -> int:
    from app.services.ingestion import ingest_helius_events
    return _run_async(ingest_helius_events(payload))


@celery_app.task(name="tahrix.ingest_alchemy_webhook")
def ingest_alchemy_webhook(payload: Any) -> int:
    from app.services.ingestion import ingest_alchemy_events
    return _run_async(ingest_alchemy_events(payload))
