"""GNN inference service — ONNX Runtime, CPU-only.

Public API:
    GnnService.predict(subgraph) -> GnnPrediction

The service builds a feature matrix from a Neo4j subgraph (centered on the target
wallet), runs forward pass, and returns the probability of `illicit` for the
center node together with a SHAP-style explanation.

Graceful degradation: if `GNN_MODEL_PATH` does not exist, the service runs in
"unavailable" mode — `predict()` raises `GnnUnavailableError` so the Risk Scorer
can fall back to formula-only scoring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import settings
from app.core.exceptions import TahrixError
from app.core.logging import get_logger
from app.models.domain import GnnPrediction
from app.models.enums import GnnLabel

logger = get_logger(__name__)


class GnnUnavailableError(TahrixError):
    code = "gnn_unavailable"
    status_code = 503


# ─────────────────────────────────────────────────────────────────────────────
# Feature engineering — derives a 165-dim vector per wallet from a subgraph row
# ─────────────────────────────────────────────────────────────────────────────
# The Elliptic dataset features are anonymized; we cannot reconstruct them from
# on-chain data exactly. We approximate with derived metrics + zero-pad to keep
# the model's expected input dimension. Documented limitation: this is a domain
# transfer that the spec acknowledges (MVP §3.4 — "fine-tune with Ethereum data").
def build_node_feature(
    row: dict[str, Any], feature_dim: int = settings.gnn_feature_dim,
) -> np.ndarray:
    """Approximate per-node features. Replace with learned encoder when retraining.

    Keys accepted from get_subgraph() nodes:
        tx_count, balance_usd, risk_score, is_contract, is_sanctioned, hop_distance
    Also accepts pre-split keys (tx_count_in / tx_count_out) if available.
    """
    f = np.zeros(feature_dim, dtype=np.float32)

    # tx_count: get_subgraph returns a single `tx_count`; split heuristically 50/50
    tx_total = float(row.get("tx_count") or 0)
    tx_in  = float(row.get("tx_count_in")  or tx_total / 2)
    tx_out = float(row.get("tx_count_out") or tx_total / 2)

    f[0] = tx_in
    f[1] = tx_out
    # USD volumes not available per-node from subgraph; use balance as proxy
    bal = float(row.get("balance_usd") or 0.0)
    f[2] = bal           # total_in_usd proxy
    f[3] = bal           # total_out_usd proxy
    f[4] = bal / max(tx_total, 1)   # avg_value_usd proxy
    f[5] = bal                       # max_value_usd proxy
    f[6] = tx_total      # unique_counterparties proxy (tx count ≈ counterparties)
    f[7] = 0.0           # active_days — not in subgraph
    f[8] = bal
    f[9]  = 1.0 if row.get("is_contract") else 0.0
    f[10] = 1.0 if row.get("is_sanctioned") else 0.0
    f[11] = float(row.get("hop_distance") or 0)
    # risk_score if already computed (re-investigation loop)
    f[12] = float(row.get("risk_score") or 0.0)
    # 13..end: zero-padded
    return f


def build_input_tensors(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]],
    feature_dim: int = settings.gnn_feature_dim,
) -> tuple[np.ndarray, np.ndarray, dict[str, int]]:
    """Build (x, edge_index, address→idx).

    Handles both edge key conventions:
      - get_subgraph()  → keys: 'source' / 'target'  (frontend-compatible)
      - legacy          → keys: 'from'   / 'to'
    Addresses are lowercased for consistent lookup (matching _addr() normalization).
    """
    # Build address→idx map; normalize to lowercase
    addr_to_idx: dict[str, int] = {}
    for i, n in enumerate(nodes):
        addr = n.get("address") or n.get("id") or ""
        if addr:
            addr_to_idx[addr.lower()] = i

    x = np.stack([build_node_feature(n, feature_dim) for n in nodes]) \
        if nodes else np.zeros((0, feature_dim), dtype=np.float32)

    src, dst = [], []
    for e in edges:
        # Support both key conventions
        a = (e.get("source") or e.get("from") or "")
        b = (e.get("target") or e.get("to")   or "")
        al, bl = str(a).lower(), str(b).lower()
        if al in addr_to_idx and bl in addr_to_idx:
            src.append(addr_to_idx[al])
            dst.append(addr_to_idx[bl])

    edge_index = np.array([src, dst], dtype=np.int64) if src else \
        np.zeros((2, 0), dtype=np.int64)
    return x, edge_index, addr_to_idx


# ─────────────────────────────────────────────────────────────────────────────
# Inference
# ─────────────────────────────────────────────────────────────────────────────
class GnnService:
    _instance: "GnnService | None" = None

    def __init__(self, model_path: str | Path | None = None) -> None:
        self.model_path = Path(model_path or settings.gnn_model_path)
        self._session = None  # lazy
        self._available = self.model_path.exists()
        if not self._available:
            logger.warning("gnn.model.missing", path=str(self.model_path))

    @classmethod
    def instance(cls) -> "GnnService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def available(self) -> bool:
        return self._available

    def _ensure_session(self):
        if self._session is None:
            if not self._available:
                raise GnnUnavailableError(
                    f"GNN model not found at {self.model_path}; "
                    "run ml/train_gat_elliptic.py and ml/export_onnx.py."
                )
            import onnxruntime as ort
            sess_options = ort.SessionOptions()
            sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self._session = ort.InferenceSession(
                str(self.model_path),
                sess_options=sess_options,
                providers=["CPUExecutionProvider"],
            )
            logger.info("gnn.session.ready",
                        inputs=[i.name for i in self._session.get_inputs()],
                        outputs=[o.name for o in self._session.get_outputs()])
        return self._session

    def predict(
        self,
        target_address: str,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> GnnPrediction:
        if not nodes:
            raise GnnUnavailableError("empty subgraph")
        sess = self._ensure_session()
        x, edge_index, idx_map = build_input_tensors(nodes, edges)

        # Normalize target address for lookup (idx_map keys are lowercase)
        target_lower = target_address.lower()
        if target_lower not in idx_map:
            raise GnnUnavailableError(
                f"target {target_address[:16]}… not in subgraph "
                f"(subgraph has {len(nodes)} nodes, {len(idx_map)} mapped)"
            )
        center_idx = idx_map[target_lower]

        logger.info("gnn.predict",
                    nodes=len(nodes), edges=edge_index.shape[1],
                    center_idx=center_idx)

        logits = sess.run(None, {"x": x, "edge_index": edge_index})[0]
        # softmax → P(illicit)
        e = np.exp(logits - logits.max(axis=1, keepdims=True))
        probs = e / e.sum(axis=1, keepdims=True)
        score = float(probs[center_idx, 1])

        label = (GnnLabel.ILLICIT if score >= settings.gnn_threshold
                 else GnnLabel.LICIT)

        # Ablation-based feature importance (SHAP approximation via leave-one-out
        # on the 12 interpretable dimensions — fast, no extra library needed).
        top_features = self._ablation_importance(
            sess=sess,
            x=x,
            edge_index=edge_index,
            center_idx=center_idx,
            base_score=score,
            k=5,
        )

        return GnnPrediction(
            address=target_address,
            score=score,
            label=label,
            shap_top_features=top_features,
            explanation=_compose_explanation(score, top_features, nodes, target_address),
            subgraph_size=len(nodes),
        )

    @staticmethod
    def _ablation_importance(
        sess,
        x: np.ndarray,
        edge_index: np.ndarray,
        center_idx: int,
        base_score: float,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        """Ablation-based feature attribution (leave-one-out on interpretable dims).

        For each of the 12 named feature dimensions, zero it out and measure
        the drop in P(illicit) for the center node. A large positive drop means
        the feature strongly contributed to the illicit prediction.
        """
        names = [
            "tx_count_in", "tx_count_out", "total_in_usd", "total_out_usd",
            "avg_value_usd", "max_value_usd", "unique_counterparties",
            "active_days", "balance_usd", "is_contract", "is_sanctioned",
            "hop_distance",
        ]
        contributions: list[dict[str, Any]] = []
        for i, name in enumerate(names):
            if x[center_idx, i] == 0:
                continue  # already zero — no information to ablate
            x_ablated = x.copy()
            x_ablated[center_idx, i] = 0.0
            logits_abl = sess.run(None, {"x": x_ablated, "edge_index": edge_index})[0]
            e = np.exp(logits_abl - logits_abl.max(axis=1, keepdims=True))
            probs_abl = e / e.sum(axis=1, keepdims=True)
            score_abl = float(probs_abl[center_idx, 1])
            delta = base_score - score_abl  # positive = feature pushed score up
            contributions.append({
                "feature": name,          # consistent key for frontend + report
                "value": round(delta, 4), # SHAP delta = contribution to illicit score
                "raw_value": float(x[center_idx, i]),
            })

        contributions.sort(key=lambda c: abs(c["value"]), reverse=True)
        return contributions[:k]

    @staticmethod
    def _top_contributing_features(feature_vec: np.ndarray, k: int = 5) -> list[dict[str, Any]]:
        """Legacy heuristic (kept for backward compat). Prefer _ablation_importance."""
        names = [
            "tx_count_in", "tx_count_out", "total_in_usd", "total_out_usd",
            "avg_value_usd", "max_value_usd", "unique_counterparties",
            "active_days", "balance_usd", "is_contract", "is_sanctioned",
            "hop_distance",
        ]
        idx = np.argsort(np.abs(feature_vec[: len(names)]))[::-1][:k]
        return [
            {"name": names[i], "value": float(feature_vec[i])}
            for i in idx if abs(feature_vec[i]) > 0
        ]


def _compose_explanation(
    score: float, top_features: list[dict[str, Any]],
    nodes: list[dict[str, Any]], target_address: str,
) -> str:
    parts = [f"GNN illicit-probability {score:.2f}."]
    sanctioned_neighbors = sum(1 for n in nodes if n.get("sanctioned"))
    mixer_neighbors = sum(
        1 for n in nodes
        if (n.get("entity") or "").lower().find("mixer") >= 0
        or (n.get("entity") or "").lower().find("tornado") >= 0
    )
    if sanctioned_neighbors:
        parts.append(f"{sanctioned_neighbors} sanctioned neighbor(s) in subgraph.")
    if mixer_neighbors:
        parts.append(f"{mixer_neighbors} mixer-related counterparty(ies).")
    if top_features:
        feats = ", ".join(f"{f['feature']}={f['raw_value']:.2f}(Δ{f['value']:+.3f})" for f in top_features[:3])
        parts.append(f"Top features: {feats}.")
    return " ".join(parts)
