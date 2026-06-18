"""TmuxIsolatedEnvironment: a fresh tmux session per task.

Each task gets:
- A fresh detached tmux session (`hermesbench-<session_name>`)
- A fresh worktree at `traces/<run_id>/<task_id>/worktree/`
- An isolated `$HOME` directory
- A fresh shell environment (PATH, env vars from task)
- Per-task `ulimit` enforcement (Q48)
- `DISABLED_TOOLSETS` injection (Q54)
- Optional `unshare --net` (Q8)
- Optional `pipe-pane` to a recorder that writes asciinema v2
  (Q3.1a / Q56)
- Latency injection in `_run_bash` (Q59)

The model never sees a difference from a regular hermes session —
the harness uses the same tool schemas, same AIAgent loop, same
conversation flow. We just changed which `bash` is being invoked.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from hermesbench.backend.base import BaseHermesBenchEnvironment, CommandResult
from hermesbench.backend.registry import register_backend

logger = logging.getLogger(__name__)


@register_backend("tmux_isolated")
class TmuxIsolatedEnvironment(BaseHermesBenchEnvironment):
    """Default v0.1 backend. See module docstring."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._tmux_server: subprocess.Popen | None = None
        self._recorder: subprocess.Popen | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def init_session(self) -> None:
        if self._initialized:
            return

        # Sanity checks
        for tool in ("tmux", "bash"):
            if shutil.which(tool) is None:
                raise RuntimeError(
                    f"{tool} not found on PATH; install or set TERMINAL_ENV to a different backend"
                )

        self.worktree.mkdir(parents=True, exist_ok=True)
        self.isolated_home.mkdir(parents=True, exist_ok=True)

        # Per-task env script
        env_script = self.worktree / ".hermesbench_env.sh"
        env_script.write_text(self._build_env_script())

        # Start tmux session
        cmd = [
            "tmux",
            "new-session",
            "-d",
            "-s",
            self.session_name,
            "-c",
            str(self.worktree),
            "-x",
            "200",
            "-y",
            "50",  # reasonable pane size for pyte
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"tmux new-session failed: {result.stderr}")

        # Source env script, apply ulimits, set HOME, disable echo
        setup_cmd = (
            f"source {shlex.quote(str(env_script))}; "
            f"export HOME={shlex.quote(str(self.isolated_home))}; "
            f"stty -echo; "
            f"clear"
        )
        self._send_keys(setup_cmd, enter=True)

        # Apply ulimits from resource_limits (Q48)
        for limit_name, value in self.resource_limits.items():
            self._apply_ulimit(limit_name, value)

        # Start the cast recorder (Q3.1a) if a path was provided
        if self.record_path is not None:
            self._start_recorder()

        self._initialized = True
        logger.info(
            "tmux session %s ready (worktree=%s, home=%s)",
            self.session_name,
            self.worktree,
            self.isolated_home,
        )

    def cleanup(self) -> None:
        """Tear down — idempotent and signal-safe."""
        # Stop recorder first
        if self._recorder is not None:
            try:
                self._recorder.terminate()
                self._recorder.wait(timeout=2)
            except Exception:
                with contextlib.suppress(Exception):
                    self._recorder.kill()
            self._recorder = None

        # Kill tmux session
        if self._initialized:
            subprocess.run(
                ["tmux", "kill-session", "-t", self.session_name],
                capture_output=True,
                check=False,
            )
            self._initialized = False

    # ------------------------------------------------------------------
    # run()
    # ------------------------------------------------------------------

    def run(self, cmd: str, *, timeout: int = 120) -> CommandResult:
        if not self._initialized:
            raise RuntimeError("init_session() not called")

        # Apply latency injection (Q59)
        for tool, delay_ms in self.latency_injection_ms.items():
            # We can't tell which tool the command uses from the command
            # text alone; we apply a pre-delay if the first token matches
            first_token = cmd.split()[0] if cmd.strip() else ""
            if first_token == tool and delay_ms > 0:
                time.sleep(delay_ms / 1000.0)
                break

        # Send command + Enter
        # Use a unique sentinel to delimit the output for capture
        sentinel = f"__HB_DONE_{os.getpid()}_{int(time.time() * 1e6)}__"
        full_cmd = f"{cmd}\necho {sentinel} $?\n"
        self._send_keys(full_cmd, enter=True)

        # Capture output by polling tmux capture-pane
        start = time.time()
        output = ""
        exit_code: int | None = None
        timed_out = False
        while time.time() - start < timeout:
            try:
                line = self._capture_last_line()
            except Exception:
                line = ""
            if sentinel in line:
                # Parse "echo <sentinel> <rc>"
                try:
                    after = line.split(sentinel, 1)[1].strip()
                    exit_code = int(after.split()[0])
                except (IndexError, ValueError):
                    exit_code = 0
                break
            time.sleep(0.05)
        else:
            timed_out = True
            # Force a new prompt by sending Enter
            self._send_keys("", enter=True)

        # Get full pane content (strip the sentinel echo line)
        output = self._capture_pane()
        if sentinel in output:
            output = output.split(sentinel)[0]

        return CommandResult(
            exit_code=exit_code if exit_code is not None else -1,
            stdout=output,
            stderr="",  # tmux merges stdout/stderr in the pane
            duration_seconds=time.time() - start,
            timed_out=timed_out,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _send_keys(self, text: str, *, enter: bool = True) -> None:
        """Send literal keys to the tmux session.

        Uses `tmux send-keys -l` for literal text (escaping handled by tmux).
        """
        cmd = ["tmux", "send-keys", "-t", self.session_name, "-l", text]
        subprocess.run(cmd, capture_output=True, check=False)
        if enter:
            subprocess.run(
                ["tmux", "send-keys", "-t", self.session_name, "Enter"],
                capture_output=True,
                check=False,
            )

    def _capture_pane(self) -> str:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", self.session_name, "-p", "-S", "-2000"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout

    def _capture_last_line(self) -> str:
        return (
            self._capture_pane().rstrip().splitlines()[-1] if self._capture_pane().strip() else ""
        )

    def _build_env_script(self) -> str:
        """Build the env script sourced in the session."""
        # Resource limits → ulimit
        ulimits: list[str] = []
        if "max_memory_mb" in self.resource_limits:
            mb = self.resource_limits["max_memory_mb"]
            ulimits.append(f"ulimit -v {mb * 1024}  # max_memory_mb={mb}")
        if "max_processes" in self.resource_limits:
            n = self.resource_limits["max_processes"]
            ulimits.append(f"ulimit -u {n}  # max_processes={n}")
        if "max_file_size_mb" in self.resource_limits:
            mb = self.resource_limits["max_file_size_mb"]
            ulimits.append(f"ulimit -f {mb * 1024 * 1024}  # max_file_size_mb={mb}")

        # DISABLED_TOOLSETS (Q54)
        disabled = ",".join(
            p
            for p in [
                "kanban",
                "memory_providers",
                "observability",
                "image_gen",
                "video_gen",
                "computer_use",
                "cronjob",
                "messaging",
                "ha_*",
                "send_message",
                "delegate_task",
            ]
            if p not in self.plugin_allowlist
        )

        lines = [
            "#!/bin/bash",
            "# hermesbench session env (auto-generated)",
            f"export HERMESBENCH_SESSION={shlex.quote(self.session_name)}",
            f"export HERMESBENCH_HOME={shlex.quote(str(self.isolated_home))}",
            f"export HERMESBENCH_WORKTREE={shlex.quote(str(self.worktree))}",
            f"export DISABLED_TOOLSETS={shlex.quote(','.join(p for p in disabled.split(',') if p))}",
            'export PS1="$ "',  # short prompt so pyte screen buffer is useful
            "export TERM=xterm-256color",
            "stty -echo",
            "set +o history",  # don't pollute the session history
            *ulimits,
        ]
        return "\n".join(lines) + "\n"

    def _apply_ulimit(self, name: str, value: int) -> None:
        """Apply a single ulimit in the session."""
        flag_map = {
            "max_memory_mb": ("-v", value * 1024),
            "max_processes": ("-u", value),
            "max_file_size_mb": ("-f", value * 1024 * 1024),
        }
        if name in flag_map:
            flag, val = flag_map[name]
            self._send_keys(f"ulimit {flag} {val}", enter=True)

    def _start_recorder(self) -> None:
        """Start the pyte-based recorder as a pipe-pane sink.

        Q3.1a / Q56: writes an asciinema v2 .cast file.
        The recorder is a separate Python process that maintains a
        screen buffer via pyte and flushes diffs to the .cast file.
        """
        if self.record_path is None:
            return
        # Ensure parent exists
        self.record_path.parent.mkdir(parents=True, exist_ok=True)
        # Spawn the recorder
        recorder_script = Path(__file__).parent / "recorder.py"
        cmd = [
            "python3",
            "-u",
            str(recorder_script),
            "--out",
            str(self.record_path),
            "--cols",
            "200",
            "--rows",
            "50",
        ]
        # The recorder reads from stdin; we connect pipe-pane to it
        self._recorder = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # pipe-pane
        subprocess.run(
            [
                "tmux",
                "pipe-pane",
                "-t",
                self.session_name,
                "-o",
                f"python3 -u {shlex.quote(str(recorder_script))} --out {shlex.quote(str(self.record_path))} --cols 200 --rows 50",
            ],
            capture_output=True,
            check=False,
        )
        logger.info("recorder started -> %s", self.record_path)


# Convenience entry point for the runner
def make_tmux_isolated(**kwargs: Any) -> TmuxIsolatedEnvironment:
    return TmuxIsolatedEnvironment(**kwargs)
