#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EchoNull - Lightweight CI-native framework for graph and null-trace anomaly detection via massive parameter sweeps.

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
import os
import shutil
import time
import unittest
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, asdict, field
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple

import numpy as np
import pandas as pd

# Optionnels
try:
    import matplotlib.pyplot as plt  # type: ignore
except Exception:  # pragma: no cover
    plt = None

try:
    import torch  # type: ignore
    import torch.nn as nn  # type: ignore
except Exception:  # pragma: no cover
    torch = None
    nn = None

try:
    from tqdm import tqdm  # type: ignore
except Exception:  # pragma: no cover
    tqdm = None

try:
    import networkx as nx  # type: ignore
except Exception:  # pragma: no cover
    nx = None

try:
    from dask.distributed import Client, LocalCluster  # type: ignore
except Exception:  # pragma: no cover
    Client = None
    LocalCluster = None

try:
    import memory_profiler  # type: ignore
except Exception:  # pragma: no cover
    memory_profiler = None


# Torch optional: define the autoencoder class only if torch is available
def _make_denoising_autoencoder():
    if nn is None:
        return None

    class DenoisingAutoencoder(nn.Module):  # type: ignore[misc]
        def __init__(self, input_size: int = 50):
            super().__init__()
            self.encoder = nn.Sequential(nn.Linear(input_size, 32), nn.ReLU(), nn.Linear(32, 16))
            self.decoder = nn.Sequential(nn.Linear(16, 32), nn.ReLU(), nn.Linear(32, input_size))

        def forward(self, x):
            return self.decoder(self.encoder(x))

    return DenoisingAutoencoder


_DENOISING_AUTOENCODER = _make_denoising_autoencoder()

logger = logging.getLogger("EchoNull")
logger.setLevel(logging.INFO)

if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))
    logger.addHandler(console_handler)

    file_handler = logging.FileHandler("echonull.log", mode="a", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))
    logger.addHandler(file_handler)

BASE_OUTPUT_DIR = Path("_echonull_out")
TIMESTAMP = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S")
VERSION = "0.1.0"


@dataclass
class RiftLensResult:
    threshold: float
    n_nodes: int
    n_edges: int
    jaccard: float = 1.0
    path_tmp: str = ""
    path_report: str = ""
    anomaly_flag: bool = False


@dataclass
class NullTraceResult:
    n_deltas: int = 21
    abs_p50: float = 0.0
    abs_p90: float = 0.0
    abs_p99: float = 0.0
    abs_mad: float = 0.0
    abs_max: float = 0.0
    denoised_mean: float = 0.0


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
    def analyze(self, run_id: int, seed: int, data: Any, output_dir: Path) -> Dict[str, Any]:
        ...


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


def _clip01(x: float) -> float:
    return float(max(0.0, min(1.0, x)))


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
    p99_component = _clip01((np.log10(p99 + 1e-12) + 12.0) / 6.0)
    mad_component = _clip01((np.log10(mad + 1e-12) + 12.0) / 6.0)
    null_component = _clip01(0.7 * p99_component + 0.3 * mad_component)

    void_count = float(voidmark.get("anomaly_count", 0.0))
    void_component = _clip01(void_count / 5.0)

    score = (w_jaccard * graph_component) + (w_p99 * null_component) + (w_void * void_component)
    return float(score)


class RiftLensAnalyzer(AnalyzerProtocol):
    def __init__(self, thresholds: List[float]):
        self.thresholds = thresholds

    @perf_timer
    def analyze(self, run_id: int, seed: int, data: Any, output_dir: Path) -> Dict[str, Any]:
        if nx is None:
            raise RuntimeError("networkx n'est pas installé.")
        np.random.seed(seed)

        results: List[RiftLensResult] = []
        for thr in self.thresholds:
            g = nx.erdos_renyi_graph(n=10 + run_id % 5, p=0.2 + thr / 2)
            n_nodes = g.number_of_nodes()
            n_edges = g.number_of_edges()
            jaccard = float(np.random.uniform(0.9, 1.0)) if run_id % 3 == 0 else 1.0

            tmp_path = output_dir / f"_tmp/thr_{thr:.2f}/graph_report.json"
            report_path = output_dir / f"reports/thr_{thr:.2f}/graph_report.json"
            tmp_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.parent.mkdir(parents=True, exist_ok=True)

            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump({"nodes": int(n_nodes), "edges": int(n_edges)}, f)

            shutil.copy(tmp_path, report_path)

            flag = bool(n_edges < 1 or jaccard < 0.95)

            results.append(
                RiftLensResult(
                    threshold=float(thr),
                    n_nodes=int(n_nodes),
                    n_edges=int(n_edges),
                    jaccard=float(jaccard),
                    path_tmp=str(tmp_path),
                    path_report=str(report_path),
                    anomaly_flag=flag,
                )
            )

        return {"riftlens": results}


class NullTraceAnalyzer(AnalyzerProtocol):
    def __init__(self, input_size: int = 50):
            super().__init__()
            self.encoder = nn.Sequential(nn.Linear(input_size, 32), nn.ReLU(), nn.Linear(32, 16))
            self.decoder = nn.Sequential(nn.Linear(16, 32), nn.ReLU(), nn.Linear(32, input_size))

        def forward(self, x):
            return self.decoder(self.encoder(x))

    def __init__(self, use_ml: bool = False):
        self.use_ml = bool(use_ml)
        self.model = None
        self.optimizer = None
        self.criterion = None

        if self.use_ml:
            if torch is None or nn is None or _DENOISING_AUTOENCODER is None:
                raise RuntimeError("torch n'est pas installé.")
            self.model = _DENOISING_AUTOENCODER()  # type: ignore[operator]
            self.optimizer = torch.optim.Adam(self.model.parameters(), lr=0.01)
            self.criterion = nn.MSELoss()

    @perf_timer
    def analyze(self, run_id: int, seed: int, data: Any, output_dir: Path) -> Dict[str, Any]:
        np.random.seed(seed)
        deltas = np.random.lognormal(mean=-8, sigma=1.5, size=50)
        abs_deltas = np.abs(deltas)

        denoised_mean = 0.0
        if self.use_ml:
            assert torch is not None and self.model is not None and self.optimizer is not None and self.criterion is not None
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

        return {
            "nulltrace": NullTraceResult(
                n_deltas=int(len(abs_deltas)),
                abs_p50=float(np.percentile(abs_deltas, 50)),
                abs_p90=float(np.percentile(abs_deltas, 90)),
                abs_p99=float(np.percentile(abs_deltas, 99)),
                abs_mad=float(np.median(np.abs(abs_deltas - np.median(abs_deltas)))),
                abs_max=float(np.max(abs_deltas)),
                denoised_mean=float(denoised_mean),
            )
        }


class VoidMarkAnalyzer(AnalyzerProtocol):
    @perf_timer
    def analyze(self, run_id: int, seed: int, data: Any, output_dir: Path) -> Dict[str, Any]:
        np.random.seed(seed)
        count = int(np.random.randint(1, 5))
        anomaly_count = int(count if count > 2 else 0)
        return {"voidmark": VoidMarkResult(marks_files_count_median=count, anomaly_count=anomaly_count)}


def process_run_worker(run_id: int, params: Dict[str, Any]) -> RunResult:
    thresholds = [float(x) for x in params["thresholds"]]
    enable_ml = bool(params.get("enable_ml", False))
    score_weights = tuple(params.get("score_weights", (0.4, 0.4, 0.2)))
    output_base = Path(params["output_base"])

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

    rift_analyzer = RiftLensAnalyzer(thresholds)
    null_analyzer = NullTraceAnalyzer(use_ml=enable_ml)
    void_analyzer = VoidMarkAnalyzer()

    rift_results: List[RiftLensResult] = rift_analyzer.analyze(run_id, seed, data, run_dir)["riftlens"]
    null_result: NullTraceResult = null_analyzer.analyze(run_id, seed, data, run_dir)["nulltrace"]
    void_result: VoidMarkResult = void_analyzer.analyze(run_id, seed, data, run_dir)["voidmark"]

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

    @perf_timer
    def run_sweep(self) -> List[RunResult]:
        runs = int(self.params["runs"])
        workers = int(self.params["workers"])

        logger.info(
            f"EchoNull Sweep | runs={runs} | workers={workers} | ML={self.params.get('enable_ml')} | "
            f"Viz={self.params.get('enable_viz')} | Dask={self.params.get('use_dask')}"
        )

        self.output_base.mkdir(parents=True, exist_ok=True)

        if self.params.get("use_dask", False):
            if LocalCluster is None or Client is None:
                raise RuntimeError("dask[distributed] n'est pas installé.")
            with LocalCluster(n_workers=workers, threads_per_worker=1) as cluster:
                with Client(cluster) as client:
                    futures = [client.submit(process_run_worker, i, self.params) for i in range(1, runs + 1)]
                    results = client.gather(futures)
        else:
            with ProcessPoolExecutor(max_workers=workers) as executor:
                futures = [executor.submit(process_run_worker, i, self.params) for i in range(1, runs + 1)]
                if tqdm is None:
                    results = [f.result() for f in as_completed(futures)]
                else:
                    results = [f.result() for f in tqdm(as_completed(futures), total=runs, desc="Runs")]

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
                "score_weights": list(self.params.get("score_weights", (0.4, 0.4, 0.2))),
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
        n_edges_avg = [float(np.mean([rl.n_edges for rl in r.riftlens])) for r in results]

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

    def save_artifacts(self, results: List[RunResult], overview: Dict[str, Any]) -> Dict[str, Path]:
        overview_path = self.output_base / "overview.json"
        with open(overview_path, "w", encoding="utf-8") as f:
            json.dump(overview, f, indent=2)

        df = pd.DataFrame([r.to_dict() for r in results])
        run_summary_path = self.output_base / "run_summary.csv"
        df.to_csv(run_summary_path, index=False)

        zip_path = self.output_base.with_suffix(".zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_LZMA) as zf:
            for file in self.output_base.rglob("*"):
                if file.is_file():
                    zf.write(file, file.relative_to(self.output_base.parent))

        logger.info(f"Artefacts saved: {zip_path}")
        return {"overview": overview_path, "run_summary": run_summary_path, "zip": zip_path}


def build_manifest(
    results: List[RunResult],
    overview: Dict[str, Any],
    output_base: Path,
    artifact_paths: Dict[str, Path],
    viz_path: Optional[Path],
) -> Dict[str, Any]:
    zip_sha = compute_sha256(artifact_paths["zip"]) if artifact_paths.get("zip") else ""
    overview_sha = compute_sha256(artifact_paths["overview"]) if artifact_paths.get("overview") else ""
    run_summary_sha = compute_sha256(artifact_paths["run_summary"]) if artifact_paths.get("run_summary") else ""
    viz_sha = compute_sha256(viz_path) if viz_path and viz_path.exists() else ""

    runs_manifest: List[Dict[str, Any]] = []
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
                "riftlens_flags": {str(x.threshold): bool(x.anomaly_flag) for x in r.riftlens},
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
        "overview": {"path": str(artifact_paths["overview"]), "sha256": overview_sha},
        "run_summary": {"path": str(artifact_paths["run_summary"]), "sha256": run_summary_sha},
        "zip": {"path": str(artifact_paths["zip"]), "sha256": zip_sha},
        "viz_overview": {"path": str(viz_path) if viz_path else "", "sha256": viz_sha},
        "overview_payload": overview,
        "runs": runs_manifest,
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
    parser = argparse.ArgumentParser(description="EchoNull - Graph & Null-Trace Anomaly Detection Framework")
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

    gad = subparsers.add_parser("gad", help="Run GAD-focused sweep")
    gad.add_argument("--runs", type=int, default=100)
    gad.add_argument("--thresholds", type=str, default="0.25,0.5,0.7,0.8")
    gad.add_argument("--seed-base", type=int, default=42)
    gad.add_argument("--workers", type=int, default=8)
    gad.add_argument("--use-dask", action="store_true")
    gad.add_argument("--enable-ml", action="store_true")
    gad.add_argument("--enable-viz", action="store_true")
    gad.add_argument("--score-weights", type=str, default="0.4,0.4,0.2")

    subparsers.add_parser("test", help="Run unit tests")
    subparsers.add_parser("bench", help="Run performance benchmarks")

    return parser.parse_args()


def main():
    args = parse_args()
    thresholds = [float(t.strip()) for t in getattr(args, "thresholds", "0.25,0.5,0.7,0.8").split(",") if t.strip()]
    score_weights = tuple(float(w.strip()) for w in getattr(args, "score_weights", "0.4,0.4,0.2").split(","))

    params: Dict[str, Any] = {
        "runs": int(getattr(args, "runs", 100)),
        "thresholds": thresholds,
        "seed_base": int(getattr(args, "seed_base", 42)),
        "workers": int(getattr(args, "workers", 8)),
        "output_base": str(BASE_OUTPUT_DIR / f"sweep_{TIMESTAMP}"),
        "use_dask": bool(getattr(args, "use_dask", False)),
        "enable_ml": bool(getattr(args, "enable_ml", False)),
        "enable_viz": bool(getattr(args, "enable_viz", False)),
        "score_weights": score_weights,
    }

    if args.command in ("sweep", "gad"):
        orchestrator = EchoNullOrchestrator(params)
        results = orchestrator.run_sweep()
        overview = orchestrator.generate_overview(results)
        viz_path = orchestrator.generate_viz(results) if params.get("enable_viz", False) else None
        artifact_paths = orchestrator.save_artifacts(results, overview)

        manifest = build_manifest(
            results=results,
            overview=overview,
            output_base=Path(params["output_base"]),
            artifact_paths=artifact_paths,
            viz_path=viz_path,
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
