"""HTTP request/response schemas for the public API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import CaseStatus, Chain, UserRole


class _Base(BaseModel):
    """Response/output models — read from ORM attributes."""
    model_config = ConfigDict(from_attributes=True)


class _Input(BaseModel):
    """Request/input models — strict dict parsing."""
    model_config = ConfigDict(extra="forbid")


class ReportRequest(BaseModel):
    """Optional body for POST /cases/{id}/report."""
    graph_svg: str | None = None   # SVG string from frontend (inline, WeasyPrint renders natively)





# ── Auth ──
class UserCreate(_Input):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = None


class UserOut(_Base):
    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: UserRole
    is_active: bool
    created_at: datetime


class TokenPair(_Base):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class LoginRequest(_Input):
    email: EmailStr
    password: str


class APIKeyCreate(_Input):
    name: str = Field(min_length=1, max_length=120)
    tier: str = "free"


class APIKeyOut(_Base):
    id: uuid.UUID
    name: str
    key_prefix: str
    tier: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class APIKeyCreateOut(APIKeyOut):
    raw_key: str  # only returned ONCE on creation


# ── Investigation ──
class InvestigationStartRequest(_Input):
    address: str
    chain: Chain | None = None
    depth: int = Field(default=3, ge=1, le=5)
    iterations: int = Field(default=5, ge=1, le=10)


class AnomalyFlagOut(BaseModel):
    """Structured anomaly flag with severity and description."""
    code: str
    severity: float
    description: str
    evidence_tx_hashes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InvestigationCaseOut(_Base):
    id: uuid.UUID
    case_number: str
    input_address: str
    input_chain: str
    depth: int
    status: CaseStatus
    risk_score: float | None
    risk_grade: str | None
    gnn_score: float | None         # raw GAT illicit probability 0–1
    sanctions_hit: bool
    anomaly_score: float | None     # aggregated anomaly weight 0–1
    anomaly_codes: list[str] | None
    iterations: int
    confidence: float | None
    summary: str | None
    ipfs_cid: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class CaseEventOut(_Base):
    id: int = 0                     # surrogate key — useful for since_id polling
    iteration: int
    phase: str
    tool: str | None
    payload: dict[str, Any] | None
    result: dict[str, Any] | None
    duration_ms: int | None
    created_at: datetime


# ── Graph ──
class GraphNodeOut(BaseModel):
    address: str
    chain: str | None = None
    risk_score: float | None = None
    entity: str | None = None
    sanctioned: bool | None = None
    gnn_label: str | None = None
    is_focal: bool = False          # True for the investigated address


class GraphEdgeOut(BaseModel):
    source: str | None = None       # from address
    target: str | None = None       # to address
    tx_hash: str | None = None
    value_usd: float | None = None
    value_native: float | None = None
    timestamp: str | None = None


class CaseGraphOut(BaseModel):
    case_id: uuid.UUID
    address: str
    chain: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    node_count: int
    edge_count: int


class HealthResponse(_Base):
    status: str
    version: str
    components: dict[str, str]


# ── Telegram subscription ──
class TelegramLinkOut(_Base):
    deep_link: str
    token: str
    expires_at: str
    ttl_minutes: str


class TelegramSubscriptionOut(_Base):
    chat_id: str
    telegram_user_id: str | None
    telegram_username: str | None
    is_active: bool
    linked_at: datetime


# ── Address Labels ──
class AddressLabelCreate(_Input):
    """Analyst submits address intelligence label."""
    address: str = Field(min_length=1, max_length=80)
    chain: str = Field(default="ETH", min_length=1, max_length=16)
    tags: list[str] = Field(default_factory=list, max_length=20)
    chronology: str | None = Field(default=None, max_length=8000)
    poc_filename: str | None = Field(default=None, max_length=255)
    poc_content: str | None = Field(default=None, max_length=200_000)  # file text, base64 or plain
    poc_mimetype: str | None = Field(default=None, max_length=120)
    case_id: uuid.UUID | None = None


class AddressLabelAudit(BaseModel):
    """LLM audit result embedded in label response."""
    verdict: str                    # CONFIRMED / DISPUTED / INCONCLUSIVE
    confidence: float
    summary: str
    flags: list[str] = Field(default_factory=list)


class AddressLabelOut(_Base):
    id: uuid.UUID
    address: str
    chain: str
    tags: list[str] | None
    chronology: str | None
    poc_filename: str | None
    poc_mimetype: str | None
    audit_verdict: str | None
    audit_confidence: float | None
    audit_summary: str | None
    audit_flags: list[str] | None
    audited_at: datetime | None
    submitted_by: uuid.UUID | None
    case_id: uuid.UUID | None
    created_at: datetime
