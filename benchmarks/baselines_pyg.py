"""
Baselines GAD "heavy" (PyG/Torch) — skeleton.

Goal: DOMINANT, CoLA, GCNAE, ... as optional baselines for public benchmarks.

This file intentionally contains stubs so the repo stays light by default.
When ready:
- add an extra dependency (pyg/baselines)
- implement each baseline in a small, testable function
- plug into benchmarks/public_benchmark.py

References (to implement later):
- DOMINANT (Deep Anomaly Detection on Attributed Networks)
- CoLA (Contrastive Self-Supervised Learning for Anomaly Detection)
- GCNAE (GCN Autoencoder variants)
"""

from __future__ import annotations


def dominant_score(*args, **kwargs) -> float:  # pragma: no cover
    raise NotImplementedError("DOMINANT baseline not implemented yet. Install extras + implement.")


def cola_score(*args, **kwargs) -> float:  # pragma: no cover
    raise NotImplementedError("CoLA baseline not implemented yet. Install extras + implement.")


def gcnae_score(*args, **kwargs) -> float:  # pragma: no cover
    raise NotImplementedError("GCNAE baseline not implemented yet. Install extras + implement.")
