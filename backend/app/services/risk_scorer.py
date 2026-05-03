"""Risk Scorer — aggregates GNN, Anomaly, Sanctions, Centrality, and OSINT/Threat signals.

Formula:
    Risk = (GNN × 0.35) + (Anomaly × 0.30) + (Sanctions × 0.20) + (Threat × 0.10) + (Centrality × 0.05)

If GNN unavailable its weight is renormalized into the remaining factors.
If no threat signal, its weight folds into anomaly.

Result in [0, 100] with grade thresholds 30/60/80.
"""

from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger
from app.models.domain import (
    AnomalyFlag,
    GnnPrediction,
    RiskAssessment,
    SanctionResult,
)
from app.models.enums import Chain, RiskGrade

logger = get_logger(__name__)


def _anomaly_weight(flags: list[AnomalyFlag]) -> float:
    """Aggregate severity of triggered flags into a single [0, 1] weight.

    Uses noisy-OR: monotonically increasing in count and severity.
    Also adds a flat boost per flag so that even 1 low-severity flag
    registers meaningfully.
    """
    if not flags:
        return 0.0
    # Flat boost: each flag contributes at least 0.08 regardless of severity
    flat_boost = min(0.40, len(flags) * 0.08)
    # Noisy-OR of severities
    p_clean = 1.0
    for f in flags:
        p_clean *= max(0.0, 1.0 - float(f.severity))
    noisy_or = 1.0 - p_clean
    return min(1.0, flat_boost + noisy_or * (1.0 - flat_boost))


def _threat_weight(
    *,
    threat_hits: int = 0,
    max_threat_severity: float = 0.0,
    osint_hits: int = 0,
) -> float:
    """Signal from darkweb/threat-intel findings and OSINT mentions.

    - Each confirmed threat hit adds significant weight.
    - OSINT mentions (web/social results linking this address to bad actors) add smaller weight.
    """
    if threat_hits == 0 and osint_hits == 0:
        return 0.0
    threat_component = min(1.0, threat_hits * 0.35 + max_threat_severity * 0.40)
    osint_component  = min(0.30, osint_hits * 0.04)
    return min(1.0, threat_component + osint_component)


def compute_risk(
    *,
    address: str,
    chain: Chain,
    gnn: GnnPrediction | None,
    anomaly_flags: list[AnomalyFlag],
    sanctions: SanctionResult | None,
    centrality: float = 0.0,
    # New: OSINT / threat intel signal from agent tool calls
    threat_hits: int = 0,
    max_threat_severity: float = 0.0,
    osint_hits: int = 0,
) -> RiskAssessment:
    # Base weights
    w_gnn   = 0.35
    w_anom  = 0.30
    w_sanc  = 0.20
    w_thr   = 0.10
    w_cent  = 0.05

    # If GNN unavailable, renormalize
    if gnn is None:
        total = w_anom + w_sanc + w_thr + w_cent
        if total > 0:
            f = 1.0 / total
            w_anom, w_sanc, w_thr, w_cent = (
                w_anom * f, w_sanc * f, w_thr * f, w_cent * f,
            )
        w_gnn = 0.0
        gnn_score = 0.0
    else:
        gnn_score = float(gnn.score)

    # If no threat signal, fold its weight into anomaly
    thr_score = _threat_weight(
        threat_hits=threat_hits,
        max_threat_severity=max_threat_severity,
        osint_hits=osint_hits,
    )
    if thr_score == 0.0:
        w_anom += w_thr
        w_thr   = 0.0

    anom_score = _anomaly_weight(anomaly_flags)
    sanc_score = 1.0 if (sanctions and sanctions.sanctioned) else 0.0
    cent_score = max(0.0, min(1.0, float(centrality)))

    raw = (
        gnn_score  * w_gnn
        + anom_score * w_anom
        + sanc_score * w_sanc
        + thr_score  * w_thr
        + cent_score * w_cent
    )
    score = max(0.0, min(100.0, raw * 100.0))

    # Sanctioned → auto-Critical
    if sanc_score == 1.0 and score < 90.0:
        score = max(score, 90.0)

    # Confirmed threat hit with severity >= 0.7 → floor at HIGH (60)
    if threat_hits > 0 and max_threat_severity >= 0.7 and score < 60.0:
        score = max(score, 60.0)

    # Confirmed mixer/OFAC entity (static DB severity >= 0.90) → CRITICAL floor
    # This catches Tornado Cash, Blender.io, Sinbad etc. investigated directly.
    if threat_hits > 0 and max_threat_severity >= 0.90 and score < 90.0:
        score = max(score, 90.0)

    # P01 self-mixer flag (focal address IS the mixer contract) → CRITICAL floor
    has_self_mixer = any(
        f.code.value == "P01" and float(f.severity) >= 1.0
        and bool(f.metadata) and f.metadata.get("self_mixer")
        for f in anomaly_flags
    )
    if has_self_mixer and score < 90.0:
        score = max(score, 90.0)

    grade = RiskGrade.from_score(score)

    explanation_parts: list[str] = []
    if gnn:
        explanation_parts.append(gnn.explanation or f"GNN illicit probability: {gnn_score:.2f}.")
    if anomaly_flags:
        codes = ", ".join(f.code.value for f in anomaly_flags)
        explanation_parts.append(f"Anomaly patterns triggered: {codes}.")
    if sanc_score:
        explanation_parts.append("Address present in OFAC SDN sanctions list.")
    if threat_hits:
        explanation_parts.append(
            f"{threat_hits} threat intelligence hit(s) (max severity {max_threat_severity:.2f})."
        )
    if osint_hits:
        explanation_parts.append(f"{osint_hits} OSINT mention(s) found.")
    if cent_score:
        explanation_parts.append(f"Network centrality: {cent_score:.2f}.")

    return RiskAssessment(
        address=address,
        chain=chain,
        score=score,
        grade=grade.value,
        components={
            "gnn":         gnn_score,
            "anomaly":     anom_score,
            "sanctions":   sanc_score,
            "threat":      thr_score,
            "centrality":  cent_score,
            "w_gnn":       w_gnn,
            "w_anomaly":   w_anom,
            "w_sanctions": w_sanc,
            "w_threat":    w_thr,
            "w_centrality":w_cent,
        },
        anomaly_flags=anomaly_flags,
        sanctions=sanctions,
        gnn=gnn,
        explanation=" ".join(explanation_parts) or None,
    )
