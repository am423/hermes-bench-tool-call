"""Run hermesbench tasks against the real Hermes Agent (run_agent.py)."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from hermesbench.backend import worktree as worktree_setup
from hermesbench.cli import _discover_tasks, _load_task
from hermesbench.hermes_invocation import (
    find_hermes_agent,
    get_hermes_sha,
    get_hermes_version,
    hermes_python,
)
from hermesbench.runner import _run_verifier
from hermesbench.types import TaskSpec, VerifierResult, VerifierStatus

REPO = Path(__file__).resolve().parent.parent

FINAL_TASK_STATUSES = frozenset({"PASS", "FAIL"})


DEFAULT_BASE_URL = "https://api.kilo.ai/api/gateway"
DEFAULT_MODEL = "nex-agi/nex-n2-pro:free"
DEFAULT_TOOLSETS = "all"
FUNCTION_CALL_OPEN = "<" + "tool_call" + ">"
FUNCTION_CALL_CLOSE = "</" + "tool_call" + ">"
FUNCTION_CALL_RE = re.compile(
    re.escape(FUNCTION_CALL_OPEN) + r"(.*?)" + re.escape(FUNCTION_CALL_CLOSE), re.S
)
FUNCTION_CALL_STRIP_RE = re.compile(
    re.escape(FUNCTION_CALL_OPEN) + r".*?" + re.escape(FUNCTION_CALL_CLOSE), re.S
)
REASONING_SCRATCHPAD_RE = re.compile(
    r"<" + "REASONING_SCRATCHPAD" + ">(.*?)</" + "REASONING_SCRATCHPAD" + ">", re.S
)
THINK_RE = re.compile(r"<" + "think" + ">", re.S)
THINK_CLOSE_RE = re.compile(r"</" + "think" + ">", re.S)
THINK_RE2 = re.compile(r"<" + "</think>" + ">", re.S)
THINK_CLOSE_RE2 = re.compile(r"</" + "</think>" + ">", re.S)


def _slugify(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in value)[:120]


def _now() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _timestamp_to_float(value: str) -> float:
    try:
        return datetime.fromisoformat(value).timestamp()
    except Exception:
        try:
            return float(value)
        except Exception:
            return 0.0


def _parse_tool_result(value: str) -> dict[str, Any]:
    text = value.strip()
    if text.startswith("result"):
        text = text.split("\n", 1)[1].strip() if "\n" in text else ""
    try:
        return json.loads(text)
    except Exception:
        return {"content": value}


def _extract_reasoning(value: str) -> tuple[str, list[str]]:
    reasoning: list[str] = []
    content = value

    for tag in ("REASONING_SCRATCHPAD", "think", "</think>"):
        pattern = rf"<{tag}>(.*?)</{tag}>"
        matches = re.findall(pattern, content, flags=re.S)
        if matches:
            reasoning.extend(m.strip() for m in matches if m.strip())
            content = re.sub(pattern, "", content, flags=re.S)

    return content.strip(), reasoning


def _extract_tool_calls(
    value: str, tool_call_ids: list[str], offset: int
) -> tuple[list[dict[str, Any]], int]:
    calls: list[dict[str, Any]] = []
    next_id = offset
    for match in FUNCTION_CALL_RE.finditer(value):
        raw = match.group(1).strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        tool_call_id = tool_call_ids[next_id] if next_id < len(tool_call_ids) else f"call_{next_id}"
        calls.append(
            {
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": str(obj.get("name", "")),
                    "arguments": json.dumps(obj.get("arguments", {}), ensure_ascii=False),
                },
            }
        )
        next_id += 1
    return calls, next_id


def _trajectory_to_trace(traj_path: Path, trace_path: Path) -> None:
    """Convert run_agent.py trajectory JSONL into hermesbench trace JSONL."""
    trace: list[dict[str, Any]] = []
    for line in traj_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        conversations = entry.get("conversations", [])
        tool_call_ids: list[str] = []
        for conv in conversations:
            if conv.get("from") == "tool":
                result = _parse_tool_result(str(conv.get("value", "")))
                if result.get("tool_call_id"):
                    tool_call_ids.append(str(result["tool_call_id"]))

        tool_id_cursor = 0
        for conv in conversations:
            role_raw = conv.get("from")
            value = str(conv.get("value", ""))
            ts = _timestamp_to_float(entry.get("timestamp", ""))

            if role_raw == "system":
                trace.append({"role": "system", "content": value, "ts": ts})
                continue

            if role_raw == "human":
                trace.append({"role": "user", "content": value, "ts": ts})
                continue

            if role_raw == "gpt":
                clean_value, reasoning = _extract_reasoning(value)
                tool_calls, tool_id_cursor = _extract_tool_calls(
                    clean_value, tool_call_ids, tool_id_cursor
                )
                clean_value = FUNCTION_CALL_STRIP_RE.sub("", clean_value).strip()
                clean_value = REASONING_SCRATCHPAD_RE.sub("", clean_value).strip()
                clean_value = THINK_RE.sub("", clean_value).strip()
                clean_value = THINK_CLOSE_RE.sub("", clean_value).strip()
                clean_value = THINK_RE2.sub("", clean_value).strip()
                clean_value = THINK_CLOSE_RE2.sub("", clean_value).strip()
                msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": clean_value or None,
                    "ts": ts,
                }
                if tool_calls:
                    msg["tool_calls"] = tool_calls
                if reasoning:
                    msg["reasoning_content"] = "\n".join(reasoning)
                trace.append(msg)
                continue

            if role_raw == "tool":
                result = _parse_tool_result(value)
                msg = {
                    "role": "tool",
                    "content": result.get("content", value),
                    "ts": ts,
                }
                if result.get("tool_call_id"):
                    msg["tool_call_id"] = result["tool_call_id"]
                if result.get("name"):
                    msg["name"] = result["name"]
                trace.append(msg)
                continue

            trace.append({"role": role_raw, "content": value, "ts": ts})

    trace_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in trace) + ("\n" if trace else ""),
        encoding="utf-8",
    )


def _select_trajectory_path(worktree: Path) -> Path | None:
    """Return the best available run_agent trajectory artifact.

    run_agent.py writes successful conversations to ``trajectory_samples.jsonl``
    and failed/incomplete conversations to ``failed_trajectories.jsonl``. Failed
    conversations can still contain valid tool calls that verifiers need when
    scoring model behavior, so do not collapse them into empty traces.
    """

    for name in ("trajectory_samples.jsonl", "failed_trajectories.jsonl"):
        path = worktree / name
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


INFRA_ERROR_PATTERNS = (
    "APIConnectionError",
    "API call failed after",
    "Connection error.",
    "EngineDeadError",
    "HTTP Error 5",
    "ReadTimeout",
    "ConnectTimeout",
    "RemoteProtocolError",
)


def _detect_infra_error(
    *,
    completed: subprocess.CompletedProcess[str],
    log_path: Path,
    selected_trajectory_path: Path | None,
) -> str | None:
    """Return an infra-error reason for transport/engine failures.

    If run_agent never produced a trajectory, running the task verifier turns an
    endpoint outage into a misleading model failure such as "model did not use
    terminal". Classify those as INFRA_ERROR so the run is visibly invalid and
    resumable instead of poisoning model scores.
    """
    if completed.returncode == 124:
        return "agent subprocess timed out before producing a trajectory"
    if selected_trajectory_path is not None:
        return None
    if completed.returncode == 0:
        return None
    text = log_path.read_text(encoding="utf-8", errors="ignore") if log_path.exists() else ""
    for pattern in INFRA_ERROR_PATTERNS:
        if pattern in text:
            return f"infrastructure/API failure: {pattern}"
    return None


def _load_tasks(repo_root: Path, task_ids: list[str] | None) -> list[TaskSpec]:
    discovered = _discover_tasks(repo_root)
    if task_ids is None:
        return [_load_task(path) for path in discovered]
    if not task_ids:
        raise SystemExit("No tasks selected (empty --task list)")

    tasks_by_id = {_load_task(path).id: _load_task(path) for path in discovered}
    missing = [tid for tid in task_ids if tid not in tasks_by_id]
    if missing:
        raise SystemExit(f"Unknown task(s): {', '.join(missing)}")
    return [tasks_by_id[tid] for tid in task_ids]


def _build_task_query(task: TaskSpec, worktree: Path) -> str:
    """Add an explicit benchmark-worktree guard to the user task prompt."""

    return (
        f"Benchmark worktree: {worktree}\n"
        "Use this directory as the current workspace for all relative file and terminal operations. "
        "Prefer relative paths. Do not inspect or modify the HermesBench source checkout unless the task explicitly asks for it.\n\n"
        f"Task: {task.prompt}"
    )


def _run_hermes(
    *,
    hermes_path: Path,
    worktree: Path,
    isolated_home: Path,
    task: TaskSpec,
    model: str,
    base_url: str,
    toolsets: str,
    max_turns: int,
    log_path: Path,
    timeout_seconds: int,
    use_hermes_config: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "HOME": str(isolated_home),
        "HERMES_HOME": str(Path.home() / ".hermes"),
        # Hermes tools resolve relative file paths and terminal commands from
        # TERMINAL_CWD, not necessarily the subprocess cwd. Keep every task
        # inside its isolated benchmark worktree; otherwise models can discover
        # and mutate the repository fixtures in the parent checkout.
        "TERMINAL_CWD": str(worktree),
        "PWD": str(worktree),
        "PYTHONUNBUFFERED": "1",
        "TERM": "xterm-256color",
    }
    # Local OpenAI-compatible servers (vLLM, llama.cpp, etc.) often do not
    # require authentication, but Hermes Agent's run_agent.py still needs an
    # explicit API key argument to stay on the OpenAI-compatible provider path.
    # If this is omitted, runs can fall back to the user's configured Hermes
    # provider even when --base_url is supplied, producing misleading 401/403
    # failures against the wrong endpoint. Use a harmless placeholder when the
    # caller has not exported OPENAI_API_KEY.
    api_key = os.environ.get("OPENAI_API_KEY") or "dummy"
    if not use_hermes_config and base_url:
        env["OPENAI_BASE_URL"] = base_url
        env["OPENAI_MODEL"] = model
        env["OPENAI_API_KEY"] = api_key
    cmd = [
        hermes_python(hermes_path),
        "-u",
        str(hermes_path / "run_agent.py"),
        "--model",
        model,
        f"--enabled_toolsets={toolsets}",
        "--save_trajectories",
        "--max_turns",
        str(max_turns),
        "--query",
        _build_task_query(task, worktree),
    ]
    if not use_hermes_config and base_url:
        cmd.extend(["--base_url", base_url, "--api_key", api_key])
    log_file = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        cwd=worktree,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            log_file.write(line)
            log_file.flush()
        return subprocess.CompletedProcess(cmd, proc.wait(timeout=timeout_seconds), "", "")
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            rest = proc.stdout.read(65536)
        except Exception:
            rest = ""
        if rest:
            log_file.write(rest)
            log_file.flush()
        return subprocess.CompletedProcess(cmd, 124, "", rest)
    finally:
        log_file.close()


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _load_existing_summary(summary_path: Path) -> dict[str, Any] | None:
    if not summary_path.is_file():
        return None
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _completed_tasks_by_id(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in summary.get("tasks") or []:
        if not isinstance(row, dict):
            continue
        task_id = row.get("task_id")
        status = row.get("status")
        if task_id and status in FINAL_TASK_STATUSES:
            out[str(task_id)] = row
    return out


def _merge_task_rows(
    selected_ids: list[str],
    prior: dict[str, dict[str, Any]],
    fresh: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fresh_by_id = {str(row["task_id"]): row for row in fresh}
    merged: list[dict[str, Any]] = []
    for tid in selected_ids:
        if tid in fresh_by_id:
            merged.append(fresh_by_id[tid])
        elif tid in prior:
            merged.append(prior[tid])
    return merged


def tasks_to_run_with_resume(
    tasks: list[TaskSpec],
    *,
    completed_by_id: dict[str, dict[str, Any]],
) -> tuple[list[TaskSpec], list[dict[str, Any]]]:
    """Return tasks still to execute and rows skipped from a prior summary."""
    pending: list[TaskSpec] = []
    skipped: list[dict[str, Any]] = []
    for task in tasks:
        prior = completed_by_id.get(task.id)
        if prior is not None:
            skipped.append(prior)
        else:
            pending.append(task)
    return pending, skipped


def run_real_benchmark(
    *,
    repo_root: Path | None = None,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    toolsets: str = DEFAULT_TOOLSETS,
    run_id: str | None = None,
    task_ids: list[str] | None = None,
    max_turns: int | None = None,
    timeout_overhead: int = 30,
    hermes_agent_path: Path | None = None,
    use_hermes_config: bool = False,
    resume: bool = False,
) -> int:
    root = (repo_root or REPO).resolve()
    rid = run_id or f"real_model_{_now()}_{uuid.uuid4().hex[:8]}"

    tasks = _load_tasks(root, task_ids)
    if not tasks:
        raise SystemExit("No tasks selected")

    selected_ids = [t.id for t in tasks]
    results_root = root / "results" / rid
    traces_root = root / "traces" / rid
    summary_path = results_root / "summary.json"

    prior_summary = _load_existing_summary(summary_path) if resume else None
    completed_by_id = _completed_tasks_by_id(prior_summary) if prior_summary else {}
    pending_tasks, skipped_rows = tasks_to_run_with_resume(
        tasks, completed_by_id=completed_by_id
    )

    hermes_path = hermes_agent_path.resolve() if hermes_agent_path else find_hermes_agent()
    hermes_sha = get_hermes_sha(hermes_path)
    hermes_version = get_hermes_version(hermes_path)

    results_root.mkdir(parents=True, exist_ok=True)
    traces_root.mkdir(parents=True, exist_ok=True)

    if prior_summary and resume:
        summary = dict(prior_summary)
        summary.update(
            {
                "run_id": rid,
                "model": model,
                "base_url": base_url,
                "toolsets": toolsets,
                "hermes_path": str(hermes_path),
                "hermes_sha": hermes_sha,
                "hermes_version": hermes_version,
                "task_count": len(tasks),
                "resumed": True,
                "skipped_task_count": len(skipped_rows),
            }
        )
    else:
        summary = {
            "run_id": rid,
            "model": model,
            "base_url": base_url,
            "toolsets": toolsets,
            "hermes_path": str(hermes_path),
            "hermes_sha": hermes_sha,
            "hermes_version": hermes_version,
            "task_count": len(tasks),
            "tasks": [],
        }

    fresh_rows: list[dict[str, Any]] = []

    for task in pending_tasks:
        task_started = time.time()
        task_dir = traces_root / task.id
        task_dir.mkdir(parents=True, exist_ok=True)
        worktree = worktree_setup.setup_worktree(task, run_id=rid, repo_root=root)
        isolated_home = (
            Path.home() / ".hermes" / "tmp" / f"hb-home-{rid}-{task.id.replace('/', '_')}"
        )
        isolated_home.mkdir(parents=True, exist_ok=True)

        raw_log_path = task_dir / "run_agent.log"
        trajectory_path = worktree / "trajectory_samples.jsonl"
        trace_path = task_dir / "trace.jsonl"
        verifier_path = task_dir / "verifier_result.json"

        completed = _run_hermes(
            hermes_path=hermes_path,
            worktree=worktree,
            isolated_home=isolated_home,
            task=task,
            model=model,
            base_url=base_url,
            toolsets=toolsets,
            max_turns=max_turns or task.max_turns,
            log_path=raw_log_path,
            timeout_seconds=task.timeout_seconds + timeout_overhead,
            use_hermes_config=use_hermes_config,
        )

        selected_trajectory_path = _select_trajectory_path(worktree)
        if selected_trajectory_path is not None:
            _trajectory_to_trace(selected_trajectory_path, trace_path)
        else:
            trace_path.write_text("", encoding="utf-8")

        infra_reason = _detect_infra_error(
            completed=completed,
            log_path=raw_log_path,
            selected_trajectory_path=selected_trajectory_path,
        )
        if infra_reason:
            verifier_result = VerifierResult(
                status=VerifierStatus.INFRA_ERROR,
                score=0.0,
                reason=infra_reason,
                details={"exit_code": completed.returncode},
            )
        else:
            verifier_result = _run_verifier(task, worktree, trace_path)
        verifier_payload = {
            "task_id": task.id,
            "difficulty": task.difficulty,
            **asdict(verifier_result),
        }
        _write_json(verifier_path, verifier_payload)

        elapsed = time.time() - task_started

        row = {
            "task_id": task.id,
            "name": task.name,
            "difficulty": task.difficulty,
            "status": verifier_result.status.value,
            "score": verifier_result.score,
            "reason": verifier_result.reason,
            "elapsed_seconds": elapsed,
            "exit_code": completed.returncode,
            "worktree": str(worktree),
            "raw_log": str(raw_log_path),
            "trajectory": str(selected_trajectory_path or trajectory_path),
            "trajectory_source": selected_trajectory_path.name if selected_trajectory_path else None,
            "trace": str(trace_path),
            "verifier_result": str(verifier_path),
        }
        fresh_rows.append(row)

        _write_json(results_root / f"{task.id.replace('/', '_')}.json", row)

    summary["tasks"] = _merge_task_rows(selected_ids, completed_by_id, fresh_rows)

    passed = sum(1 for item in summary["tasks"] if item["status"] == "PASS")
    infra_errors = sum(1 for item in summary["tasks"] if item["status"] == "INFRA_ERROR")
    summary["passed"] = passed
    summary["infra_errors"] = infra_errors
    summary["failed"] = sum(1 for item in summary["tasks"] if item["status"] == "FAIL")
    summary["pass_rate"] = passed / len(summary["tasks"]) if summary["tasks"] else 0.0
    summary["valid_task_count"] = len(summary["tasks"]) - infra_errors
    summary["valid_pass_rate"] = (
        passed / summary["valid_task_count"] if summary["valid_task_count"] else 0.0
    )
    _write_json(results_root / "summary.json", summary)

    return 0 if summary["failed"] == 0 and infra_errors == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run hermesbench tasks with the real Hermes Agent model path."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--toolsets", default=DEFAULT_TOOLSETS)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--tasks", nargs="*", help="Task IDs to run. Omit to run all tasks.")
    parser.add_argument("--max-turns", type=int, default=None, help="Override per-task max turns.")
    parser.add_argument(
        "--timeout-overhead", type=int, default=30, help="Extra seconds added to each task timeout."
    )
    parser.add_argument(
        "--hermes-agent-path", type=Path, default=None, help="Override Hermes Agent checkout path."
    )
    parser.add_argument(
        "--use-hermes-config",
        action="store_true",
        help="Use ~/.hermes/config.yaml provider (e.g. xai-oauth); omit base_url and OPENAI_* env.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="With --run-id, skip tasks already PASS/FAIL in results/<run_id>/summary.json.",
    )
    args = parser.parse_args()

    return run_real_benchmark(
        repo_root=args.repo_root.resolve(),
        model=args.model,
        base_url=args.base_url,
        toolsets=args.toolsets,
        run_id=args.run_id,
        task_ids=args.tasks if args.tasks else None,
        max_turns=args.max_turns,
        timeout_overhead=args.timeout_overhead,
        hermes_agent_path=args.hermes_agent_path,
        use_hermes_config=args.use_hermes_config,
        resume=bool(args.resume and args.run_id),
    )


if __name__ == "__main__":
    raise SystemExit(main())
