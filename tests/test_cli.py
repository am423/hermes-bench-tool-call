"""Q74: tests for the CLI surface.

Covers: each subcommand's happy path, exit codes, error handling.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "hermesbench", *args],
        capture_output=True,
        text=True,
        cwd=REPO,
    )


def test_cli_help() -> None:
    r = run_cli("--help")
    assert r.returncode == 0
    assert "hermesbench" in r.stdout
    assert "run" in r.stdout
    r_run = run_cli("run", "--help")
    assert r_run.returncode == 0
    assert "--engine" in r_run.stdout


def test_cli_version() -> None:
    r = run_cli("--version")
    assert r.returncode == 0
    assert "0.3.0" in r.stdout


def test_cli_list() -> None:
    r = run_cli("list")
    assert r.returncode == 0


def test_cli_doctor_runs() -> None:
    r = run_cli("doctor")
    # doctor may return 4 if agg missing, but should always be in {0, 4}
    assert r.returncode in (0, 4)


def test_cli_validate_default_targets() -> None:
    r = run_cli("validate")
    # Should validate fixtures/ + tasks/ — both valid
    assert r.returncode == 0


def test_cli_validate_with_path() -> None:
    r = run_cli("validate", "--path", "tasks/")
    assert r.returncode == 0


def test_cli_run_unknown_task_exits_4() -> None:
    r = run_cli("run", "--model", "x", "--task", "t99_nonexistent")
    assert r.returncode == 4
    assert "task not found" in r.stderr


def test_cli_run_no_args_exits_4() -> None:
    r = run_cli("run", "--model", "x")
    assert r.returncode == 4
    assert "Specify" in r.stderr


def test_cli_run_dry_run_all() -> None:
    r = run_cli("run", "--model", "x", "--all", "--dry-run")
    assert r.returncode == 0
    assert "dry-run" in r.stderr


def test_cli_run_engine_legacy_dry_run() -> None:
    r = run_cli(
        "run",
        "--engine",
        "legacy",
        "--model",
        "x",
        "--base-url",
        "http://127.0.0.1:8080/v1",
        "--task",
        "t01_terminal_smoke/t01_echo",
        "--dry-run",
    )
    assert r.returncode == 0
    assert "legacy" in r.stderr


def test_cli_score_missing_path() -> None:
    r = run_cli("score", "--path", "/nonexistent/path")
    assert r.returncode == 0
    assert "path does not exist" in r.stderr
    assert "Traceback" not in r.stderr
