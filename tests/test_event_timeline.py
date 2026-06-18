"""Tests for event timeline builder."""

from __future__ import annotations

import json
from pathlib import Path

from hermesbench.event_timeline import build_timeline_from_summary


def test_build_timeline_from_summary_minimal() -> None:
    summary = {
        "run_id": "test_run",
        "model": "test-model",
        "tasks": [
            {
                "task_id": "t01_terminal_smoke/t01_echo",
                "name": "Echo",
                "status": "PASS",
                "elapsed_seconds": 5.0,
            },
            {
                "task_id": "t01_terminal_smoke/t02_ls",
                "name": "Ls",
                "status": "FAIL",
                "reason": "nope",
                "elapsed_seconds": 10.0,
            },
        ],
    }
    tl = build_timeline_from_summary(summary, video_duration=20.0)
    assert tl["total_tasks"] == 2
    assert tl["passed"] == 1
    assert len(tl["events"]) == 2
    assert tl["events"][0]["family_label"] == "Terminal Smoke"
    assert tl["last_event_end"] >= tl["events"][-1]["end_sec"]
    assert tl["finale_start"] >= tl["last_event_start"]
    assert tl["video_duration"] <= tl["finale_start"] + tl["outro_seconds"] + 1
    assert len(tl["term_segments"]) >= 1


def test_write_event_timeline_file(tmp_path: Path) -> None:
    from hermesbench.event_timeline import write_event_timeline

    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "run_id": "r1",
                "model": "m",
                "tasks": [
                    {
                        "task_id": "t01_terminal_smoke/t01_echo",
                        "name": "e",
                        "status": "PASS",
                        "elapsed_seconds": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "tl.json"
    write_event_timeline(summary_path, out)
    assert out.is_file()
    data = json.loads(out.read_text())
    assert data["events"]
