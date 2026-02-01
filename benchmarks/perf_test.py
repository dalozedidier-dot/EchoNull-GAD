import time
import importlib.util
from pathlib import Path

def load_echonull_module():
    repo_root = Path(__file__).resolve().parents[1]
    echonull_path = repo_root / "echonull.py"
    spec = importlib.util.spec_from_file_location("echonull_mod", echonull_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod

def bench():
    echonull = load_echonull_module()
    start = time.time()
    params = {
        "runs": 10,
        "thresholds": [0.25, 0.5, 0.7, 0.8],
        "seed_base": 1000,
        "workers": 4,
        "output_base": "_echonull_out/bench_10runs",
        "use_dask": False,
        "enable_ml": False,
        "enable_viz": False,
        "score_weights": (0.4, 0.4, 0.2),
    }
    orchestrator = echonull.EchoNullOrchestrator(params)
    orchestrator.run_sweep()
    print(f"Bench 10 runs: {time.time() - start:.2f} s")

if __name__ == "__main__":
    bench()
