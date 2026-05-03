"""Pydantic v2 schemas for the domain (transactions, wallets, bridges, etc.).

These types are the *internal* canonical representation flowing between
adapters → services → repositories. Adapters are responsible for mapping
provider-specific JSON into these models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    AnomalyCode,
    BridgeProtocol,
    Chain,
    EntityType,
    GnnLabel,
    TxStatus,
)


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=False, extra="forbid")


# ── Wallet & Transaction ──
class WalletNode(_Base):
    address: str
    chain: Chain
    balance_usd: float | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    tx_count: int | None = None
    risk_score: float | None = None
    gnn_label: GnnLabel = GnnLabel.UNKNOWN
    entity_label: str | None = None
    is_contract: bool = False
    is_sanctioned: bool = False


class TransactionNode(_Base):
    hash: str
    chain: Chain
    from_address: str
    to_address: str | None
    value_native: float = 0.0
    value_usd: float | None = None
    asset: str | None = None  # ETH, SOL, USDC, etc.
    timestamp: datetime
    block_number: int | None = None
    gas_used: int | None = None
    status: TxStatus = TxStatus.SUCCESS
    method: str | None = None  # smart-contract method (if any)
    raw: dict[str, Any] | None = None  # provider-specific raw blob (kept for evidence)


class BridgeEvent(_Base):
    id: str  # provider-derived deterministic id (e.g. lz:<guid>, wh:<vaa_id>)
    protocol: BridgeProtocol
    source_chain: Chain
    dest_chain: Chain
    source_tx_hash: str
    dest_tx_hash: str | None = None
    source_address: str | None = None
    dest_address: str | None = None
    message_id: str | None = None  # GUID/VAA
    timestamp: datetime
    value_usd: float | None = None
    status: str | None = None


class EntityLabel(_Base):
    name: str
    type: EntityType
    source: str  # ETHERSCAN_TAG, CHAINALYSIS, MANUAL
    risk_level: str | None = None


# ── Sanctions ──
class SanctionResult(_Base):
    address: str
    sanctioned: bool
    identifications: list[dict[str, Any]] = Field(default_factory=list)
    source: str = "chainalysis"
    checked_at: datetime


# ── Anomaly ──
class AnomalyFlag(_Base):
    code: AnomalyCode
    severity: float = Field(ge=0.0, le=1.0)
    description: str
    evidence_tx_hashes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── GNN ──
class GnnPrediction(_Base):
    address: str
    score: float = Field(ge=0.0, le=1.0)
    label: GnnLabel
    shap_top_features: list[dict[str, Any]] = Field(default_factory=list)
    explanation: str | None = None
    subgraph_size: int = 0


# ── Risk ──
class RiskAssessment(_Base):
    address: str
    chain: Chain
    score: float = Field(ge=0.0, le=100.0)
    grade: str
    components: dict[str, float]  # gnn, anomaly, sanctions, centrality
    anomaly_flags: list[AnomalyFlag] = Field(default_factory=list)
    sanctions: SanctionResult | None = None
    gnn: GnnPrediction | None = None
    explanation: str | None = None


# ── Cross-chain trace ──
class CrossChainTrace(_Base):
    protocol: BridgeProtocol
    source_tx: str
    dest_tx: str | None
    source_chain: Chain
    dest_chain: Chain
    source_address: str | None = None
    dest_address: str | None = None
    value_usd: float | None = None
    message_id: str | None = None
    delivered: bool = False
    raw: dict[str, Any] | None = None


# ── OSINT ──
class OsintNode(_Base):
    """An open-source intelligence artifact linked to a wallet or entity."""
    source: str                     # "web_search" | "whois" | "social_media" | "manual"
    entity_ref: str                 # wallet address or entity name this is linked to
    url: str = ""                   # source URL
    snippet: str = ""               # text excerpt (≤300 chars)
    platform: str = "web"           # "web" | "twitter" | "reddit" | "telegram"
    retrieved_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Threat Intel ──
class ThreatIntelHit(_Base):
    """A threat intelligence finding linked to a wallet address."""
    source: str                     # "chainalysis_ofac" | "darkweb_monitor" | "static_threat_db"
    address: str                    # the wallet address flagged
    threat_type: str                # "SANCTIONED" | "mixer" | "ransomware" | "mention"
    severity: float = Field(ge=0.0, le=1.0, default=0.5)
    description: str = ""
    url: str | None = None          # evidence URL (if any)
    confirmed: bool = False
    detected_at: datetime | None = None
    raw: dict[str, Any] | None = None
