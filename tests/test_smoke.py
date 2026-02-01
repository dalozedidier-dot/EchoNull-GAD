from pathlib import Path
import importlib.util

def _load_echonull():
    # Import echonull.py as module even if repo is not packaged
    spec = importlib.util.spec_from_file_location("echonull", "echonull.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod

def test_compute_sha256():
    echonull = _load_echonull()
    p = Path("tmp_test.txt")
    p.write_text("test", encoding="utf-8")
    try:
        assert echonull.compute_sha256(p) == "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
    finally:
        p.unlink()
