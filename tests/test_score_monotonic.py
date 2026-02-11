import sys
from pathlib import Path

# Ensure repo root is importable so `import echonull` works on GitHub Actions
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import echonull  # noqa: E402


def test_compute_anomaly_score_monotonic_voidmark():
    rift = {0.25: {"jaccard": 1.0, "anomaly_flag": False}}
    nulltrace = {"abs_p99": 1e-6, "abs_mad": 1e-6}

    s0 = echonull.compute_anomaly_score(rift, nulltrace, {"anomaly_count": 0})
    s1 = echonull.compute_anomaly_score(rift, nulltrace, {"anomaly_count": 5})

    assert s1 > s0


def test_compute_anomaly_score_monotonic_graph_jaccard():
    nulltrace = {"abs_p99": 1e-6, "abs_mad": 1e-6}
    voidmark = {"anomaly_count": 0}

    high_j = {0.25: {"jaccard": 0.95, "anomaly_flag": False}}
    low_j = {0.25: {"jaccard": 0.75, "anomaly_flag": False}}

    s_high = echonull.compute_anomaly_score(high_j, nulltrace, voidmark)
    s_low = echonull.compute_anomaly_score(low_j, nulltrace, voidmark)

    # Lower jaccard => higher graph_component => higher score
    assert s_low > s_high


def test_compute_anomaly_score_monotonic_nulltrace_p99():
    rift = {0.25: {"jaccard": 1.0, "anomaly_flag": False}}
    voidmark = {"anomaly_count": 0}

    low_p = {"abs_p99": 1e-5, "abs_mad": 1e-6}
    high_p = {"abs_p99": 1e-2, "abs_mad": 1e-6}

    s_low = echonull.compute_anomaly_score(rift, low_p, voidmark)
    s_high = echonull.compute_anomaly_score(rift, high_p, voidmark)

    assert s_high > s_low
