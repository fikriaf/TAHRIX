"""Domain enums shared across SQL models, graph models, and Pydantic schemas."""

from __future__ import annotations

from enum import Enum


class Chain(str, Enum):
    ETH = "ETH"
    SOL = "SOL"
    BASE = "BASE"
    POLYGON = "POLYGON"
    BNB = "BNB"
    BTC = "BTC"
    TRON = "TRON"
    ARB = "ARB"
    OSINT = "OSINT"  # For OSINT-only entities (not a blockchain)


class UserRole(str, Enum):
    ANALYST = "analyst"
    SUPERVISOR = "supervisor"
    ADMIN = "admin"


class CaseStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    FAILED = "failed"


class RiskGrade(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @classmethod
    def from_score(cls, score: float) -> "RiskGrade":
        # score expected 0–100
        if score >= 80:
            return cls.CRITICAL
        if score >= 60:
            return cls.HIGH
        if score >= 30:
            return cls.MEDIUM
        return cls.LOW


class GnnLabel(str, Enum):
    UNKNOWN = "UNKNOWN"
    LICIT = "LICIT"
    ILLICIT = "ILLICIT"


class EntityType(str, Enum):
    EXCHANGE = "EXCHANGE"
    MIXER = "MIXER"
    DARKNET = "DARKNET"
    DEFI = "DEFI"
    BRIDGE = "BRIDGE"
    SANCTIONED = "SANCTIONED"
    UNKNOWN = "UNKNOWN"


class BridgeProtocol(str, Enum):
    LAYERZERO = "LAYERZERO"
    WORMHOLE = "WORMHOLE"
    STARGATE = "STARGATE"


class TxStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PENDING = "PENDING"


class AnomalyCode(str, Enum):
    """17 anomaly patterns from MVP §3.4."""

    P01_MIXER = "P01"
    P02_LAYERING = "P02"
    P03_FAN_OUT = "P03"
    P04_FAN_IN = "P04"
    P05_PEELING = "P05"
    P06_ROUND_TRIP = "P06"
    P07_BRIDGE_HOPPING = "P07"
    P08_WHALE = "P08"
    P09_DORMANT_REACTIVATION = "P09"
    P10_RAPID_SUCCESSION = "P10"
    P11_OFAC_INDIRECT = "P11"
    P12_DEX_WASH = "P12"
    P13_NFT_WASH = "P13"
    P14_FLASH_LOAN = "P14"
    P15_ADDRESS_POISONING = "P15"
    P16_RUG_PULL = "P16"
    P17_SANDWICH = "P17"
