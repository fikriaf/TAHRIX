"""Auth endpoints: register, login, refresh, API key management."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, require_role
from app.core.exceptions import BadRequestError, UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_api_key,
    hash_password,
    verify_password,
)
from app.db.postgres import get_db
from app.models.enums import UserRole
from app.models.schemas import (
    APIKeyCreate,
    APIKeyCreateOut,
    APIKeyOut,
    LoginRequest,
    TokenPair,
    UserCreate,
    UserOut,
    WalletLoginRequest,
)
from app.models.sql import APIKey, User
from app.services.audit import audit

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    request: Request,
    body: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserOut:
    existing = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if existing:
        raise BadRequestError("Email already registered")
    user = User(
        email=body.email,
        full_name=body.full_name,
        hashed_password=hash_password(body.password),
        role=UserRole.ANALYST,
    )
    db.add(user)
    await db.flush()
    await audit(db, action="auth.register", actor_id=user.id,
                resource_type="user", resource_id=str(user.id),
                ip=request.client.host if request.client else None,
                metadata={"email": body.email})
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenPair)
async def login(
    request: Request,
    body: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenPair:
    user = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_password):
        # Record failed attempt (no actor_id)
        await audit(db, action="auth.login.failed", actor_type="anonymous",
                    ip=request.client.host if request.client else None,
                    metadata={"email": body.email})
        await db.commit()
        raise UnauthorizedError("Invalid credentials")
    if not user.is_active:
        raise UnauthorizedError("User inactive")
    await audit(db, action="auth.login", actor_id=user.id,
                resource_type="user", resource_id=str(user.id),
                ip=request.client.host if request.client else None)
    await db.commit()
    role_value = user.role.value if hasattr(user.role, "value") else str(user.role)
    return TokenPair(
        access_token=create_access_token(str(user.id), extra={"role": role_value}),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/wallet-login", response_model=TokenPair)
async def wallet_login(
    request: Request,
    body: WalletLoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenPair:
    """Login with wallet signature - verify message signed by wallet address."""
    from eth_account import Account
    from eth_account.messages import encode_defunct
    
    try:
        encoded_msg = encode_defunct(text=body.message)
        recovered = Account.recover_message(encoded_msg, signature=body.signature)
    except Exception as e:
        raise UnauthorizedError(f"Invalid signature: {str(e)[:80]}")
    
    if recovered.lower() != body.address.lower():
        raise UnauthorizedError("Signature does not match address")
    
    user = (await db.execute(select(User).where(User.wallet_address == body.address.lower()))).scalar_one_or_none()
    
    if not user:
        user = User(
            email=f"wallet_{body.address.lower()[:16]}@tahrix.io",
            full_name=f"Wallet User ({body.address[:6]}...{body.address[-4:]})",
            hashed_password=hash_password(str(uuid.uuid4())),
            wallet_address=body.address.lower(),
            role=UserRole.ANALYST,
        )
        db.add(user)
        await db.flush()
        await audit(db, action="auth.wallet.register", actor_id=user.id,
                    ip=request.client.host if request.client else None,
                    metadata={"wallet": body.address})
    
    if not user.is_active:
        raise UnauthorizedError("User inactive")
    
    await audit(db, action="auth.wallet_login", actor_id=user.id,
                ip=request.client.host if request.client else None,
                metadata={"wallet": body.address})
    await db.commit()
    
    role_value = user.role.value if hasattr(user.role, "value") else str(user.role)
    return TokenPair(
        access_token=create_access_token(str(user.id), extra={"role": role_value}),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(refresh_token: str) -> TokenPair:
    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise UnauthorizedError("Wrong token type")
    return TokenPair(
        access_token=create_access_token(payload["sub"]),
        refresh_token=create_refresh_token(payload["sub"]),
    )


@router.get("/me", response_model=UserOut)
async def me(user: Annotated[User, Depends(get_current_user)]) -> UserOut:
    return UserOut.model_validate(user)


# ── API key management ──
@router.post("/api-keys", response_model=APIKeyCreateOut, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    request: Request,
    body: APIKeyCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> APIKeyCreateOut:
    raw, digest = generate_api_key()
    record = APIKey(
        id=uuid.uuid4(),
        owner_id=user.id,
        name=body.name,
        key_hash=digest,
        key_prefix=raw[:12],
        tier=body.tier,
    )
    db.add(record)
    await db.flush()
    await audit(db, action="apikey.create", actor_id=user.id,
                resource_type="api_key", resource_id=str(record.id),
                ip=request.client.host if request.client else None,
                metadata={"name": body.name, "tier": body.tier})
    await db.commit()
    await db.refresh(record)
    out = APIKeyCreateOut.model_validate(record).model_copy(update={"raw_key": raw})
    return out


@router.get("/api-keys", response_model=list[APIKeyOut])
async def list_api_keys(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[APIKeyOut]:
    rows = (await db.execute(select(APIKey).where(APIKey.owner_id == user.id))).scalars().all()
    return [APIKeyOut.model_validate(r) for r in rows]


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    request: Request,
    key_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    record = await db.get(APIKey, key_id)
    if not record or record.owner_id != user.id:
        raise BadRequestError("API key not found")
    record.revoked_at = datetime.now(timezone.utc)
    await audit(db, action="apikey.revoke", actor_id=user.id,
                resource_type="api_key", resource_id=str(key_id),
                ip=request.client.host if request.client else None)
    await db.commit()


# Admin-only example
@router.get("/admin/users", response_model=list[UserOut])
async def list_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_role(UserRole.ADMIN))],
) -> list[UserOut]:
    rows = (await db.execute(select(User))).scalars().all()
    return [UserOut.model_validate(r) for r in rows]
