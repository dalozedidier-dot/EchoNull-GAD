import sys
from pathlib import Path

# Ensure repo root is importable so `import echonull` works on GitHub Actions
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import echonull  # noqa: E402


def test_compute_sha256():
    p = Path("tmp_test.txt")
    p.write_text("test", encoding="utf-8")
    try:
        assert echonull.compute_sha256(p) == "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
    finally:
        p.unlink()
