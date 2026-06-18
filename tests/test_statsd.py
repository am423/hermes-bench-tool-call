"""Q-test: statsd samples for 5s, produces valid .stats.jsonl."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_statsd_runs(tmp_path: Path) -> None:
    """statsd should sample for ~2s and produce a valid .stats.jsonl."""
    out = tmp_path / "x.stats.jsonl"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "hermesbench.statsd",
            "--out",
            str(out),
            "--hz",
            "5",
            "--no-pin",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        time.sleep(2.0)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    assert out.exists(), "stats.jsonl not created"
    lines = [json.loads(line) for line in out.read_text().splitlines() if line]
    assert 5 <= len(lines) <= 15, f"expected ~10 samples at 5 Hz over 2s, got {len(lines)}"
    for s in lines[:3]:
        assert "t" in s and "cpu" in s
        assert "gpu" in s
        assert "ram" in s
    # CPU must have util (could be 0 on idle box, but the key must be there)
    assert "util_pct" in lines[0]["cpu"]
    # GPU is a list (possibly empty)
    assert isinstance(lines[0]["gpu"], list)
