import json
import sys
import zipfile
from pathlib import Path

import pytest

# Ensure repo root is importable so `import echonull` works on GitHub Actions
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import echonull  # noqa: E402


def test_orchestrator_two_runs_artifacts_and_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Run everything inside a temp working dir because write_manifest also writes ./manifest.json
    monkeypatch.chdir(tmp_path)

    output_base = tmp_path / "_echonull_out" / "sweep_test"
    params = {
        "runs": 2,
        "thresholds": [0.25, 0.5],
        "seed_base": 1000,
        "workers": 1,
        "use_dask": False,
        "enable_ml": False,
        "enable_viz": False,
        "score_weights": (0.4, 0.4, 0.2),
        "output_base": str(output_base),
    }

    # Avoid multiprocessing in unit tests: call worker directly.
    results = [echonull.process_run_worker(i, params) for i in range(1, 3)]

    orch = echonull.EchoNullOrchestrator(params)
    overview = orch.generate_overview(results)
    viz_path = orch.generate_viz(results)  # should be None because enable_viz=False
    artifact_paths = orch.save_artifacts(results, overview)

    manifest = echonull.build_manifest(results, overview, Path(params["output_base"]), artifact_paths, viz_path)
    echonull.write_manifest(manifest, Path(params["output_base"]))

    # Basic outputs exist
    assert artifact_paths["overview"].exists()
    assert artifact_paths["run_summary"].exists()
    assert artifact_paths["zip"].exists()
    assert (output_base / "manifest.json").exists()
    assert Path("manifest.json").exists()

    # Manifest payload sanity
    root_manifest = json.loads(Path("manifest.json").read_text(encoding="utf-8"))
    assert root_manifest["overview_payload"]["runs_found"] == 2
    assert len(root_manifest["runs"]) == 2

    # Sha256 coherence
    assert echonull.compute_sha256(Path(root_manifest["overview"]["path"])) == root_manifest["overview"]["sha256"]
    assert echonull.compute_sha256(Path(root_manifest["run_summary"]["path"])) == root_manifest["run_summary"]["sha256"]
    assert echonull.compute_sha256(Path(root_manifest["zip"]["path"])) == root_manifest["zip"]["sha256"]

    # Zip contains the two run folders
    with zipfile.ZipFile(Path(root_manifest["zip"]["path"]), "r") as zf:
        names = set(zf.namelist())
        # The zip is rooted at "<output_base.name>/..."
        base = output_base.name
        assert f"{base}/run_0001/multi.csv" in names
        assert f"{base}/run_0002/multi.csv" in names
