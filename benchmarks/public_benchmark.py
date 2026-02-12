#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Public benchmark for EchoNull-GAD (graph-level anomaly detection).

Design:
- Use a base graph (synthetic by default).
- Generate many variants: normal (label 0) vs null-trace anomalies (label 1).
- Score each variant with EchoNull's lightweight scoring primitives.
- Report AUC / Average Precision / Recall@k.

Optional:
- Cora/PubMed loaders via torch_geometric if installed.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import networkx as nx
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import echonull  # noqa: E402


@dataclass
class BenchRow:
    idx: int
    label: int
    score: float
    missing_edge_ratio: float
    isolated_ratio: float
    silent_nodes: int
    n_edges: int


def roc_auc(y_true: Sequence[int], y_score: Sequence[float]) -> float:
    """Compute AUC without sklearn using the rank statistic."""
    y_true_arr = np.asarray(y_true, dtype=int)
    score_arr = np.asarray(y_score, dtype=float)

    pos = int(np.sum(y_true_arr == 1))
    neg = int(np.sum(y_true_arr == 0))
    if pos == 0 or neg == 0:
        return float("nan")

    order = np.argsort(score_arr)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(score_arr) + 1, dtype=float)
    sum_ranks_pos = float(np.sum(ranks[y_true_arr == 1]))
    auc = (sum_ranks_pos - (pos * (pos + 1) / 2.0)) / float(pos * neg)
    return float(auc)


def average_precision(y_true: Sequence[int], y_score: Sequence[float]) -> float:
    """Compute AP without sklearn."""
    y_true_arr = np.asarray(y_true, dtype=int)
    score_arr = np.asarray(y_score, dtype=float)

    order = np.argsort(-score_arr)
    y_sorted = y_true_arr[order]
    pos_total = int(np.sum(y_sorted == 1))
    if pos_total == 0:
        return float("nan")

    precisions: List[float] = []
    tp = 0
    for i, y in enumerate(y_sorted, start=1):
        if y == 1:
            tp += 1
            precisions.append(tp / i)

    return float(np.mean(precisions)) if precisions else float("nan")


def recall_at_k(y_true: Sequence[int], y_score: Sequence[float], k: int) -> float:
    y_true_arr = np.asarray(y_true, dtype=int)
    score_arr = np.asarray(y_score, dtype=float)

    if k <= 0:
        return 0.0

    order = np.argsort(-score_arr)[:k]
    pos_total = int(np.sum(y_true_arr == 1))
    if pos_total == 0:
        return float("nan")

    return float(np.sum(y_true_arr[order] == 1) / pos_total)


def make_base_graph(dataset: str, seed: int) -> nx.Graph:
    ds = dataset.lower().strip()

    if ds == "synthetic":
        # Barabasi-Albert gives a heavy-tail degree distribution (useful for bridge cuts).
        return nx.barabasi_albert_graph(n=400, m=3, seed=int(seed))

    if ds in ("cora", "pubmed"):
        # Optional Planetoid loader (PyG). If not installed, give a clear error.
        try:
            from torch_geometric.datasets import Planetoid
            from torch_geometric.utils import to_networkx
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "torch_geometric is not installed. Use dataset=synthetic, or install extras."
            ) from e

        name = "Cora" if ds == "cora" else "PubMed"
        data = Planetoid(root=str(Path(".") / ".bench_data"), name=name)[0]
        return to_networkx(data, to_undirected=True)

    raise ValueError(f"Unknown dataset: {dataset}")


def inject_null_trace(
    base: nx.Graph,
    rng: np.random.Generator,
    mode: str,
    severity: float,
) -> Tuple[nx.Graph, Dict[str, float], int]:
    """Create a variant graph as a subset of base edges (edge deletions only)."""
    mode = mode.lower().strip()
    severity = float(np.clip(severity, 0.0, 1.0))

    g = nx.Graph()
    g.add_nodes_from(base.nodes(data=True))
    g.add_edges_from(base.edges())

    silent_nodes = 0

    if mode == "edge_missing":
        # Drop a fraction of edges uniformly.
        edges = list(g.edges())
        drop_n = int(severity * len(edges))
        if drop_n > 0:
            drop_idx = rng.choice(len(edges), size=drop_n, replace=False)
            g.remove_edges_from([edges[i] for i in drop_idx])

    elif mode == "silent_nodes":
        # Pick k nodes and remove all incident edges (creates isolated/silent nodes).
        nodes = list(g.nodes())
        k = max(1, int(severity * 0.1 * len(nodes)))
        bad = nodes[:k]
        g.remove_edges_from(list(g.edges(bad)))
        silent_nodes = k

    elif mode == "bridge_break":
        # Remove top betweenness edges (approximate "bridge missing").
        if g.number_of_edges() > 0:
            edges = list(g.edges())
            if len(edges) <= 2000:
                sample = edges
            else:
                sample = [edges[i] for i in rng.choice(len(edges), 2000, replace=False)]

            # Compute betweenness on a subgraph sample for speed.
            sub = nx.Graph()
            sub.add_nodes_from(g.nodes())
            sub.add_edges_from(sample)
            bet = nx.edge_betweenness_centrality(sub, k=None, normalized=True)
            ranked = sorted(bet.items(), key=lambda x: x[1], reverse=True)
            drop_n = max(1, int(severity * 0.02 * len(edges)))
            to_drop = [e for e, _ in ranked[: min(drop_n, len(ranked))]]
            g.remove_edges_from(to_drop)
    else:
        raise ValueError(f"Unknown mode: {mode}")

    base_edges = max(1, base.number_of_edges())
    missing_edge_ratio = float(base.number_of_edges() - g.number_of_edges()) / float(
        base_edges
    )
    isolated_ratio = float(sum(1 for _, deg in g.degree() if deg == 0)) / float(
        max(1, g.number_of_nodes())
    )
    metrics = {
        "missing_edge_ratio": missing_edge_ratio,
        "isolated_ratio": isolated_ratio,
    }
    return g, metrics, int(silent_nodes)


def score_variant(
    base: nx.Graph, var: nx.Graph, thresholds: Sequence[float]
) -> Tuple[float, Dict[str, float], int]:
    base_edges = max(1, base.number_of_edges())
    missing_edge_ratio = float(base.number_of_edges() - var.number_of_edges()) / float(
        base_edges
    )
    isolated_ratio = float(sum(1 for _, deg in var.degree() if deg == 0)) / float(
        max(1, var.number_of_nodes())
    )
    silent_nodes = int(sum(1 for _, deg in var.degree() if deg == 0))

    # RiftLens: for deletion-only variants, jaccard reduces to edge_keep_ratio.
    jacc = float(var.number_of_edges()) / float(base_edges)
    anomaly_flag = bool((missing_edge_ratio > 0.02) or (isolated_ratio > 0.01))

    rift_by_thr = {
        float(t): {"jaccard": jacc, "anomaly_flag": anomaly_flag} for t in thresholds
    }

    # Map graph ratios to a nulltrace-like numeric range ~1e-4..2e-2
    p99 = max(1e-6, (missing_edge_ratio + isolated_ratio) * 1.0e-2)
    mad = max(1e-6, isolated_ratio * 5.0e-3)

    nulltrace = {"abs_p99": float(p99), "abs_mad": float(mad)}
    voidmark = {"anomaly_count": int(silent_nodes > 0) + int(missing_edge_ratio > 0.05)}

    score = echonull.compute_anomaly_score(
        rift_by_thr, nulltrace, voidmark, score_weights=(0.4, 0.4, 0.2)
    )
    return (
        float(score),
        {"missing_edge_ratio": missing_edge_ratio, "isolated_ratio": isolated_ratio},
        silent_nodes,
    )


def run_benchmark(
    dataset: str,
    variants: int,
    anomaly_frac: float,
    mode: str,
    severity: float,
    thresholds: Sequence[float],
    seed: int,
    out_dir: Path,
) -> Dict[str, object]:
    out_dir.mkdir(parents=True, exist_ok=True)

    base = make_base_graph(dataset, seed=seed)
    rng = np.random.default_rng(seed)

    rows: List[BenchRow] = []
    y_true: List[int] = []
    y_score: List[float] = []

    # Light baselines (no PyG): purely structural signals
    y_missing: List[float] = []
    y_isolated: List[float] = []
    y_combo: List[float] = []

    n_anom = int(round(float(variants) * float(anomaly_frac)))
    labels = np.array([1] * n_anom + [0] * (variants - n_anom), dtype=int)
    rng.shuffle(labels)

    for i in range(variants):
        label = int(labels[i])
        if label == 1:
            var, _, silent_nodes = inject_null_trace(
                base, rng=rng, mode=mode, severity=severity
            )
        else:
            # "Normal" variant: tiny edge noise
            var, _, silent_nodes = inject_null_trace(
                base, rng=rng, mode="edge_missing", severity=0.002
            )

        score, met, silent_nodes2 = score_variant(base, var, thresholds=thresholds)
        silent_nodes = int(max(silent_nodes, silent_nodes2))

        y_missing.append(float(met["missing_edge_ratio"]))
        y_isolated.append(float(met["isolated_ratio"]))
        y_combo.append(float(met["missing_edge_ratio"]) + float(met["isolated_ratio"]))

        rows.append(
            BenchRow(
                idx=i,
                label=label,
                score=score,
                missing_edge_ratio=float(met["missing_edge_ratio"]),
                isolated_ratio=float(met["isolated_ratio"]),
                silent_nodes=silent_nodes,
                n_edges=int(var.number_of_edges()),
            )
        )
        y_true.append(label)
        y_score.append(float(score))

    auc = roc_auc(y_true, y_score)
    ap = average_precision(y_true, y_score)

    auc_missing = roc_auc(y_true, y_missing)
    ap_missing = average_precision(y_true, y_missing)
    auc_isolated = roc_auc(y_true, y_isolated)
    ap_isolated = average_precision(y_true, y_isolated)
    auc_combo = roc_auc(y_true, y_combo)
    ap_combo = average_precision(y_true, y_combo)

    k5 = max(1, int(0.05 * variants))
    k10 = max(1, int(0.10 * variants))
    r5 = recall_at_k(y_true, y_score, k=k5)
    r10 = recall_at_k(y_true, y_score, k=k10)

    scores_csv = out_dir / "scores.csv"
    import pandas as pd  # local import to keep startup minimal

    pd.DataFrame([r.__dict__ for r in rows]).to_csv(scores_csv, index=False)

    report = {
        "dataset": dataset,
        "variants": int(variants),
        "anomaly_frac": float(anomaly_frac),
        "mode": mode,
        "severity": float(severity),
        "thresholds": [float(t) for t in thresholds],
        "seed": int(seed),
        "metrics": {
            "echonull": {
                "roc_auc": float(auc),
                "avg_precision": float(ap),
                "recall_at_5pct": float(r5),
                "recall_at_10pct": float(r10),
            },
            "baseline_missing_edge_ratio": {
                "roc_auc": float(auc_missing),
                "avg_precision": float(ap_missing),
            },
            "baseline_isolated_ratio": {
                "roc_auc": float(auc_isolated),
                "avg_precision": float(ap_isolated),
            },
            "baseline_combo": {
                "roc_auc": float(auc_combo),
                "avg_precision": float(ap_combo),
            },
        },
        "outputs": {"scores_csv": str(scores_csv)},
    }

    with open(out_dir / "benchmark_results.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return report


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="EchoNull-GAD public benchmark")
    p.add_argument(
        "--dataset",
        type=str,
        default="synthetic",
        choices=["synthetic", "cora", "pubmed"],
    )
    p.add_argument("--variants", type=int, default=300)
    p.add_argument("--anomaly-frac", type=float, default=0.2)
    p.add_argument(
        "--mode",
        type=str,
        default="silent_nodes",
        choices=["edge_missing", "silent_nodes", "bridge_break"],
    )
    p.add_argument("--severity", type=float, default=0.9)
    p.add_argument("--thresholds", type=str, default="0.25,0.5,0.7,0.8")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out-dir", type=str, default="bench_out")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    thresholds = [float(x.strip()) for x in args.thresholds.split(",") if x.strip()]

    report = run_benchmark(
        dataset=args.dataset,
        variants=args.variants,
        anomaly_frac=args.anomaly_frac,
        mode=args.mode,
        severity=args.severity,
        thresholds=thresholds,
        seed=args.seed,
        out_dir=Path(args.out_dir),
    )
    print(json.dumps(report["metrics"], indent=2))


if __name__ == "__main__":
    main()
