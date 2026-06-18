"""Q3.1a: test_recorder_roundtrip — produce a .cast, verify it parses."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RECORDER = REPO / "hermesbench" / "backend" / "recorder.py"


def _run_recorder(ansi_input: str, out: Path) -> None:
    """Spawn the recorder and feed it ANSI; close stdin to flush."""
    proc = subprocess.Popen(
        [sys.executable, "-u", str(RECORDER), "--out", str(out), "--cols", "80", "--rows", "24"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdin is not None
    time.sleep(0.2)
    proc.stdin.write(ansi_input)
    proc.stdin.flush()
    time.sleep(0.3)
    proc.stdin.close()
    rc = proc.wait(timeout=3)
    assert rc == 0, f"recorder exited {rc}, stderr: {proc.stderr.read()}"


def test_recorder_roundtrip(tmp_path: Path) -> None:
    """5-line bash session should produce a valid asciinema v2 .cast."""
    out = tmp_path / "x.cast"
    ansi = (
        "\x1b[?25l"  # hide cursor
        "echo hello\n"
        "echo world\n"
        "sleep 0.1\n"
        "ls -la\n"
        "echo done\n"
    )
    _run_recorder(ansi, out)

    assert out.exists()
    text = out.read_text()
    lines = text.splitlines()
    assert len(lines) >= 2, f"expected at least header + 1 frame, got {len(lines)}"

    # Header
    header = json.loads(lines[0])
    assert header["version"] == 2
    assert header["width"] == 80
    assert header["height"] == 24

    # At least one frame
    found_text = False
    for line in lines[1:]:
        frame = json.loads(line)
        assert len(frame) == 3
        assert frame[1] == "o"  # output frame
        if "hello" in frame[2] or "done" in frame[2]:
            found_text = True
    assert found_text, "no frame contained expected text"


def test_recorder_handles_empty_input(tmp_path: Path) -> None:
    out = tmp_path / "empty.cast"
    _run_recorder("", out)
    text = out.read_text()
    lines = text.splitlines()
    # Just the header, no frames (or one blank frame)
    assert len(lines) >= 1
    assert json.loads(lines[0])["version"] == 2


@pytest.mark.integration
@pytest.mark.skipif(
    subprocess.run(["which", "tmux"], capture_output=True).returncode != 0,
    reason="tmux not installed",
)
def test_recorder_via_tmux_pipe_pane(tmp_path: Path) -> None:
    """End-to-end: pipe-pane to recorder, run real bash commands.

    This is a manual integration test. The unit-level coverage
    is in test_recorder_roundtrip and test_recorder_handles_empty_input.
    The end-to-end tmux integration is sensitive to shell escaping
    and signal handling in subprocess environments and is marked
    as `integration` so it can be deselected in fast test runs.
    Run with: `pytest -m integration tests/test_recorder.py`
    """
    work = tmp_path
    cast = work / "tmux.cast"
    work / "recorder.err"
    session = f"hb_test_{int(time.time())}"
    recorder_cmd = f"{sys.executable} -u {RECORDER} --out {cast} --cols 200 --rows 50"
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", session, "-c", str(work), "-x", "200", "-y", "50"],
        check=True,
    )
    try:
        subprocess.run(
            ["tmux", "pipe-pane", "-t", session, "-o", recorder_cmd],
            check=True,
        )
        time.sleep(0.5)
        for cmd in ["echo hello", "echo world", "echo done"]:
            subprocess.run(["tmux", "send-keys", "-t", session, "-l", cmd], check=True)
            subprocess.run(["tmux", "send-keys", "-t", session, "Enter"], check=True)
            time.sleep(0.5)
        time.sleep(0.5)
    finally:
        subprocess.run(["tmux", "kill-session", "-t", session], capture_output=True)

    text = cast.read_text()
    assert "hello" in text, f"hello not in cast; size={len(text)}"
