"""Security primitives: password hashing, JWT, API key hashing."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings
from app.core.exceptions import UnauthorizedError


# ── Passwords ──
# Use bcrypt directly (passlib has compatibility issues with bcrypt >= 4.x).
# bcrypt has a 72-byte limit on input — pre-hash longer passwords with SHA-256
# (industry-standard pattern, e.g. used by Dropbox).
_BCRYPT_MAX = 72


def _prepare_password(plain: str) -> bytes:
    raw = plain.encode("utf-8")
    if len(raw) > _BCRYPT_MAX:
        raw = hashlib.sha256(raw).digest()  # 32 bytes, well within limit
    return raw


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_prepare_password(plain), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare_password(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ── API keys ──
# Strategy: generate a random token, store the SHA-256 hash. On request, hash
# incoming token and compare. (bcrypt is too slow for per-request API key checks.)
def generate_api_key(prefix: str = "thx") -> tuple[str, str]:
    """Return (raw_key, sha256_hex). Persist only the hash."""
    raw = f"{prefix}_{secrets.token_urlsafe(32)}"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return raw, digest


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def verify_api_key(raw: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_api_key(raw), stored_hash)


# ── JWT ──
def create_access_token(
    subject: str,
    *,
    extra: dict[str, Any] | None = None,
    expires_minutes: int | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=expires_minutes or settings.jwt_access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "type": "access",
        **(extra or {}),
    }
    return jwt.encode(
        payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token(subject: str) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.jwt_refresh_token_expire_days)
    payload = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "type": "refresh",
    }
    return jwt.encode(
        payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError as e:
        raise UnauthorizedError("Token expired") from e
    except jwt.InvalidTokenError as e:
        raise UnauthorizedError("Invalid token") from e
