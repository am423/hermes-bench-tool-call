"""Task runner: orchestrate the per-task lifecycle.

Q55: worktree persists at traces/<run_id>/<task_id>/worktree/.
Q7: statsd starts before hermes; Q42: hermes timeout drains trace.
Q48: resource limits via tmux session ulimits.
Q57: endpoint smoke test before run.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

from hermesbench.backend import worktree as worktree_setup
from hermesbench.backend.base import BaseHermesBenchEnvironment
from hermesbench.backend.tmux_isolated import TmuxIsolatedEnvironment
from hermesbench.scoring import compute_hardware_metrics
from hermesbench.types import (
    RunId,
    RunMeta,
    TaskResult,
    TaskSpec,
    VerifierResult,
    VerifierStatus,
)

logger = logging.getLogger(__name__)


REPO = Path(__file__).resolve().parent.parent

_smoke_test_cache: dict[str, bool] = {}


def make_run_id(model: str) -> RunId:
    """Q21: <model_slug>_<YYYYMMDD-HHMMSS>_<8-char-uuid>."""
    slug = _slugify(model)
    return RunId(
        model_slug=slug,
        timestamp=datetime.now(),
        nonce=uuid.uuid4().hex[:8],
    )


def _slugify(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s)[:80]


def run_task(
    task: TaskSpec,
    *,
    model: str,
    base_url: str,
    repo_root: Path = REPO,
    dry_run: bool = False,
    use_real_agent: bool = False,
) -> TaskResult:
    """Run a single task end-to-end.

    Returns a TaskResult. Never raises; all errors are captured
    in the result's `verifier_result.status` field.
    """
    run_id = make_run_id(model)
    run_id_str = str(run_id)
    started_at = time.time()

    # 1. Resolve hermes-agent (Q22)
    from hermesbench.hermes_invocation import (
        find_hermes_agent,
        get_hermes_sha,
        get_hermes_version,
        smoke_test_endpoint,
    )

    try:
        hermes_path = find_hermes_agent()
    except FileNotFoundError as e:
        return TaskResult(
            task_id=task.id,
            run_id=run_id_str,
            worktree=Path(),
            trace_path=Path(),
            cast_path=Path(),
            stats_path=Path(),
            meta_path=Path(),
            verifier_result=VerifierResult(status=VerifierStatus.VERIFIER_ERROR, reason=str(e)),
            started_at=started_at,
            finished_at=time.time(),
            error=str(e),
        )

    hermes_sha = get_hermes_sha(hermes_path)
    hermes_version = get_hermes_version(hermes_path)

    # 2. Setup worktree (Q55)
    worktree = worktree_setup.setup_worktree(task, run_id=run_id_str, repo_root=repo_root)
    isolated_home = Path(tempfile.mkdtemp(prefix=f"hb-home-{run_id.nonce}-"))
    task_dir = repo_root / "traces" / run_id_str / task.id
    cast_path = task_dir / "trace.cast"
    stats_path = task_dir / "stats.jsonl"
    trace_path = task_dir / "trace.jsonl"

    # 3. Endpoint smoke test — skip for real agent (uses hermes CLI which handles auth)
    if not dry_run and not use_real_agent and not _smoke_test_cache.get(model):
        ok, msg = smoke_test_endpoint(base_url, model, task.model_endpoint.__dict__)
        if not ok:
            return TaskResult(
                task_id=task.id,
                run_id=run_id_str,
                worktree=worktree,
                trace_path=trace_path,
                cast_path=cast_path,
                stats_path=stats_path,
                meta_path=Path(),
                verifier_result=VerifierResult(
                    status=VerifierStatus.VERIFIER_ERROR,
                    reason=f"endpoint smoke test failed: {msg}",
                ),
                started_at=started_at,
                finished_at=time.time(),
                error=msg,
            )
        _smoke_test_cache[model] = True
    if dry_run:
        return TaskResult(
            task_id=task.id,
            run_id=run_id_str,
            worktree=worktree,
            trace_path=trace_path,
            cast_path=cast_path,
            stats_path=stats_path,
            meta_path=Path(),
            verifier_result=VerifierResult(status=VerifierStatus.SKIPPED, reason="dry-run"),
            started_at=started_at,
            finished_at=time.time(),
        )

    # 5. Setup backend
    backend: BaseHermesBenchEnvironment = TmuxIsolatedEnvironment(
        worktree=worktree,
        isolated_home=isolated_home,
        session_name=f"hb-{run_id.nonce}",
        record_path=cast_path,
        resource_limits={
            "max_memory_mb": task.resource_limits.max_memory_mb,
            "max_processes": task.resource_limits.max_processes,
            "max_file_size_mb": task.resource_limits.max_file_size_mb,
        },
        plugin_allowlist=task.hermes_plugins,
        latency_injection_ms=task.latency_injection_ms.__dict__,
        isolated_network=task.isolated_network,
    )

    # 6. Start statsd
    statsd_proc: subprocess.Popen | None = None
    try:
        backend.init_session()
    except Exception as e:
        return TaskResult(
            task_id=task.id,
            run_id=run_id_str,
            worktree=worktree,
            trace_path=trace_path,
            cast_path=cast_path,
            stats_path=stats_path,
            meta_path=Path(),
            verifier_result=VerifierResult(
                status=VerifierStatus.VERIFIER_ERROR,
                reason=f"backend init failed: {e}",
            ),
            started_at=started_at,
            finished_at=time.time(),
            error=str(e),
        )

    try:
        statsd_proc = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-m",
                "hermesbench.statsd",
                "--out",
                str(stats_path),
                "--hz",
                "5",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # 7. Spawn hermes (Q53 line-buffered)
        from hermesbench.hermes_invocation import export_to_trace, spawn_hermes

        env_overrides = {
            "DISABLED_TOOLSETS": ",".join(
                p
                for p in (
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
                )
                if p not in task.hermes_plugins
            ),
        }
        hermes_proc = spawn_hermes(
            hermes_path=hermes_path,
            task_prompt=task.prompt,
            worktree=worktree,
            isolated_home=isolated_home,
            cast_path=cast_path,
            model=model,
            base_url=base_url,
            env_overrides=env_overrides,
            timeout_seconds=task.timeout_seconds,
            allowed_tools=task.allowed_tools,
            use_real_agent=use_real_agent,
            max_turns=task.max_turns,
        )

        # 8. Stream the trace — dual mode
        if use_real_agent:
            # Real agent: wait for completion, then capture session via export
            try:
                hermes_proc.wait(timeout=task.timeout_seconds)
            except subprocess.TimeoutExpired:
                hermes_proc.kill()
                hermes_proc.wait(timeout=5)

            stdout_text = hermes_proc.stdout.read() if hermes_proc.stdout else ""
            stderr_text = hermes_proc.stderr.read() if hermes_proc.stderr else ""

            # Parse session_id from stderr
            import re as _re

            session_id = None
            for line in stderr_text.splitlines():
                m = _re.search(r"session_id:\s*(\S+)", line)
                if m:
                    session_id = m.group(1)
                    break

            if session_id:
                # Export session and convert to per-message JSONL
                export_tmp = Path(tempfile.mktemp(suffix=".jsonl"))
                hermes_bin = shutil.which("hermes") or str(hermes_path / "hermes")
                export_result = subprocess.run(
                    [hermes_bin, "sessions", "export", "--session-id", session_id, str(export_tmp)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if export_result.returncode == 0 and export_tmp.exists():
                    export_to_trace(export_tmp, trace_path)
                    export_tmp.unlink(missing_ok=True)
                else:
                    # Fallback: write stdout as plain text
                    trace_path.write_text(stdout_text)
            else:
                # Fallback: no session_id, write stdout
                trace_path.write_text(stdout_text)
        else:
            # Fake mode: read JSONL from stdout (existing behavior)
            with trace_path.open("w") as f:
                assert hermes_proc.stdout is not None
                for line in hermes_proc.stdout:
                    f.write(line)
            try:
                hermes_proc.wait(timeout=task.timeout_seconds)
            except subprocess.TimeoutExpired:
                hermes_proc.kill()
                if hermes_proc.stdout:
                    try:
                        rest = hermes_proc.stdout.read(65536)
                        with trace_path.open("a") as f:
                            f.write(rest)
                    except Exception:
                        pass

    finally:
        # 9. Stop statsd, cleanup
        if statsd_proc is not None:
            try:
                statsd_proc.terminate()
                statsd_proc.wait(timeout=5)
            except Exception:
                pass
        backend.cleanup()

    finished_at = time.time()

    # 10. Run verifier
    verifier_result = _run_verifier(task, worktree, trace_path)

    # 11. Write meta.json
    meta = RunMeta(
        run_id=run_id_str,
        model=model,
        model_slug=run_id.model_slug,
        hermes_sha=hermes_sha,
        hermes_path=str(hermes_path),
        hermes_agent_version=hermes_version,
        hermesbench_version="0.1.0",
        started_at=started_at,
        finished_at=finished_at,
        status="completed" if hermes_proc.returncode == 0 else "crashed",
        exit_code=hermes_proc.returncode,
        python_version=platform.python_version(),
        platform=platform.platform(),
        hostname=socket.gethostname(),
        worktree_root=str(worktree),
        worktree_strategy="persistent",
    )
    meta_path = task_dir / "meta.json"
    meta_path.write_text(json.dumps(meta.__dict__, indent=2, default=str))

    # 12. Write verifier_result.json
    results_subdir = repo_root / "results" / run_id_str / task.id
    results_subdir.mkdir(parents=True, exist_ok=True)
    (results_subdir / "verifier_result.json").write_text(
        json.dumps(
            {
                "task_id": task.id,
                "difficulty": task.difficulty,
                **verifier_result.__dict__,
            },
            indent=2,
        )
    )
    # Also link/save stats from statsd
    if stats_path.exists():
        (results_subdir / "stats.jsonl").write_text(stats_path.read_text())
        hw = compute_hardware_metrics(stats_path)
        (results_subdir / "hardware.json").write_text(json.dumps(hw.__dict__, indent=2))

    return TaskResult(
        task_id=task.id,
        run_id=run_id_str,
        worktree=worktree,
        trace_path=trace_path,
        cast_path=cast_path,
        stats_path=stats_path,
        meta_path=meta_path,
        verifier_result=verifier_result,
        started_at=started_at,
        finished_at=finished_at,
    )


def _run_verifier(task: TaskSpec, worktree: Path, trace_path: Path) -> VerifierResult:
    """Load and execute the task's verifier.

    Verifiers are stdlib-only modules exporting `verify(worktree, trace)`.
    """
    import sys

    spec = task.verifier
    parts = task.id.split("/")
    if len(parts) == 2:
        verifier_path = REPO / "tasks" / parts[0] / parts[1] / f"{spec.module}.py"
    else:
        verifier_path = REPO / "tasks" / task.id / f"{spec.module}.py"

    if not verifier_path.exists():
        return VerifierResult(
            status=VerifierStatus.VERIFIER_ERROR,
            reason=f"verifier not found: {verifier_path}",
        )

    # Q-stand-in: register in sys.modules BEFORE exec_module so
    # Python 3.14's dataclass introspection can find the module.
    mod_name = f"hermesbench_verifier_{task.id.replace('/', '_').replace('-', '_')}"
    try:
        mod_spec = importlib.util.spec_from_file_location(mod_name, verifier_path)
        mod = importlib.util.module_from_spec(mod_spec)  # type: ignore[arg-type]
        sys.modules[mod_name] = mod
        assert mod_spec is not None and mod_spec.loader is not None
        mod_spec.loader.exec_module(mod)  # type: ignore[union-attr]
        fn = getattr(mod, spec.fn)
    except Exception as e:
        return VerifierResult(
            status=VerifierStatus.VERIFIER_ERROR,
            reason=f"verifier import failed: {type(e).__name__}: {e}",
        )

    try:
        from hermesbench.trace import read_trace

        trace = read_trace(trace_path) if trace_path.exists() else []
        result = fn(worktree, trace)
        # Verifier defines its own VerifierResult (Q5: stdlib-only).
        # Use duck-typing, not isinstance, since the classes are
        # distinct.
        if not hasattr(result, "status") or not hasattr(result, "score"):
            return VerifierResult(
                status=VerifierStatus.VERIFIER_ERROR,
                reason=f"verifier returned {type(result).__name__}, missing status/score attrs",
            )
        # Coerce into our VerifierResult
        try:
            status = VerifierStatus(str(result.status))
        except ValueError:
            return VerifierResult(
                status=VerifierStatus.VERIFIER_ERROR,
                reason=f"verifier status {result.status!r} not a known VerifierStatus",
            )
        return VerifierResult(
            status=status,
            score=float(getattr(result, "score", 0.0)),
            reason=str(getattr(result, "reason", "")),
            details=dict(getattr(result, "details", {})),
        )
    except Exception as e:
        return VerifierResult(
            status=VerifierStatus.VERIFIER_ERROR,
            reason=f"verifier raised: {type(e).__name__}: {e}",
        )
