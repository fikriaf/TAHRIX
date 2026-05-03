"""Telegram link service — generate per-user link tokens and bind chat IDs.

Flow (Model B — per-user subscription):
1. User calls `POST /me/telegram/link` → backend returns deep link
   `https://t.me/<bot_username>?start=<token>`.
2. User opens link → Telegram sends `/start <token>` to the bot.
3. Bot webhook (`POST /webhooks/telegram`) consumes the update, validates
   the token, and creates / updates a `TelegramSubscription`.
4. Future investigation alerts targeting that user's case are dispatched to
   their `chat_id` (with fallback to `TELEGRAM_DEFAULT_CHAT_ID`).
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, ConfigurationError
from app.core.logging import get_logger
from app.models.sql import TelegramLinkToken, TelegramSubscription

logger = get_logger(__name__)

LINK_TOKEN_TTL_MINUTES = 15


async def issue_link_token(db: AsyncSession, user_id: uuid.UUID) -> dict[str, str]:
    """Generate a one-time token + Telegram deep link for the given user."""
    if not settings.telegram_bot_token:
        raise ConfigurationError("TELEGRAM_BOT_TOKEN missing — bot is disabled")
    if not settings.telegram_bot_username:
        raise ConfigurationError(
            "TELEGRAM_BOT_USERNAME missing — set it in .env to enable deep links"
        )

    token = secrets.token_urlsafe(24)  # 32 chars URL-safe
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=LINK_TOKEN_TTL_MINUTES)
    db.add(TelegramLinkToken(token=token, user_id=user_id, expires_at=expires_at))
    await db.commit()

    deep_link = f"https://t.me/{settings.telegram_bot_username}?start={token}"
    return {
        "token": token,
        "deep_link": deep_link,
        "expires_at": expires_at.isoformat(),
        "ttl_minutes": str(LINK_TOKEN_TTL_MINUTES),
    }


async def consume_link_token(
    db: AsyncSession,
    token: str,
    chat_id: str,
    *,
    telegram_user_id: str | None = None,
    telegram_username: str | None = None,
) -> TelegramSubscription:
    """Validate `/start <token>` and bind chat_id to the owning user."""
    record = await db.get(TelegramLinkToken, token)
    if not record:
        raise BadRequestError("Invalid or unknown link token")
    if record.used_at is not None:
        raise BadRequestError("Link token already used")
    if record.expires_at < datetime.now(timezone.utc):
        raise BadRequestError("Link token expired")

    # Upsert subscription
    existing = (
        await db.execute(
            select(TelegramSubscription).where(TelegramSubscription.user_id == record.user_id)
        )
    ).scalar_one_or_none()

    if existing:
        existing.chat_id = chat_id
        existing.telegram_user_id = telegram_user_id
        existing.telegram_username = telegram_username
        existing.is_active = True
        existing.linked_at = datetime.now(timezone.utc)
        sub = existing
    else:
        sub = TelegramSubscription(
            user_id=record.user_id,
            chat_id=chat_id,
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            is_active=True,
        )
        db.add(sub)

    record.used_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(sub)
    logger.info("telegram.link.success", user_id=str(record.user_id), chat_id=chat_id)
    return sub


async def get_subscription(
    db: AsyncSession, user_id: uuid.UUID
) -> TelegramSubscription | None:
    return (
        await db.execute(
            select(TelegramSubscription).where(TelegramSubscription.user_id == user_id)
        )
    ).scalar_one_or_none()


async def unlink(db: AsyncSession, user_id: uuid.UUID) -> bool:
    sub = await get_subscription(db, user_id)
    if not sub:
        return False
    await db.delete(sub)
    await db.commit()
    return True


async def resolve_chat_id_for_user(
    db: AsyncSession, user_id: uuid.UUID | None
) -> str | None:
    """Returns the user's Telegram chat_id, falling back to default if unset."""
    if user_id is not None:
        sub = await get_subscription(db, user_id)
        if sub and sub.is_active:
            return sub.chat_id
    return settings.telegram_default_chat_id
