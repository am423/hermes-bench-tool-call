"""Worktree setup: create the per-task worktree and copy fixtures.

See Q55: worktrees live at `traces/<run_id>/<task_id>/worktree/`
and persist for the life of the run archive.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from hermesbench.types import TaskSpec


def setup_worktree(
    task: TaskSpec,
    *,
    run_id: str,
    repo_root: Path,
) -> Path:
    """Create the per-task worktree and copy the declared fixture.

    Returns the worktree path. Caller is responsible for running the
    task and for *not* deleting the worktree (per Q55: persistent).
    """
    # Q55: persistent location
    worktree = repo_root / "traces" / run_id / task.id / "worktree"
    worktree.mkdir(parents=True, exist_ok=True)

    # Copy fixture
    fixture_root = repo_root / "fixtures"
    source = fixture_root / task.fixture.source
    if source.exists():
        if task.fixture.globs == ["**/*"]:
            # Copy everything
            for src in source.rglob("*"):
                if src.is_file():
                    rel = src.relative_to(source)
                    dst = worktree / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
        else:
            for pattern in task.fixture.globs:
                for src in source.glob(pattern):
                    if src.is_file():
                        rel = src.relative_to(source)
                        dst = worktree / rel
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)

    task.worktree = worktree
    return worktree


def results_dir(run_id: str, repo_root: Path) -> Path:
    """The per-run results directory."""
    p = repo_root / "results" / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def trace_dir(run_id: str, task_id: str, repo_root: Path) -> Path:
    """The per-task trace/cast/stats directory (Q55)."""
    p = repo_root / "traces" / run_id / task_id
    p.mkdir(parents=True, exist_ok=True)
    return p
