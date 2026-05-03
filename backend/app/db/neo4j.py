"""Neo4j async driver wrapper. Per-event-loop driver instance.

The Neo4j async driver binds to the asyncio loop at creation time. To support
Celery workers (which spawn a new loop per task), we lazily create one driver
per loop and dispose at the end of each task.

All Cypher queries are parameterized — never f-string interpolate user data.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_drivers: dict[int, AsyncDriver] = {}


def _current_loop_id() -> int:
    try:
        return id(asyncio.get_running_loop())
    except RuntimeError:
        return 0


def _make_driver() -> AsyncDriver:
    return AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password.get_secret_value()),
        max_connection_pool_size=50,
        connection_acquisition_timeout=60,
    )


def get_driver() -> AsyncDriver:
    loop_id = _current_loop_id()
    drv = _drivers.get(loop_id)
    if drv is None:
        drv = _make_driver()
        _drivers[loop_id] = drv
    return drv


@asynccontextmanager
async def neo4j_session() -> AsyncIterator[AsyncSession]:
    async with get_driver().session(database=settings.neo4j_database) as session:
        yield session


async def run_query(
    cypher: str,
    parameters: dict[str, Any] | None = None,
    *,
    write: bool = False,
) -> list[dict[str, Any]]:
    """Execute a parameterized Cypher query and return list of records as dicts."""

    async def _tx(tx) -> list[dict[str, Any]]:
        result = await tx.run(cypher, parameters or {})
        records = await result.data()
        return records

    async with neo4j_session() as session:
        if write:
            return await session.execute_write(_tx)
        return await session.execute_read(_tx)


async def verify_connectivity() -> None:
    await get_driver().verify_connectivity()
    logger.info("neo4j.connected", uri=settings.neo4j_uri)


async def close_driver() -> None:
    """Close driver for the current loop."""
    loop_id = _current_loop_id()
    drv = _drivers.pop(loop_id, None)
    if drv is not None:
        await drv.close()


async def close_all_drivers() -> None:
    for loop_id, drv in list(_drivers.items()):
        try:
            await drv.close()
        except Exception:  # noqa: BLE001
            pass
        _drivers.pop(loop_id, None)
