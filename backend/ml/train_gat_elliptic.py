"""Train a Graph Attention Network on the Elliptic Bitcoin Dataset.

Run:
    python ml/train_gat_elliptic.py

Artifacts written to ml/artifacts/:
    • gat_elliptic.pt        — torch state_dict
    • gat_elliptic.onnx      — ONNX export (used by the inference service)
    • gat_elliptic.metrics.json — eval metrics (F1, precision, recall, AUC)
"""

from __future__ import annotations

import json
from pathlib import Path

# These imports are intentionally inside the script — the API service does NOT
# depend on torch. ML deps live behind the [ml] extra.
import torch
import torch.nn.functional as F
from sklearn.metrics import (
    f1_score,
    precision_recall_fscore_support,
    roc_auc_score,
)
from torch_geometric.datasets import EllipticBitcoinDataset
from torch_geometric.nn import GATConv

ARTIFACTS = Path(__file__).parent / "artifacts"
ARTIFACTS.mkdir(parents=True, exist_ok=True)
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class GAT(torch.nn.Module):
    """3-layer GAT with multi-head attention as specified in MVP §3.4."""

    def __init__(self, in_dim: int, hidden_dims: tuple[int, ...] = (256, 128, 64),
                 heads: int = 8, num_classes: int = 2, dropout: float = 0.5) -> None:
        super().__init__()
        self.dropout = dropout
        self.gat1 = GATConv(in_dim, hidden_dims[0] // heads, heads=heads, dropout=dropout)
        self.gat2 = GATConv(hidden_dims[0], hidden_dims[1] // heads, heads=heads,
                            dropout=dropout)
        self.gat3 = GATConv(hidden_dims[1], hidden_dims[2], heads=1, concat=False,
                            dropout=dropout)
        self.out = torch.nn.Linear(hidden_dims[2], num_classes)

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        x = F.dropout(x, p=self.dropout, training=self.training)
        x = F.elu(self.gat1(x, edge_index))
        x = F.dropout(x, p=self.dropout, training=self.training)
        x = F.elu(self.gat2(x, edge_index))
        x = F.dropout(x, p=self.dropout, training=self.training)
        x = F.elu(self.gat3(x, edge_index))
        return self.out(x)  # logits


def train(epochs: int = 100, lr: float = 1e-3, weight_decay: float = 5e-4,
          patience: int = 15) -> None:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[train] device={device}")

    dataset = EllipticBitcoinDataset(root=str(DATA_DIR))
    data = dataset[0].to(device)

    # Elliptic labels: 0 = unknown (mask out), 1 = illicit, 2 = licit
    # Build binary masks: train on labeled nodes only.
    labeled_mask = data.y != -1 if hasattr(data, "y") else (data.y > 0)
    # Per the PyG version: y is already 0/1/2, but unknown often coded as 2.
    # The torch_geometric `EllipticBitcoinDataset` in recent versions exposes
    # train_mask/test_mask directly — use those if present.
    train_mask = getattr(data, "train_mask", labeled_mask)
    test_mask = getattr(data, "test_mask", labeled_mask)

    in_dim = data.num_node_features
    model = GAT(in_dim).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)

    best_f1, best_state, no_improve = 0.0, None, 0
    metrics: dict = {}

    for epoch in range(1, epochs + 1):
        model.train()
        optimizer.zero_grad()
        logits = model(data.x, data.edge_index)
        loss = F.cross_entropy(logits[train_mask], data.y[train_mask].long())
        loss.backward()
        optimizer.step()

        # Eval
        model.eval()
        with torch.no_grad():
            logits = model(data.x, data.edge_index)
            probs = torch.softmax(logits, dim=1)[:, 1]  # P(illicit)
            preds = logits.argmax(dim=1)
            y_true = data.y[test_mask].cpu().numpy()
            y_pred = preds[test_mask].cpu().numpy()
            y_prob = probs[test_mask].cpu().numpy()
            p, r, f1, _ = precision_recall_fscore_support(
                y_true, y_pred, average="binary", pos_label=1, zero_division=0,
            )
            try:
                auc = roc_auc_score(y_true, y_prob)
            except ValueError:
                auc = float("nan")

        if epoch % 10 == 0 or epoch == 1:
            print(f"[epoch {epoch:03d}] loss={loss.item():.4f} "
                  f"P={p:.3f} R={r:.3f} F1={f1:.3f} AUC={auc:.3f}")

        if f1 > best_f1:
            best_f1 = f1
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            no_improve = 0
            metrics = {"epoch": epoch, "loss": float(loss.item()),
                       "precision": float(p), "recall": float(r),
                       "f1": float(f1), "auc": float(auc)}
        else:
            no_improve += 1
            if no_improve >= patience:
                print(f"[early-stop] no improvement for {patience} epochs at epoch {epoch}")
                break

    if best_state is None:
        raise RuntimeError("training produced no usable checkpoint")

    pt_path = ARTIFACTS / "gat_elliptic.pt"
    torch.save({"state_dict": best_state, "in_dim": in_dim}, pt_path)
    (ARTIFACTS / "gat_elliptic.metrics.json").write_text(
        json.dumps(metrics, indent=2)
    )
    print(f"[done] best F1={best_f1:.3f}, saved → {pt_path}")
    print("Now run:  python ml/export_onnx.py")


if __name__ == "__main__":
    train()
