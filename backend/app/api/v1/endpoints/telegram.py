"""User-facing Telegram subscription endpoints (Model B).

GET    /me/telegram          → current subscription status
POST   /me/telegram/link     → issue deep link `https://t.me/<bot>?start=<token>`
DELETE /me/telegram          → unlink chat
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.db.postgres import get_db
from app.models.schemas import TelegramLinkOut, TelegramSubscriptionOut
from app.models.sql import User
from app.services.telegram_link import (
    get_subscription,
    issue_link_token,
    unlink,
)

router = APIRouter(prefix="/me/telegram", tags=["telegram"])


@router.get("", response_model=TelegramSubscriptionOut | None)
async def my_telegram(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> TelegramSubscriptionOut | None:
    sub = await get_subscription(db, user.id)
    if not sub:
        return None
    return TelegramSubscriptionOut.model_validate(sub)


@router.post("/link", response_model=TelegramLinkOut, status_code=status.HTTP_201_CREATED)
async def link_telegram(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> TelegramLinkOut:
    payload = await issue_link_token(db, user.id)
    return TelegramLinkOut.model_validate(payload)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_telegram(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    await unlink(db, user.id)
