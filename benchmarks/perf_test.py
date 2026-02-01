import time
import sys
from pathlib import Path

# Ensure repo root is on sys.path so `import echonull` works reliably
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import echonull  # noqa: E402


def bench():
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
