"""Regression tests for real-run endpoint routing."""
from __future__ import annotations

import io
import subprocess
from pathlib import Path
from typing import Any, ClassVar

from hermesbench.run_real import _run_hermes
from hermesbench.types import TaskSpec

REPO = Path(__file__).resolve().parent.parent


class _FakePopen:
    captured: ClassVar[dict[str, Any]] = {}

    def __init__(self, cmd: list[str], **kwargs: Any) -> None:
        _FakePopen.captured = {"cmd": cmd, **kwargs}
        self.stdout = io.StringIO("")

    def wait(self, timeout: int | None = None) -> int:
        return 0

    def communicate(self, timeout: int | None = None) -> tuple[str, str]:
        return ("", "")

    @property
    def returncode(self) -> int:
        return 0

    def kill(self) -> None:  # pragma: no cover - only used on timeout path
        return None


def test_real_run_passes_local_base_url_and_dummy_key(monkeypatch, tmp_path: Path) -> None:
    """Local OpenAI-compatible servers often do not need auth, but Hermes needs a key arg.

    Without an explicit `--api_key`, run_agent.py may fall back to the user's Hermes
    config provider even when `--base_url` is supplied. That caused local benchmark
    runs to route to the wrong provider and fail with HTTP 403 instead of hitting
    the local vLLM endpoint.
    """

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(subprocess, "Popen", _FakePopen)
    hermes_path = tmp_path / "hermes-agent"
    hermes_path.mkdir()
    (hermes_path / "run_agent.py").write_text("", encoding="utf-8")
    task = TaskSpec.from_yaml(REPO / "tasks" / "t01_terminal_smoke" / "t01_echo" / "task.yaml")

    _run_hermes(
        hermes_path=hermes_path,
        worktree=tmp_path,
        isolated_home=tmp_path / "home",
        task=task,
        model="qwen36-27b-nvfp4",
        base_url="http://127.0.0.1:8999/v1",
        toolsets="all",
        max_turns=2,
        log_path=tmp_path / "run.log",
        timeout_seconds=10,
        use_hermes_config=False,
    )

    cmd = _FakePopen.captured["cmd"]
    env = _FakePopen.captured["env"]
    assert "--base_url" in cmd
    assert cmd[cmd.index("--base_url") + 1] == "http://127.0.0.1:8999/v1"
    assert "--api_key" in cmd
    assert cmd[cmd.index("--api_key") + 1] == "dummy"
    assert env["OPENAI_BASE_URL"] == "http://127.0.0.1:8999/v1"
    assert env["OPENAI_MODEL"] == "qwen36-27b-nvfp4"
    assert env["OPENAI_API_KEY"] == "dummy"
    assert env["TERMINAL_CWD"] == str(tmp_path)
    assert env["PWD"] == str(tmp_path)


def test_real_run_hermes_config_does_not_override_provider(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(subprocess, "Popen", _FakePopen)
    hermes_path = tmp_path / "hermes-agent"
    hermes_path.mkdir()
    (hermes_path / "run_agent.py").write_text("", encoding="utf-8")
    task = TaskSpec.from_yaml(REPO / "tasks" / "t01_terminal_smoke" / "t01_echo" / "task.yaml")

    _run_hermes(
        hermes_path=hermes_path,
        worktree=tmp_path,
        isolated_home=tmp_path / "home",
        task=task,
        model="configured-model",
        base_url="http://127.0.0.1:8999/v1",
        toolsets="all",
        max_turns=2,
        log_path=tmp_path / "run.log",
        timeout_seconds=10,
        use_hermes_config=True,
    )

    cmd = _FakePopen.captured["cmd"]
    assert "--base_url" not in cmd
    assert "--api_key" not in cmd
