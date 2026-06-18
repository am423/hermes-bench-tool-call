"""Abstract base for hermesbench execution backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommandResult:
    """The result of running a single command in an environment."""

    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False


class BaseHermesBenchEnvironment(ABC):
    """Common interface for execution backends.

    Mirrors the role of `hermes_agent.tools.environments.base.BaseEnvironment`
    but is hermesbench-owned. v0.1 ships the tmux_isolated subclass only.

    Lifecycle: `__init__` -> `init_session()` -> N * `run(cmd)` -> `cleanup()`.
    `cleanup()` is idempotent and signal-safe.
    """

    def __init__(
        self,
        *,
        worktree: Path,
        isolated_home: Path,
        session_name: str,
        record_path: Path | None = None,  # .cast file path
        resource_limits: dict[str, int] | None = None,
        plugin_allowlist: list[str] | None = None,
        latency_injection_ms: dict[str, int] | None = None,
        isolated_network: bool = True,
    ):
        self.worktree = Path(worktree)
        self.isolated_home = Path(isolated_home)
        self.session_name = session_name
        self.record_path = Path(record_path) if record_path else None
        self.resource_limits = resource_limits or {}
        self.plugin_allowlist = plugin_allowlist or []
        self.latency_injection_ms = latency_injection_ms or {}
        self.isolated_network = isolated_network
        self._initialized = False

    @abstractmethod
    def init_session(self) -> None:
        """Bring up the environment. Called once before any run() call."""

    @abstractmethod
    def run(self, cmd: str, *, timeout: int = 120) -> CommandResult:
        """Run a single command. Must respect CWD = self.worktree."""

    @abstractmethod
    def cleanup(self) -> None:
        """Tear down. Idempotent and signal-safe."""
