"""FastAPI dependencies: auth (JWT/API key), DB session injection, RBAC."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_token, hash_api_key
from app.db.postgres import get_db
from app.models.enums import UserRole
from app.models.sql import APIKey, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    token: Annotated[str | None, Depends(oauth2_scheme)] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> User:
    """Resolve user via either Bearer JWT or X-API-Key header."""
    # 1) API Key first (preferred for programmatic access)
    if x_api_key:
        digest = hash_api_key(x_api_key)
        stmt = select(APIKey).where(APIKey.key_hash == digest, APIKey.revoked_at.is_(None))
        api_key = (await db.execute(stmt)).scalar_one_or_none()
        if not api_key:
            raise UnauthorizedError("Invalid API key")
        user = await db.get(User, api_key.owner_id)
        if not user or not user.is_active:
            raise UnauthorizedError("Owner inactive")
        request.state.api_key_id = str(api_key.id)
        request.state.tier = api_key.tier
        return user

    # 2) JWT
    if token:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise UnauthorizedError("Wrong token type")
        user = await db.get(User, payload["sub"])
        if not user or not user.is_active:
            raise UnauthorizedError("User inactive")
        return user

    raise UnauthorizedError("Authentication required")


def require_role(*allowed: UserRole):
    async def _checker(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in allowed:
            raise ForbiddenError(f"Requires role: {', '.join(r.value for r in allowed)}")
        return user

    return _checker
