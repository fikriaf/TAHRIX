"""Inbound webhook endpoints (Helius, Alchemy, Telegram bot)."""

from __future__ import annotations

import hashlib
import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, UnauthorizedError
from app.core.logging import get_logger
from app.db.postgres import get_db
from app.services.telegram_link import consume_link_token

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = get_logger(__name__)


def _verify_helius_sig(body: bytes, signature: str | None) -> bool:
    secret = settings.helius_webhook_secret
    if not secret:
        # No secret configured → reject (fail closed)
        return False
    if not signature:
        return False
    expected = hmac.new(
        secret.get_secret_value().encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/helius", status_code=status.HTTP_202_ACCEPTED)
async def helius_webhook(
    request: Request,
    x_signature: Annotated[str | None, Header(alias="X-Helius-Signature")] = None,
) -> dict[str, Any]:
    raw = await request.body()

    # Helius supports HMAC verification when an authHeader is set on the webhook;
    # if you used `Authorization` instead of HMAC, swap to a header-token check.
    if settings.helius_webhook_secret and not _verify_helius_sig(raw, x_signature):
        raise UnauthorizedError("Invalid Helius signature")

    payload = await request.json()
    logger.info("webhook.helius", count=len(payload) if isinstance(payload, list) else 1)

    # Dispatch to ingestion task (Phase 1+)
    from app.workers.tasks import ingest_helius_webhook
    ingest_helius_webhook.delay(payload)
    return {"accepted": True}


@router.post("/alchemy", status_code=status.HTTP_202_ACCEPTED)
async def alchemy_webhook(request: Request) -> dict[str, Any]:
    payload = await request.json()
    logger.info("webhook.alchemy", type=payload.get("type"))

    from app.workers.tasks import ingest_alchemy_webhook
    ingest_alchemy_webhook.delay(payload)
    return {"accepted": True}


# ─────────────────────────────────────────────────────────────────────────────
# Telegram bot updates webhook
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/telegram", status_code=status.HTTP_200_OK)
async def telegram_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_telegram_secret: Annotated[
        str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")
    ] = None,
) -> dict[str, Any]:
    """Receive Telegram bot updates.

    Configure this URL via setWebhook with `secret_token` set to
    `TELEGRAM_WEBHOOK_SECRET`. Telegram echoes that value in the
    `X-Telegram-Bot-Api-Secret-Token` header on every call.

    Currently handles: `/start <token>` to bind a user's chat to TAHRIX.
    """
    if settings.telegram_webhook_secret:
        expected = settings.telegram_webhook_secret.get_secret_value()
        if not x_telegram_secret or not hmac.compare_digest(x_telegram_secret, expected):
            raise UnauthorizedError("Invalid Telegram webhook secret")

    update = await request.json()
    message = update.get("message") or update.get("edited_message") or {}
    text: str = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    from_user = message.get("from") or {}
    chat_id = chat.get("id")

    # Only act on /start <token>
    if text.startswith("/start") and chat_id is not None:
        parts = text.split(maxsplit=1)
        if len(parts) == 2 and parts[1]:
            token = parts[1].strip()
            try:
                sub = await consume_link_token(
                    db,
                    token=token,
                    chat_id=str(chat_id),
                    telegram_user_id=str(from_user.get("id") or "") or None,
                    telegram_username=from_user.get("username"),
                )
            except BadRequestError as e:
                await _reply(chat_id, f"❌ {e.message}")
                return {"ok": True}
            except Exception:  # noqa: BLE001
                logger.exception("telegram.webhook.link.error")
                await _reply(chat_id, "❌ Internal error linking your account.")
                return {"ok": True}

            await _reply(
                chat_id,
                "✅ <b>Telegram linked to TAHRIX</b>\n"
                f"User ID: <code>{sub.user_id}</code>\n"
                "You will now receive investigation alerts here.",
            )
            return {"ok": True}

        # Plain /start without token
        await _reply(
            chat_id,
            "👋 <b>TAHRIX Alerts Bot</b>\n"
            "To receive alerts, open the deep link from your TAHRIX dashboard "
            "(Settings → Telegram → Link).",
        )
        return {"ok": True}

    return {"ok": True}


async def _reply(chat_id: int | str, text: str) -> None:
    """Best-effort reply via Telegram Bot API."""
    if not settings.telegram_bot_token:
        return
    from app.adapters.telegram import TelegramAdapter

    try:
        async with TelegramAdapter() as tg:
            await tg.send_message(text, chat_id=chat_id)
    except Exception:  # noqa: BLE001
        logger.exception("telegram.reply.failed", chat_id=chat_id)
