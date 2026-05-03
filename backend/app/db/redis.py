"""Async Redis client. Used as cache, agent short-term memory, rate-limit store,
and real-time event pub/sub for SSE streaming.

Like the other DB clients, the Redis connection pool is bound to its event loop
at creation time. We lazily create one client per loop and close at end of task.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import redis.asyncio as redis_async

from app.core.config import settings

_clients: dict[int, redis_async.Redis] = {}


def _current_loop_id() -> int:
    try:
        return id(asyncio.get_running_loop())
    except RuntimeError:
        return 0


def _make_client() -> redis_async.Redis:
    return redis_async.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        health_check_interval=30,
    )


def get_redis() -> redis_async.Redis:
    loop_id = _current_loop_id()
    cli = _clients.get(loop_id)
    if cli is None:
        cli = _make_client()
        _clients[loop_id] = cli
    return cli


async def cache_get_json(key: str) -> Any | None:
    raw = await get_redis().get(key)
    return json.loads(raw) if raw else None


async def cache_set_json(key: str, value: Any, ttl_seconds: int) -> None:
    await get_redis().set(key, json.dumps(value, default=str), ex=ttl_seconds)


async def cache_delete(key: str) -> None:
    await get_redis().delete(key)


async def ping() -> bool:
    return bool(await get_redis().ping())


async def close_redis() -> None:
    """Close client for current loop."""
    loop_id = _current_loop_id()
    cli = _clients.pop(loop_id, None)
    if cli is not None:
        await cli.aclose()


async def close_all_redis() -> None:
    for loop_id, cli in list(_clients.items()):
        try:
            await cli.aclose()
        except Exception:  # noqa: BLE001
            pass
        _clients.pop(loop_id, None)


# ── Pub/Sub for SSE streaming ─────────────────────────────────────────────────

def case_channel(case_id: str) -> str:
    """Redis channel name for a specific case's live events."""
    return f"tahrix:case:{case_id}:events"


async def publish_event(case_id: str, event: dict[str, Any]) -> None:
    """Publish a case event to its Redis channel. Called from Celery worker."""
    channel = case_channel(case_id)
    payload = json.dumps(event, default=str)
    await get_redis().publish(channel, payload)


async def subscribe_events(case_id: str) -> AsyncIterator[dict[str, Any]]:
    """Subscribe to a case's event channel. Yields parsed event dicts.

    Creates a dedicated pubsub connection (separate from the shared pool)
    and yields messages until the channel receives a sentinel
    ``{"type": "done"}`` message or the caller closes the generator.
    """
    # Create a fresh client for pubsub (cannot reuse command client)
    pubsub_client = _make_client()
    pubsub = pubsub_client.pubsub()
    channel = case_channel(case_id)
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                data = json.loads(message["data"])
            except (json.JSONDecodeError, TypeError):
                continue
            yield data
            # Sentinel: runner sends {"type":"done"} when investigation ends
            if data.get("type") == "done":
                break
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        await pubsub_client.aclose()

