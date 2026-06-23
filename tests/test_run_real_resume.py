"""Unit tests for run_real resume skip logic."""

from __future__ import annotations

from pathlib import Path

from hermesbench.cli import _load_task
from hermesbench.run_real import (
    _build_task_query,
    _completed_tasks_by_id,
    _effective_toolsets_for_task,
    _merge_task_rows,
    tasks_to_run_with_resume,
)

REPO = Path(__file__).resolve().parent.parent


def _fake_task(task_id: str):
    base = _load_task(REPO / "tasks/t01_terminal_smoke/t01_echo")
    base.id = task_id
    base.name = task_id
    return base


def test_completed_tasks_by_id_only_pass_fail() -> None:
    summary = {
        "tasks": [
            {"task_id": "a/t1", "status": "PASS"},
            {"task_id": "a/t2", "status": "FAIL"},
            {"task_id": "a/t3", "status": "TIMEOUT"},
        ]
    }
    done = _completed_tasks_by_id(summary)
    assert set(done) == {"a/t1", "a/t2"}


def test_tasks_to_run_with_resume_skips_completed() -> None:
    tasks = [_fake_task("a/t1"), _fake_task("a/t2"), _fake_task("a/t3")]
    completed = {
        "a/t1": {"task_id": "a/t1", "status": "PASS"},
        "a/t2": {"task_id": "a/t2", "status": "FAIL"},
    }
    pending, skipped = tasks_to_run_with_resume(tasks, completed_by_id=completed)
    assert [t.id for t in pending] == ["a/t3"]
    assert len(skipped) == 2


def test_merge_task_rows_preserves_selection_order() -> None:
    prior = {"a/t1": {"task_id": "a/t1", "status": "PASS"}}
    fresh = [{"task_id": "a/t2", "status": "FAIL"}]
    merged = _merge_task_rows(["a/t1", "a/t2"], prior, fresh)
    assert [r["task_id"] for r in merged] == ["a/t1", "a/t2"]
    assert merged[0]["status"] == "PASS"
    assert merged[1]["status"] == "FAIL"


def test_load_summary_from_disk(tmp_path: Path) -> None:
    from hermesbench.run_real import _load_existing_summary

    path = tmp_path / "summary.json"
    path.write_text('{"tasks": [{"task_id": "x", "status": "PASS"}]}', encoding="utf-8")
    loaded = _load_existing_summary(path)
    assert loaded is not None
    assert _completed_tasks_by_id(loaded)["x"]["status"] == "PASS"


def test_build_task_query_includes_worktree(tmp_path: Path) -> None:
    task = _fake_task("a/t1")
    query = _build_task_query(task, tmp_path)

    assert f"Benchmark worktree: {tmp_path}" in query
    assert "Prefer relative paths" in query
    assert task.prompt in query


def test_effective_toolsets_auto_uses_task_allowed_tools() -> None:
    task = _load_task(REPO / "tasks/t04_search_grep/t02_glob")

    assert _effective_toolsets_for_task(task, "auto") == "file,terminal"
    assert _effective_toolsets_for_task(task, "all") == "all"
