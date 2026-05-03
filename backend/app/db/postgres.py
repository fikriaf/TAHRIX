"""Async PostgreSQL session management via SQLAlchemy 2.0.

Engine is created lazily and bound to the current asyncio event loop. This
avoids "Future attached to a different loop" errors when the same module is
imported in environments that create multiple event loops (notably Celery
workers, where each task may run `asyncio.run(...)` on a fresh loop).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """Base class for all ORM models."""


_engines: dict[int, AsyncEngine] = {}
_factories: dict[int, "async_sessionmaker[AsyncSession]"] = {}


def _make_engine() -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        echo=settings.app_debug,
        future=True,
    )


def _current_loop_id() -> int:
    try:
        return id(asyncio.get_running_loop())
    except RuntimeError:
        return 0  # no running loop


def get_engine() -> AsyncEngine:
    loop_id = _current_loop_id()
    eng = _engines.get(loop_id)
    if eng is None:
        eng = _make_engine()
        _engines[loop_id] = eng
        _factories[loop_id] = async_sessionmaker(
            eng, class_=AsyncSession, expire_on_commit=False, autoflush=False,
        )
    return eng


def _factory() -> "async_sessionmaker[AsyncSession]":
    get_engine()  # ensures factory exists for current loop
    return _factories[_current_loop_id()]


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Context manager: commit on success, rollback on exception."""
    async with _factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with _factory()() as session:
        try:
            yield session
        finally:
            await session.close()


async def dispose_engine() -> None:
    """Dispose the engine for the current loop and forget it."""
    loop_id = _current_loop_id()
    eng = _engines.pop(loop_id, None)
    _factories.pop(loop_id, None)
    if eng is not None:
        await eng.dispose()


async def dispose_all_engines() -> None:
    """Dispose ALL engines (across all loops). Use only at shutdown."""
    for loop_id, eng in list(_engines.items()):
        try:
            await eng.dispose()
        except Exception:  # noqa: BLE001
            pass
        _engines.pop(loop_id, None)
        _factories.pop(loop_id, None)


if TYPE_CHECKING:
    pass
