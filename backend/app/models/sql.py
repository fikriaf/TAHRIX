"""SQLAlchemy ORM models for Postgres (case management, users, audit)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres import Base
from app.models.enums import CaseStatus, RiskGrade, UserRole


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


# ── Users & API keys ──
class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(String(32), default=UserRole.ANALYST, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    api_keys: Mapped[list["APIKey"]] = relationship(back_populates="owner",
                                                    cascade="all, delete-orphan")
    cases: Mapped[list["InvestigationCase"]] = relationship(back_populates="analyst")


class APIKey(Base, TimestampMixin):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)  # first chars (display)
    tier: Mapped[str] = mapped_column(String(32), default="free", nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    owner: Mapped[User] = relationship(back_populates="api_keys")


# ── Investigations ──
class InvestigationCase(Base, TimestampMixin):
    __tablename__ = "investigation_cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)

    input_address: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    input_chain: Mapped[str] = mapped_column(String(16), nullable=False)
    depth: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    status: Mapped[CaseStatus] = mapped_column(
        String(24), default=CaseStatus.PENDING, nullable=False, index=True
    )
    risk_score: Mapped[float | None] = mapped_column(Float)
    risk_grade: Mapped[RiskGrade | None] = mapped_column(String(16))

    gnn_score: Mapped[float | None] = mapped_column(Float)
    anomaly_score: Mapped[float | None] = mapped_column(Float)
    anomaly_codes: Mapped[list | None] = mapped_column(JSON)
    sanctions_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)

    iterations: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)

    ipfs_cid: Mapped[str | None] = mapped_column(String(80))
    report_sha256: Mapped[str | None] = mapped_column(String(64))

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    analyst_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    analyst: Mapped[User | None] = relationship(back_populates="cases")
    events: Mapped[list["CaseEvent"]] = relationship(back_populates="case",
                                                     cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_cases_status_created", "status", "created_at"),
    )


class CaseEvent(Base):
    """Log of agentic loop events for forensic replay."""

    __tablename__ = "case_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("investigation_cases.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(16), nullable=False)  # THINK/ACT/OBSERVE/REFLECT
    tool: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict | None] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    case: Mapped[InvestigationCase] = relationship(back_populates="events")


# ── Audit log ──
class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_type: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(80))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON)


# ── Webhook subscriptions (Helius) ──
class WebhookSubscription(Base, TimestampMixin):
    __tablename__ = "webhook_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # helius, alchemy
    external_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    address: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    chain: Mapped[str] = mapped_column(String(16), nullable=False)
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("investigation_cases.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class TelegramSubscription(Base, TimestampMixin):
    """Per-user Telegram chat binding for receiving alerts.

    Each user can link their personal Telegram chat to their TAHRIX account.
    Alerts will be delivered to `chat_id` for cases owned by `user_id`.
    """

    __tablename__ = "telegram_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    chat_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    telegram_user_id: Mapped[str | None] = mapped_column(String(64))
    telegram_username: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class TelegramLinkToken(Base):
    """Short-lived token user includes in `/start <token>` to link their chat."""

    __tablename__ = "telegram_link_tokens"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


# ── Address Labels (community intelligence) ──
class AddressLabel(Base, TimestampMixin):
    """Analyst-submitted label for an address: tags, PoC text/file, LLM audit verdict."""

    __tablename__ = "address_labels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    address: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    chain: Mapped[str] = mapped_column(String(16), nullable=False)

    # Analyst-supplied fields
    tags: Mapped[list | None] = mapped_column(JSON)           # e.g. ["mixer","scam","defi"]
    chronology: Mapped[str | None] = mapped_column(Text)      # free-text PoC / timeline
    poc_filename: Mapped[str | None] = mapped_column(String(255))   # original filename
    poc_content: Mapped[str | None] = mapped_column(Text)     # file text content (UTF-8 only)
    poc_mimetype: Mapped[str | None] = mapped_column(String(120))

    # LLM audit result
    audit_verdict: Mapped[str | None] = mapped_column(String(32))   # CONFIRMED / DISPUTED / INCONCLUSIVE
    audit_confidence: Mapped[float | None] = mapped_column(Float)   # 0.0–1.0
    audit_summary: Mapped[str | None] = mapped_column(Text)         # LLM reasoning
    audit_flags: Mapped[list | None] = mapped_column(JSON)          # list of concern strings
    audited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Submitter
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("investigation_cases.id", ondelete="SET NULL")
    )

    __table_args__ = (
        Index("ix_labels_address_chain", "address", "chain"),
    )
