# EchoNull-GAD

Lightweight CI-native framework for graph anomaly detection via parameter sweeps.

**Scaling Status** (February 2026)

| Runs | Mode | Status | Time | Zip Size | Notes |
|------|------|--------|------|----------|-------|
| 50   | sweep | ✅ OK | ~15 min | ~100 Mo | Good variance in GAD scores |
| 100  | sweep | À tester | ~30 min est. | ~200 Mo est. | - |
| 200  | sweep | À tester | ~60 min est. | ~400 Mo est. | - |

To test scaling, use the Actions workflow.

**Latest Viz (from 50 runs)**
![Viz Overview](viz_overview.png)

**Usage**
```bash
python echonull.py sweep --runs 100
```
