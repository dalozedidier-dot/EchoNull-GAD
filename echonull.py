#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EchoNull - Lightweight CI-native framework for graph and null-trace anomaly detection
via massive parameter sweeps.

Version: 0.1.0 (2026 Pushed Edition)

CLI:
- sweep: exécute N runs, génère artefacts, overview, manifest, zip, viz optionnelle
- gad: idem mais poids de scoring configurables
- test: tests unitaires rapides
- bench: mini bench + memory tracking optionnel

Dépendances optionnelles:
- viz: matplotlib
- ml: torch
- scale: dask[distributed]
- perf: memory_profiler
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import logging
import math
import os
import time
import sys
import unittest
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, asdict, field
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple, cast

import numpy as np
import pandas as pd

from typing import Any as _Any

# Optional dependencies. We bind imports to internal names first and then
# expose stable public variables to avoid mypy "no-redef" errors.
plt: _Any | None
torch: _Any | None
torch_nn: _Any | None
nn: _Any | None
tqdm: _Any | None

try:
    import matplotlib.pyplot as _plt
except Exception:  # pragma: no cover
    _plt = None
plt = _plt

try:
    import torch as _torch
    import torch.nn as _torch_nn
except Exception:  # pragma: no cover
    _torch = None
    _torch_nn = None
torch = _torch
torch_nn = _torch_nn
# Backward compatible alias used elsewhere in the code.
nn = _torch_nn

try:
    from tqdm import tqdm as _tqdm
except Exception:  # pragma: no cover
    _tqdm = None
tqdm = _tqdm

try:
    import networkx as nx
except Exception:  # pragma: no cover
    nx = None

try:
    from dask.distributed import Client, LocalCluster
except Exception:  # pragma: no cover
    Client = None
    LocalCluster = None

try:
    import memory_profiler
except Exception:  # pragma: no cover
    memory_profiler = None


# Torch optional: define a local autoencoder class only if torch is available.
# We keep typing permissive because torch is an optional dependency.
DenoisingAutoencoder: _Any = None
if torch is not None and _torch_nn is not None:

    class _DenoisingAutoencoder(_torch_nn.Module):
        def __init__(self, input_size: int = 50) -> None:
            super().__init__()
            self.encoder = _torch_nn.Sequential(
                _torch_nn.Linear(input_size, 32),
                _torch_nn.ReLU(),
                _torch_nn.Linear(32, 16),
            )
            self.decoder = _torch_nn.Sequential(
                _torch_nn.Linear(16, 32),
                _torch_nn.ReLU(),
                _torch_nn.Linear(32, input_size),
            )

        def forward(self, x: _Any) -> _Any:
            return self.decoder(self.encoder(x))

    DenoisingAutoencoder = _DenoisingAutoencoder

logger = logging.getLogger("EchoNull")
logger.setLevel(logging.INFO)

if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s")
    )
    logger.addHandler(console_handler)

_FILE_LOG_PATH: Optional[Path] = None


def ensure_file_logging(log_path: Path) -> None:
    """Attach a file handler to the module logger (one per process).

    We intentionally avoid writing logs in repo root by default. The orchestrator configures a log
    under the selected output directory.
    """
    global _FILE_LOG_PATH
    log_path = Path(log_path)

    if _FILE_LOG_PATH is not None and Path(_FILE_LOG_PATH) == log_path:
        return

    for h in list(logger.handlers):
        if isinstance(h, logging.FileHandler):
            logger.removeHandler(h)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(str(log_path), mode="a", encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s")
    )
    logger.addHandler(file_handler)
    _FILE_LOG_PATH = log_path


BASE_OUTPUT_DIR = Path("_echonull_out")
TIMESTAMP = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S")
VERSION = "0.1.0"


@dataclass
class RiftLensResult:
    threshold: float
    n_nodes: int
    n_edges: int
    base_edges: int = 0
    edge_keep_ratio: float = 0.0
    jaccard: float = 1.0
    silent_nodes: int = 0
    anomaly_flag: bool = False
    path_report: str = ""
    # Backward-compat fields (kept, but unused)
    path_tmp: str = ""


@dataclass
class NullTraceResult:
    n_deltas: int = 21
    abs_p50: float = 0.0
    abs_p90: float = 0.0
    abs_p99: float = 0.0
    abs_mad: float = 0.0
    abs_max: float = 0.0
    denoised_mean: float = 0.0
    # Optional graph-derived null-trace indicators (kept small and scalar)
    graph_missing_edge_ratio: float = 0.0
    graph_isolated_ratio: float = 0.0


@dataclass
class VoidMarkResult:
    marks_files_count_median: int = 1
    anomaly_count: int = 0


@dataclass
class RunResult:
    run_id: int
    seed: int = 0
    start_time: float = 0.0
    duration_s: float = 0.0
    multi_csv_hash: str = ""
    prev_shadow_hash: str = ""
    current_hash: str = ""
    riftlens: List[RiftLensResult] = field(default_factory=list)
    nulltrace: NullTraceResult = field(default_factory=NullTraceResult)
    voidmark: VoidMarkResult = field(default_factory=VoidMarkResult)
    gad_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AnalyzerProtocol(Protocol):
    def analyze(
        self, run_id: int, seed: int, data: Any, output_dir: Path
    ) -> Dict[str, Any]: ...


def perf_timer(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        duration = time.perf_counter() - start
        logger.info(f"{func.__name__} took {duration:.4f}s")
        return result

    return wrapper


def memory_tracked(func):
    if memory_profiler is None:
        return func
    return memory_profiler.profile(func)


def compute_sha256(path: Path) -> str:
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _guess_graph_format(path: str) -> str:
    suffix = Path(path).suffix.lower().lstrip(".")
    if suffix in {"graphml"}:
        return "graphml"
    if suffix in {"gml"}:
        return "gml"
    if suffix in {"gpickle", "pkl"}:
        return "gpickle"
    if suffix in {"edgelist", "txt"}:
        return "edgelist"
    if suffix in {"csv"}:
        return "csv"
    if suffix in {"json"}:
        return "json"
    return "edgelist"


def load_graph(path: str, fmt: Optional[str] = None) -> "nx.Graph":
    """Load a graph from common interchange formats.

    Supported formats:
    - graphml: NetworkX read_graphml
    - gml: NetworkX read_gml
    - gpickle: NetworkX read_gpickle
    - edgelist: whitespace-separated or tab-separated pairs
    - csv: edge list CSV (auto-detect src/dst column names, else first 2 columns)
    - json: {"nodes":[...], "edges":[{"source":..,"target":..}, ...]} or {"edges":[[u,v],...]}
    """
    if nx is None:
        raise RuntimeError("networkx n'est pas installé.")
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))

    f = (fmt or _guess_graph_format(path)).lower().strip()

    if f == "graphml":
        return nx.read_graphml(p)
    if f == "gml":
        return nx.read_gml(p)
    if f == "gpickle":
        return nx.read_gpickle(p)
    if f == "edgelist":
        return nx.read_edgelist(p, nodetype=str, data=False)
    if f == "csv":
        df = pd.read_csv(p)
        cols = [c.lower().strip() for c in df.columns]

        def pick(*names: str) -> Optional[str]:
            for n in names:
                if n in cols:
                    return str(df.columns[cols.index(n)])
            return None

        c_src = pick("source", "src", "start", "from", "u")
        c_dst = pick("target", "dst", "end", "to", "v")
        if c_src is None or c_dst is None:
            # fallback: first two columns
            if len(df.columns) < 2:
                raise ValueError("CSV edge list needs at least 2 columns.")
            c_src, c_dst = df.columns[0], df.columns[1]
        g = nx.Graph()
        g.add_edges_from(
            zip(df[c_src].astype(str), df[c_dst].astype(str), strict=False)
        )
        return g
    if f == "json":
        obj = json.loads(p.read_text(encoding="utf-8"))
        edges = obj.get("edges", obj.get("Links", obj.get("links", [])))
        g = nx.Graph()
        if isinstance(edges, list) and edges:
            if isinstance(edges[0], dict):
                for e in edges:
                    s = str(e.get("source", e.get("src", e.get("u"))))
                    t = str(e.get("target", e.get("dst", e.get("v"))))
                    if s is None or t is None:
                        continue
                    g.add_edge(s, t)
            else:
                for e in edges:
                    if isinstance(e, (list, tuple)) and len(e) >= 2:
                        g.add_edge(str(e[0]), str(e[1]))
        # Optional node list is ignored except to preserve isolated nodes
        nodes = obj.get("nodes", obj.get("Nodes", obj.get("nodes_list", [])))
        if isinstance(nodes, list):
            for n in nodes:
                if isinstance(n, dict):
                    nid = n.get("id", n.get("name"))
                    if nid is not None:
                        g.add_node(str(nid))
                else:
                    g.add_node(str(n))
        return g

    raise ValueError(f"Unsupported graph format: {f}")


def collect_env_info() -> Dict[str, Any]:
    """Collect minimal, reproducible environment info for audit."""
    import platform
    import subprocess

    info: Dict[str, Any] = {
        "python": sys.version,
        "platform": platform.platform(),
        "generated_utc": datetime.datetime.utcnow().isoformat() + "Z",
        "git_sha": os.environ.get("GITHUB_SHA", ""),
    }

    try:
        out = subprocess.check_output(
            [sys.executable, "-m", "pip", "freeze"], text=True, timeout=30
        )
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        info["pip_freeze_top200"] = lines[:200]
        info["pip_freeze_count"] = len(lines)
    except Exception as e:  # pragma: no cover
        info["pip_freeze_error"] = repr(e)

    return info


def flatten_run_summary(r: "RunResult") -> Dict[str, Any]:
    """Flat, analysis-friendly per-run summary row."""
    rift = r.riftlens or []
    min_j = min((float(x.jaccard) for x in rift), default=1.0)
    n_edges_avg = float(np.mean([x.n_edges for x in rift])) if rift else 0.0
    any_flag = any(bool(x.anomaly_flag) for x in rift)
    silent_nodes_max = max((int(x.silent_nodes) for x in rift), default=0)

    return {
        "run_id": int(r.run_id),
        "seed": int(r.seed),
        "duration_s": float(r.duration_s),
        "gad_score": float(r.gad_score),
        "rift_min_jaccard": float(min_j),
        "rift_n_edges_avg": float(n_edges_avg),
        "rift_anomaly_any": bool(any_flag),
        "rift_silent_nodes_max": int(silent_nodes_max),
        "null_abs_p50": float(r.nulltrace.abs_p50),
        "null_abs_p90": float(r.nulltrace.abs_p90),
        "null_abs_p99": float(r.nulltrace.abs_p99),
        "null_abs_mad": float(r.nulltrace.abs_mad),
        "null_abs_max": float(r.nulltrace.abs_max),
        "null_denoised_mean": float(r.nulltrace.denoised_mean),
        "null_graph_missing_edge_ratio": float(
            getattr(r.nulltrace, "graph_missing_edge_ratio", 0.0)
        ),
        "null_graph_isolated_ratio": float(
            getattr(r.nulltrace, "graph_isolated_ratio", 0.0)
        ),
        "void_marks_files_count_median": int(r.voidmark.marks_files_count_median),
        "void_anomaly_count": int(r.voidmark.anomaly_count),
    }


def _clip01(x: float) -> float:
    return float(max(0.0, min(1.0, x)))


def _sigmoid(x: float) -> float:
    # Numerically stable sigmoid for typical ranges.
    if x >= 60.0:
        return 1.0
    if x <= -60.0:
        return 0.0
    return float(1.0 / (1.0 + math.exp(-x)))


def _log10_sigmoid(x: float, center: float, scale: float, eps: float = 1e-12) -> float:
    # Map positive values to [0, 1] using a sigmoid of log10(x).
    # center: log10 value where output is 0.5. Example: center=-2.0 targets x≈1e-2.
    # scale: controls steepness. Smaller => sharper transition.
    lx = math.log10(max(0.0, float(x)) + eps)
    z = (lx - float(center)) / float(scale)
    return _sigmoid(z)


def compute_anomaly_score(
    rift_by_thr: Dict[float, Dict[str, Any]],
    nulltrace: Dict[str, Any],
    voidmark: Dict[str, Any],
    score_weights: Tuple[float, float, float] = (0.4, 0.4, 0.2),
) -> float:
    w_jaccard, w_p99, w_void = score_weights

    jaccards = [float(v.get("jaccard", 1.0)) for v in rift_by_thr.values()]
    flags = [bool(v.get("anomaly_flag", False)) for v in rift_by_thr.values()]
    min_j = min(jaccards) if jaccards else 1.0
    flag_bonus = 0.25 if any(flags) else 0.0
    graph_component = _clip01((1.0 - min_j) + flag_bonus)

    p99 = float(nulltrace.get("abs_p99", 0.0))
    mad = float(nulltrace.get("abs_mad", 0.0))

    # NullTrace scaling: keep it discriminant in the typical synthetic range.
    # We map log10(p99) around 1e-2 to ~0.5 with a smooth transition.
    p99_component = _log10_sigmoid(p99, center=-2.0, scale=0.35)
    mad_component = _log10_sigmoid(mad, center=-2.5, scale=0.35)
    null_component = _clip01(0.7 * p99_component + 0.3 * mad_component)

    void_count = float(voidmark.get("anomaly_count", 0.0))
    void_component = _clip01(void_count / 5.0)

    score = (
        (w_jaccard * graph_component)
        + (w_p99 * null_component)
        + (w_void * void_component)
    )
    return float(_clip01(score))


class RiftLensAnalyzer(AnalyzerProtocol):
    def __init__(
        self,
        thresholds: List[float],
        graph_path: Optional[str] = None,
        graph_format: Optional[str] = None,
        export_graphs: bool = False,
    ):
        self.thresholds = thresholds
        self.graph_path = graph_path
        self.graph_format = graph_format
        self.export_graphs = bool(export_graphs)

    def _load_base(self) -> Optional["nx.Graph"]:
        if not self.graph_path:
            return None
        return load_graph(self.graph_path, fmt=self.graph_format)

    def _sample_subgraph(
        self, base_g: "nx.Graph", thr: float, seed: int, run_id: int
    ) -> Tuple["nx.Graph", int, float]:
        """Sample a subgraph and optionally inject a deterministic null-trace anomaly.

        Returns: (sampled_graph, silent_nodes, edge_keep_ratio)
        """
        rng = np.random.default_rng(seed + int(run_id) * 100_000 + int(thr * 10_000))
        edges = list(base_g.edges())
        keep_mask = rng.random(len(edges)) < float(thr)
        kept_edges = [e for e, k in zip(edges, keep_mask, strict=False) if k]

        g = nx.Graph()
        g.add_nodes_from(base_g.nodes(data=True))
        g.add_edges_from(kept_edges)

        # Deterministic anomaly injection for synthetic evaluation:
        # remove all edges incident to a small set of nodes, creating "silent" nodes.
        if run_id % 5 == 0 and thr >= 0.5 and g.number_of_nodes() > 0:
            k = max(1, int(0.1 * g.number_of_nodes()))
            bad_nodes = list(g.nodes())[:k]
            g.remove_edges_from(list(g.edges(bad_nodes)))

        base_edges = max(1, base_g.number_of_edges())
        edge_keep_ratio = float(g.number_of_edges()) / float(base_edges)
        silent_nodes = sum(1 for _, deg in g.degree() if deg == 0)
        return g, int(silent_nodes), float(edge_keep_ratio)

    @perf_timer
    def analyze(
        self, run_id: int, seed: int, data: Any, output_dir: Path
    ) -> Dict[str, Any]:
        if nx is None:
            raise RuntimeError("networkx n'est pas installé.")

        base_g = self._load_base()

        results: List[RiftLensResult] = []
        for thr in self.thresholds:
            thr = float(thr)

            if base_g is None:
                rng = np.random.default_rng(
                    seed + int(run_id) * 100_000 + int(thr * 10_000)
                )
                g = nx.erdos_renyi_graph(
                    n=10 + run_id % 5,
                    p=0.2 + thr / 2,
                    seed=int(rng.integers(0, 2**32 - 1)),
                )
                n_nodes = int(g.number_of_nodes())
                n_edges = int(g.number_of_edges())
                jaccard = float(rng.uniform(0.9, 1.0)) if run_id % 3 == 0 else 1.0
                silent_nodes = int(sum(1 for _, deg in g.degree() if deg == 0))
                base_edges = int(n_edges)
                edge_keep_ratio = 1.0 if base_edges else 0.0
                anomaly_flag = bool(n_edges < 1 or jaccard < 0.95 or silent_nodes > 0)
                sampled = g
            else:
                sampled, silent_nodes, edge_keep_ratio = self._sample_subgraph(
                    base_g, thr, seed, run_id
                )
                n_nodes = int(sampled.number_of_nodes())
                n_edges = int(sampled.number_of_edges())
                base_edges = int(base_g.number_of_edges())
                # Since sampled is (mostly) a subset of base edges, jaccard reduces
                # to the edge keep ratio.
                jaccard = float(edge_keep_ratio)
                anomaly_flag = bool(
                    (edge_keep_ratio < thr * 0.75) or (silent_nodes > 0)
                )

            report_path = output_dir / f"reports/thr_{thr:.2f}/graph_report.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)

            report_payload = {
                "run_id": int(run_id),
                "seed": int(seed),
                "threshold": float(thr),
                "n_nodes": int(n_nodes),
                "n_edges": int(n_edges),
                "base_edges": int(base_edges),
                "edge_keep_ratio": float(edge_keep_ratio),
                "jaccard": float(jaccard),
                "silent_nodes": int(silent_nodes),
                "anomaly_flag": bool(anomaly_flag),
            }

            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report_payload, f, indent=2)

            if self.export_graphs:
                # Export graph for external tools (Gephi friendly)
                gml_path = report_path.with_name("graph.gml")
                graphml_path = report_path.with_name("graph.graphml")
                try:
                    nx.write_gml(sampled, gml_path)
                except Exception:  # pragma: no cover
                    pass
                try:
                    nx.write_graphml(sampled, graphml_path)
                except Exception:  # pragma: no cover
                    pass

            results.append(
                RiftLensResult(
                    threshold=float(thr),
                    n_nodes=int(n_nodes),
                    n_edges=int(n_edges),
                    base_edges=int(base_edges),
                    edge_keep_ratio=float(edge_keep_ratio),
                    jaccard=float(jaccard),
                    silent_nodes=int(silent_nodes),
                    anomaly_flag=bool(anomaly_flag),
                    path_report=str(report_path.relative_to(output_dir)),
                    path_tmp="",
                )
            )

        return {"riftlens": results}


class NullTraceAnalyzer(AnalyzerProtocol):
    def __init__(
        self,
        thresholds: Optional[List[float]] = None,
        graph_path: Optional[str] = None,
        graph_format: Optional[str] = None,
        use_ml: bool = False,
    ):
        self.thresholds = thresholds or [0.25, 0.5, 0.7, 0.8]
        self.graph_path = graph_path
        self.graph_format = graph_format

        self.use_ml = bool(use_ml)
        self.model = None
        self.optimizer = None
        self.criterion = None

        if self.use_ml:
            if torch is None or DenoisingAutoencoder is None:
                raise RuntimeError("torch n'est pas installé.")
            self.model = DenoisingAutoencoder()
            self.optimizer = torch.optim.Adam(self.model.parameters(), lr=0.01)
            self.criterion = cast(_Any, nn).MSELoss()

    def _graph_null_deltas(
        self, run_id: int, seed: int
    ) -> Tuple[np.ndarray, float, float]:
        if not self.graph_path:
            raise RuntimeError("graph_path is not set")
        if nx is None:
            raise RuntimeError("networkx n'est pas installé.")

        base_g = load_graph(self.graph_path, fmt=self.graph_format)
        base_edges = max(1, int(base_g.number_of_edges()))
        base_nodes = max(1, int(base_g.number_of_nodes()))

        deltas: List[float] = []
        silent_total = 0

        for thr in self.thresholds:
            thr = float(thr)
            # Use the exact same deterministic sampling as RiftLensAnalyzer
            rng = np.random.default_rng(
                seed + int(run_id) * 100_000 + int(thr * 10_000)
            )
            edges = list(base_g.edges())
            keep_mask = rng.random(len(edges)) < thr
            kept_edges = [e for e, k in zip(edges, keep_mask, strict=False) if k]

            g = nx.Graph()
            g.add_nodes_from(base_g.nodes(data=True))
            g.add_edges_from(kept_edges)

            if run_id % 5 == 0 and thr >= 0.5 and g.number_of_nodes() > 0:
                k = max(1, int(0.1 * g.number_of_nodes()))
                bad_nodes = list(g.nodes())[:k]
                g.remove_edges_from(list(g.edges(bad_nodes)))

            silent_nodes = sum(1 for _, deg in g.degree() if deg == 0)
            silent_total += int(silent_nodes)

            expected = thr * float(base_edges)
            deficit = max(
                0.0, (expected - float(g.number_of_edges())) / float(base_edges)
            )
            # Expand into a small cloud to make robust percentiles/MAD meaningful.
            noise = rng.normal(0.0, max(1e-8, deficit * 0.05), size=12)
            for v in deficit + np.abs(noise):
                deltas.append(float(abs(v)))

        arr = np.asarray(deltas, dtype=float)
        # Ensure a fixed length (50) for the optional ML denoiser.
        if arr.size < 50:
            pad = np.zeros(50 - arr.size, dtype=float)
            arr = np.concatenate([arr, pad])
        else:
            arr = arr[:50]

        missing_edge_ratio = float(np.median(arr)) if arr.size else 0.0
        isolated_ratio = float(silent_total) / float(len(self.thresholds) * base_nodes)
        return arr, missing_edge_ratio, isolated_ratio

    @perf_timer
    def analyze(
        self, run_id: int, seed: int, data: Any, output_dir: Path
    ) -> Dict[str, Any]:
        np.random.seed(seed)

        graph_missing_edge_ratio = 0.0
        graph_isolated_ratio = 0.0

        if self.graph_path:
            abs_deltas, graph_missing_edge_ratio, graph_isolated_ratio = (
                self._graph_null_deltas(run_id, seed)
            )
        else:
            # Legacy synthetic null-trace deltas
            deltas = np.random.lognormal(mean=-8, sigma=1.5, size=50)
            abs_deltas = np.abs(deltas)

        denoised_mean = 0.0
        if self.use_ml:
            assert torch is not None
            assert self.model is not None
            assert self.optimizer is not None
            assert self.criterion is not None
            data_tensor = torch.tensor(abs_deltas, dtype=torch.float32).unsqueeze(0)
            noise = torch.randn_like(data_tensor) * 0.1
            noisy = data_tensor + noise

            for _ in range(10):
                output = self.model(noisy)
                loss = self.criterion(output, data_tensor)
                self.optimizer.zero_grad()
                loss.backward()
                self.optimizer.step()

            denoised = self.model(noisy).detach().numpy().squeeze()
            denoised_mean = float(np.mean(denoised))

        abs_deltas = np.asarray(abs_deltas, dtype=float)
        return {
            "nulltrace": NullTraceResult(
                n_deltas=int(len(abs_deltas)),
                abs_p50=float(np.percentile(abs_deltas, 50)),
                abs_p90=float(np.percentile(abs_deltas, 90)),
                abs_p99=float(np.percentile(abs_deltas, 99)),
                abs_mad=float(np.median(np.abs(abs_deltas - np.median(abs_deltas)))),
                abs_max=float(np.max(abs_deltas)),
                denoised_mean=float(denoised_mean),
                graph_missing_edge_ratio=float(graph_missing_edge_ratio),
                graph_isolated_ratio=float(graph_isolated_ratio),
            )
        }


class VoidMarkAnalyzer(AnalyzerProtocol):
    @perf_timer
    def analyze(
        self, run_id: int, seed: int, data: Any, output_dir: Path
    ) -> Dict[str, Any]:
        np.random.seed(seed)
        count = int(np.random.randint(1, 5))
        anomaly_count = int(count if count > 2 else 0)
        return {
            "voidmark": VoidMarkResult(
                marks_files_count_median=count, anomaly_count=anomaly_count
            )
        }


def process_run_worker(run_id: int, params: Dict[str, Any]) -> RunResult:
    thresholds = [float(x) for x in params["thresholds"]]
    enable_ml = bool(params.get("enable_ml", False))
    score_weights = tuple(params.get("score_weights", (0.4, 0.4, 0.2)))
    output_base = Path(params["output_base"])
    ensure_file_logging(output_base / "echonull.log")

    seed = int(params["seed_base"]) + int(run_id)
    np.random.seed(seed)
    start = time.time()

    run_dir = output_base / f"run_{run_id:04d}"
    run_dir.mkdir(parents=True, exist_ok=True)

    multi_path = run_dir / "multi.csv"
    prev_path = run_dir / "previous_shadow.csv"
    curr_path = run_dir / "current.csv"

    data = np.random.randn(100, 5)
    pd.DataFrame(data).to_csv(multi_path, index=False)
    pd.DataFrame(data * 0.9).to_csv(prev_path, index=False)
    pd.DataFrame(data * 1.1).to_csv(curr_path, index=False)

    multi_hash = compute_sha256(multi_path)
    prev_hash = compute_sha256(prev_path)
    curr_hash = compute_sha256(curr_path)

    graph_path = params.get("graph") or params.get("graph_path")
    graph_format = params.get("graph_format")
    export_graphs = bool(params.get("export_graphs", False))

    rift_analyzer = RiftLensAnalyzer(
        thresholds,
        graph_path=graph_path,
        graph_format=graph_format,
        export_graphs=export_graphs,
    )
    null_analyzer = NullTraceAnalyzer(
        thresholds=thresholds,
        graph_path=graph_path,
        graph_format=graph_format,
        use_ml=enable_ml,
    )
    void_analyzer = VoidMarkAnalyzer()

    rift_results: List[RiftLensResult] = rift_analyzer.analyze(
        run_id, seed, data, run_dir
    )["riftlens"]
    null_result: NullTraceResult = null_analyzer.analyze(run_id, seed, data, run_dir)[
        "nulltrace"
    ]
    void_result: VoidMarkResult = void_analyzer.analyze(run_id, seed, data, run_dir)[
        "voidmark"
    ]

    gad_score = compute_anomaly_score(
        {r.threshold: r.__dict__ for r in rift_results},
        null_result.__dict__,
        void_result.__dict__,
        score_weights=score_weights,
    )

    duration = time.time() - start

    return RunResult(
        run_id=int(run_id),
        seed=int(seed),
        start_time=float(start),
        duration_s=float(duration),
        multi_csv_hash=str(multi_hash),
        prev_shadow_hash=str(prev_hash),
        current_hash=str(curr_hash),
        riftlens=rift_results,
        nulltrace=null_result,
        voidmark=void_result,
        gad_score=float(gad_score),
    )


class EchoNullOrchestrator:
    def __init__(self, params: Dict[str, Any]):
        self.params = params
        self.output_base: Path = Path(self.params["output_base"])
        ensure_file_logging(self.output_base / "echonull.log")

    @perf_timer
    def run_sweep(self) -> List[RunResult]:
        runs = int(self.params["runs"])
        workers = int(self.params["workers"])

        logger.info(
            f"EchoNull Sweep | runs={runs} | workers={workers} | "
            f"ML={self.params.get('enable_ml')} | "
            f"Viz={self.params.get('enable_viz')} | "
            f"Dask={self.params.get('use_dask')}"
        )

        self.output_base.mkdir(parents=True, exist_ok=True)

        if self.params.get("use_dask", False):
            if LocalCluster is None or Client is None:
                raise RuntimeError("dask[distributed] n'est pas installé.")
            with LocalCluster(n_workers=workers, threads_per_worker=1) as cluster:
                with Client(cluster) as client:
                    futures = [
                        client.submit(process_run_worker, i, self.params)
                        for i in range(1, runs + 1)
                    ]
                    results = client.gather(futures)
        else:
            with ProcessPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(process_run_worker, i, self.params)
                    for i in range(1, runs + 1)
                ]
                if tqdm is None:
                    results = [f.result() for f in as_completed(futures)]
                else:
                    results = [
                        f.result()
                        for f in tqdm(as_completed(futures), total=runs, desc="Runs")
                    ]

        return sorted(results, key=lambda r: r.run_id)

    def generate_overview(self, results: List[RunResult]) -> Dict[str, Any]:
        gad_scores = [float(r.gad_score) for r in results] or [0.0]
        overview = {
            "tool": "EchoNull",
            "version": VERSION,
            "generated_utc": datetime.datetime.utcnow().isoformat() + "Z",
            "runs_found": int(len(results)),
            "gad_score_stats": {
                "min": float(min(gad_scores)),
                "p50": float(np.median(gad_scores)),
                "mean": float(np.mean(gad_scores)),
                "p95": float(np.percentile(gad_scores, 95)),
                "max": float(max(gad_scores)),
            },
            "params": {
                "runs": int(self.params["runs"]),
                "thresholds": list(self.params["thresholds"]),
                "seed_base": int(self.params["seed_base"]),
                "workers": int(self.params["workers"]),
                "use_dask": bool(self.params.get("use_dask", False)),
                "enable_ml": bool(self.params.get("enable_ml", False)),
                "enable_viz": bool(self.params.get("enable_viz", False)),
                "score_weights": list(
                    self.params.get("score_weights", (0.4, 0.4, 0.2))
                ),
            },
        }
        return overview

    def generate_viz(self, results: List[RunResult]) -> Optional[Path]:
        if not self.params.get("enable_viz", False):
            return None
        if plt is None:
            raise RuntimeError("matplotlib n'est pas installé.")

        gad_scores = [r.gad_score for r in results]
        p99_deltas = [r.nulltrace.abs_p99 for r in results]
        n_edges_avg = [
            float(np.mean([rl.n_edges for rl in r.riftlens])) for r in results
        ]

        fig, axs = plt.subplots(1, 2, figsize=(12, 5))
        axs[0].hist(gad_scores, bins=20, color="cyan", label="GAD Scores")
        axs[0].set_title("Distribution GAD Anomaly Scores")
        axs[1].scatter(p99_deltas, n_edges_avg, c=gad_scores, cmap="viridis")
        axs[1].set_xlabel("p99 Delta")
        axs[1].set_ylabel("Avg n_edges")
        axs[1].set_title("Scatter p99 vs Edges (colored by GAD score)")

        viz_path = self.output_base / "viz_overview.png"
        plt.savefig(viz_path)
        plt.close()
        logger.info(f"Viz generated: {viz_path}")
        return viz_path

    def save_artifacts(
        self, results: List[RunResult], overview: Dict[str, Any]
    ) -> Dict[str, Path]:
        self.output_base.mkdir(parents=True, exist_ok=True)

        overview_path = self.output_base / "overview.json"
        with open(overview_path, "w", encoding="utf-8") as f:
            json.dump(overview, f, indent=2)

        env_path = self.output_base / "env.json"
        with open(env_path, "w", encoding="utf-8") as f:
            json.dump(collect_env_info(), f, indent=2)

        # Flat, analysis-friendly summary
        run_summary_path = self.output_base / "run_summary.csv"
        df_flat = pd.DataFrame([flatten_run_summary(r) for r in results])
        df_flat.to_csv(run_summary_path, index=False)

        # Per-module CSVs (normalized)
        rift_path = self.output_base / "riftlens_by_threshold.csv"
        rift_rows: List[Dict[str, Any]] = []
        for r in results:
            for rr in r.riftlens:
                rift_rows.append(
                    {
                        "run_id": int(r.run_id),
                        "seed": int(r.seed),
                        "threshold": float(rr.threshold),
                        "n_nodes": int(rr.n_nodes),
                        "n_edges": int(rr.n_edges),
                        "base_edges": int(rr.base_edges),
                        "edge_keep_ratio": float(rr.edge_keep_ratio),
                        "jaccard": float(rr.jaccard),
                        "silent_nodes": int(rr.silent_nodes),
                        "anomaly_flag": bool(rr.anomaly_flag),
                        "path_report": str(rr.path_report),
                    }
                )
        pd.DataFrame(rift_rows).to_csv(rift_path, index=False)

        null_path = self.output_base / "nulltrace.csv"
        null_rows = []
        for r in results:
            n = r.nulltrace
            null_rows.append(
                {
                    "run_id": int(r.run_id),
                    "seed": int(r.seed),
                    "n_deltas": int(n.n_deltas),
                    "abs_p50": float(n.abs_p50),
                    "abs_p90": float(n.abs_p90),
                    "abs_p99": float(n.abs_p99),
                    "abs_mad": float(n.abs_mad),
                    "abs_max": float(n.abs_max),
                    "denoised_mean": float(n.denoised_mean),
                    "graph_missing_edge_ratio": float(
                        getattr(n, "graph_missing_edge_ratio", 0.0)
                    ),
                    "graph_isolated_ratio": float(
                        getattr(n, "graph_isolated_ratio", 0.0)
                    ),
                }
            )
        pd.DataFrame(null_rows).to_csv(null_path, index=False)

        void_path = self.output_base / "voidmark.csv"
        void_rows = []
        for r in results:
            v = r.voidmark
            void_rows.append(
                {
                    "run_id": int(r.run_id),
                    "seed": int(r.seed),
                    "marks_files_count_median": int(v.marks_files_count_median),
                    "anomaly_count": int(v.anomaly_count),
                }
            )
        pd.DataFrame(void_rows).to_csv(void_path, index=False)

        # Detailed per-run payload in JSONL (useful for very large sweeps)
        runs_jsonl_path = self.output_base / "runs.jsonl"
        with open(runs_jsonl_path, "w", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")

        zip_path = self.output_base.with_suffix(".zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_LZMA) as zf:
            for file in self.output_base.rglob("*"):
                if file.is_file():
                    zf.write(file, file.relative_to(self.output_base.parent))

        logger.info(f"Artefacts saved: {zip_path}")
        return {
            "overview": overview_path,
            "env": env_path,
            "run_summary": run_summary_path,
            "riftlens_by_threshold": rift_path,
            "nulltrace": null_path,
            "voidmark": void_path,
            "runs_jsonl": runs_jsonl_path,
            "zip": zip_path,
        }


def build_manifest(
    results: List[RunResult],
    overview: Dict[str, Any],
    output_base: Path,
    artifact_paths: Dict[str, Path],
    viz_path: Optional[Path],
    max_detailed_runs: int = 200,
) -> Dict[str, Any]:
    zip_sha = compute_sha256(artifact_paths["zip"]) if artifact_paths.get("zip") else ""
    overview_sha = (
        compute_sha256(artifact_paths["overview"])
        if artifact_paths.get("overview")
        else ""
    )
    run_summary_sha = (
        compute_sha256(artifact_paths["run_summary"])
        if artifact_paths.get("run_summary")
        else ""
    )
    env_sha = compute_sha256(artifact_paths["env"]) if artifact_paths.get("env") else ""
    rift_sha = (
        compute_sha256(artifact_paths["riftlens_by_threshold"])
        if artifact_paths.get("riftlens_by_threshold")
        else ""
    )
    null_sha = (
        compute_sha256(artifact_paths["nulltrace"])
        if artifact_paths.get("nulltrace")
        else ""
    )
    void_sha = (
        compute_sha256(artifact_paths["voidmark"])
        if artifact_paths.get("voidmark")
        else ""
    )
    runs_jsonl_sha = (
        compute_sha256(artifact_paths["runs_jsonl"])
        if artifact_paths.get("runs_jsonl")
        else ""
    )
    viz_sha = compute_sha256(viz_path) if viz_path and viz_path.exists() else ""

    runs_manifest: List[Dict[str, Any]] = []
    if len(results) <= int(max_detailed_runs):
        for r in results:
            runs_manifest.append(
                {
                    "run_id": r.run_id,
                    "seed": r.seed,
                    "duration_s": r.duration_s,
                    "multi_csv_hash": r.multi_csv_hash,
                    "prev_shadow_hash": r.prev_shadow_hash,
                    "current_hash": r.current_hash,
                    "gad_score": r.gad_score,
                    "riftlens_flags": {
                        str(x.threshold): bool(x.anomaly_flag) for x in r.riftlens
                    },
                    "nulltrace_p99": r.nulltrace.abs_p99,
                    "voidmark_anomaly_count": r.voidmark.anomaly_count,
                }
            )

    manifest = {
        "manifest_version": 1,
        "tool": "EchoNull",
        "version": VERSION,
        "generated_utc": datetime.datetime.utcnow().isoformat() + "Z",
        "output_base": str(output_base),
        "overview": {
            "path": str(artifact_paths.get("overview", "")),
            "sha256": overview_sha,
        },
        "env": {"path": str(artifact_paths.get("env", "")), "sha256": env_sha},
        "run_summary": {
            "path": str(artifact_paths.get("run_summary", "")),
            "sha256": run_summary_sha,
        },
        "riftlens_by_threshold": {
            "path": str(artifact_paths.get("riftlens_by_threshold", "")),
            "sha256": rift_sha,
        },
        "nulltrace": {
            "path": str(artifact_paths.get("nulltrace", "")),
            "sha256": null_sha,
        },
        "voidmark": {
            "path": str(artifact_paths.get("voidmark", "")),
            "sha256": void_sha,
        },
        "runs_jsonl": {
            "path": str(artifact_paths.get("runs_jsonl", "")),
            "sha256": runs_jsonl_sha,
        },
        "zip": {"path": str(artifact_paths.get("zip", "")), "sha256": zip_sha},
        "viz_overview": {"path": str(viz_path) if viz_path else "", "sha256": viz_sha},
        "overview_payload": overview,
        # Detailed per-run payload is included only for small sweeps.
        "runs": runs_manifest,
        "runs_in_manifest": bool(len(runs_manifest) > 0),
        "max_detailed_runs": int(max_detailed_runs),
    }
    return manifest


def write_manifest(manifest: Dict[str, Any], output_base: Path) -> None:
    output_manifest = output_base / "manifest.json"
    with open(output_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    root_manifest = Path("manifest.json")
    with open(root_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    logger.info(f"Manifest written: {output_manifest} and {root_manifest}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="EchoNull - Graph & Null-Trace Anomaly Detection Framework"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    sweep = subparsers.add_parser("sweep", help="Run massive parameter sweep")
    sweep.add_argument("--runs", type=int, default=100)
    sweep.add_argument("--thresholds", type=str, default="0.25,0.5,0.7,0.8")
    sweep.add_argument("--seed-base", type=int, default=42)
    sweep.add_argument("--workers", type=int, default=8)
    sweep.add_argument("--use-dask", action="store_true")
    sweep.add_argument("--enable-ml", action="store_true")
    sweep.add_argument("--enable-viz", action="store_true")
    sweep.add_argument("--score-weights", type=str, default="0.4,0.4,0.2")
    sweep.add_argument("--output-base", type=str, default="")
    sweep.add_argument("--graph", type=str, default="")
    sweep.add_argument("--graph-format", type=str, default="")
    sweep.add_argument("--export-graphs", action="store_true")
    sweep.add_argument("--manifest-max-detailed-runs", type=int, default=200)

    gad = subparsers.add_parser("gad", help="Run GAD-focused sweep")
    gad.add_argument("--runs", type=int, default=100)
    gad.add_argument("--thresholds", type=str, default="0.25,0.5,0.7,0.8")
    gad.add_argument("--seed-base", type=int, default=42)
    gad.add_argument("--workers", type=int, default=8)
    gad.add_argument("--use-dask", action="store_true")
    gad.add_argument("--enable-ml", action="store_true")
    gad.add_argument("--enable-viz", action="store_true")
    gad.add_argument("--score-weights", type=str, default="0.4,0.4,0.2")
    gad.add_argument("--output-base", type=str, default="")
    gad.add_argument("--graph", type=str, default="")
    gad.add_argument("--graph-format", type=str, default="")
    gad.add_argument("--export-graphs", action="store_true")
    gad.add_argument("--manifest-max-detailed-runs", type=int, default=200)

    subparsers.add_parser("test", help="Run unit tests")
    subparsers.add_parser("bench", help="Run performance benchmarks")

    return parser.parse_args()


def main():
    args = parse_args()
    thresholds = [
        float(t.strip())
        for t in getattr(args, "thresholds", "0.25,0.5,0.7,0.8").split(",")
        if t.strip()
    ]
    score_weights = tuple(
        float(w.strip())
        for w in getattr(args, "score_weights", "0.4,0.4,0.2").split(",")
    )

    output_base_arg = str(getattr(args, "output_base", "") or "").strip()
    if output_base_arg:
        output_base = Path(output_base_arg)
    else:
        output_base = (
            BASE_OUTPUT_DIR / f"{getattr(args, 'command', 'sweep')}_{TIMESTAMP}"
        )

    params: Dict[str, Any] = {
        "runs": int(getattr(args, "runs", 100)),
        "thresholds": thresholds,
        "seed_base": int(getattr(args, "seed_base", 42)),
        "workers": int(getattr(args, "workers", 8)),
        "output_base": str(output_base),
        "graph": str(getattr(args, "graph", "") or "").strip() or None,
        "graph_format": str(getattr(args, "graph_format", "") or "").strip() or None,
        "export_graphs": bool(getattr(args, "export_graphs", False)),
        "manifest_max_detailed_runs": int(
            getattr(args, "manifest_max_detailed_runs", 200)
        ),
        "use_dask": bool(getattr(args, "use_dask", False)),
        "enable_ml": bool(getattr(args, "enable_ml", False)),
        "enable_viz": bool(getattr(args, "enable_viz", False)),
        "score_weights": score_weights,
    }

    if args.command in ("sweep", "gad"):
        orchestrator = EchoNullOrchestrator(params)
        results = orchestrator.run_sweep()
        overview = orchestrator.generate_overview(results)
        viz_path = (
            orchestrator.generate_viz(results)
            if params.get("enable_viz", False)
            else None
        )
        artifact_paths = orchestrator.save_artifacts(results, overview)

        manifest = build_manifest(
            results=results,
            overview=overview,
            output_base=Path(params["output_base"]),
            artifact_paths=artifact_paths,
            viz_path=viz_path,
            max_detailed_runs=int(params.get("manifest_max_detailed_runs", 200)),
        )
        write_manifest(manifest, Path(params["output_base"]))

    elif args.command == "test":

        class TestEchoNull(unittest.TestCase):
            def test_hashing(self):
                path = Path("test.txt")
                path.write_text("test", encoding="utf-8")
                try:
                    self.assertEqual(
                        compute_sha256(path),
                        "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
                    )
                finally:
                    path.unlink()

            def test_score_range(self):
                score = compute_anomaly_score(
                    {0.5: {"jaccard": 1.0, "anomaly_flag": False}},
                    {"abs_p99": 1e-6, "abs_mad": 1e-7},
                    {"anomaly_count": 0},
                )
                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 1.0)

        unittest.main(argv=["ignored", "-v"], exit=False)

    elif args.command == "bench":

        @memory_tracked
        def bench_sweep():
            params2 = dict(params)
            params2["runs"] = 10
            params2["workers"] = min(int(params2["workers"]), 4)
            orchestrator2 = EchoNullOrchestrator(params2)
            orchestrator2.run_sweep()

        bench_sweep()

    logger.info("EchoNull terminé")


if __name__ == "__main__":
    main()
