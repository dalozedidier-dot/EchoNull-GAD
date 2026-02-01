from pathlib import Path

import echonull


def test_compute_sha256():
    p = Path("tmp_test.txt")
    p.write_text("test", encoding="utf-8")
    try:
        assert echonull.compute_sha256(p) == "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
    finally:
        p.unlink()
