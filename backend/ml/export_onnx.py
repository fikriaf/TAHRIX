"""Export the trained GAT model to ONNX for CPU inference.

ONNX export of GAT layers is non-trivial because PyG's `GATConv` uses scatter
ops that ONNX doesn't natively support without `torch.onnx.export(..., dynamo=True)`
or a custom op registration. We use the torch.onnx.dynamo_export path (PyTorch 2.4+).
"""

from __future__ import annotations

from pathlib import Path

import torch
from torch_geometric.datasets import EllipticBitcoinDataset

from ml.train_gat_elliptic import GAT

ARTIFACTS = Path(__file__).parent / "artifacts"
DATA_DIR = Path(__file__).parent / "data"


def export(pt_path: Path | None = None,
           out_path: Path | None = None) -> None:
    pt_path = pt_path or (ARTIFACTS / "gat_elliptic.pt")
    out_path = out_path or (ARTIFACTS / "gat_elliptic.onnx")

    if not pt_path.exists():
        raise FileNotFoundError(f"checkpoint not found: {pt_path}. "
                                f"Run train_gat_elliptic.py first.")

    state = torch.load(pt_path, map_location="cpu", weights_only=True)
    in_dim = state.get("in_dim", 165)
    model = GAT(in_dim)
    model.load_state_dict(state["state_dict"])
    model.eval()

    # Build dummy inputs from the dataset to drive the export with realistic shapes.
    dataset = EllipticBitcoinDataset(root=str(DATA_DIR))
    data = dataset[0]

    x = data.x[:128].clone()                 # [128, in_dim]
    edge_index = data.edge_index[:, :256].clone()  # [2, 256]

    # PyTorch 2.5+: torch.onnx.export supports dynamo for graph models.
    torch.onnx.export(
        model,
        (x, edge_index),
        str(out_path),
        input_names=["x", "edge_index"],
        output_names=["logits"],
        dynamic_axes={
            "x": {0: "num_nodes"},
            "edge_index": {1: "num_edges"},
            "logits": {0: "num_nodes"},
        },
        opset_version=18,
    )
    print(f"[done] wrote {out_path} ({out_path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    export()
