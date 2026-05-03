# TAHRIX ML — GNN Training & Export

This directory contains the **offline** machine learning pipeline:

1. `train_gat_elliptic.py` — train a 3-layer Graph Attention Network on the Elliptic
   Bitcoin Dataset (a built-in PyG dataset).
2. `export_onnx.py` — export the trained PyTorch model to ONNX so the API service
   can do CPU-only inference without any heavy ML dependencies.
3. `compute_shap_baseline.py` — pre-compute SHAP background for explainability.

## Usage

```bash
pip install -e ".[ml]"           # installs torch + torch_geometric + shap
python ml/train_gat_elliptic.py  # 100 epochs, ~2-4 h on T4 GPU; auto-falls back to CPU
python ml/export_onnx.py         # writes ml/artifacts/gat_elliptic.onnx
```

Artifacts are git-ignored. The API service reads `GNN_MODEL_PATH` (defaults to
`./ml/artifacts/gat_elliptic.onnx`) at startup; if the model file is missing, GNN
inference is disabled (Risk Scorer drops to formula-only mode), and the agent logs
a warning.

## Why the API doesn't depend on torch

* ONNX Runtime is ~30 MB vs ~2 GB for torch.
* Inference is deterministic, GPU-optional, and ~10× faster on the same CPU.
* Re-training is a separate concern; deploy the API independently of model retrains.

## Dataset

Elliptic Bitcoin Dataset: 203,769 nodes (transactions), 234,355 edges, 165 features.
Labels: 1 (illicit), 2 (licit), 3 (unknown). The script trains a binary classifier
(1 vs 2) on labeled nodes and produces a sigmoid score in `[0, 1]`.

> Citation: Weber et al., "Anti-Money Laundering in Bitcoin: Experimenting with Graph
> Convolutional Networks for Financial Forensics", KDD '19 ML for Finance Workshop.
