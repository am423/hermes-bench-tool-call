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
from hermesbench.types import TaskSpec

REPO = Path(__file__).resolve().parent.parent


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
        "PYTHONUNBUFFERED": "1",
        "TERM": "xterm-256color",
    }
    if not use_hermes_config and base_url:
        env["OPENAI_BASE_URL"] = base_url
        env["OPENAI_MODEL"] = model
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
        task.prompt,
    ]
    if not use_hermes_config and base_url:
        cmd.extend(["--base_url", base_url])
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
) -> int:
    root = (repo_root or REPO).resolve()
    rid = run_id or f"real_model_{_now()}_{uuid.uuid4().hex[:8]}"

    tasks = _load_tasks(root, task_ids)
    if not tasks:
        raise SystemExit("No tasks selected")

    hermes_path = hermes_agent_path.resolve() if hermes_agent_path else find_hermes_agent()
    hermes_sha = get_hermes_sha(hermes_path)
    hermes_version = get_hermes_version(hermes_path)

    results_root = root / "results" / rid
    traces_root = root / "traces" / rid
    results_root.mkdir(parents=True, exist_ok=True)
    traces_root.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
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

    for task in tasks:
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

        if trajectory_path.exists():
            _trajectory_to_trace(trajectory_path, trace_path)
        else:
            trace_path.write_text("", encoding="utf-8")

        verifier_result = _run_verifier(task, worktree, trace_path)
        verifier_payload = {
            "task_id": task.id,
            "difficulty": task.difficulty,
            **asdict(verifier_result),
        }
        _write_json(verifier_path, verifier_payload)

        elapsed = time.time() - task_started

        summary["tasks"].append(
            {
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
                "trajectory": str(trajectory_path),
                "trace": str(trace_path),
                "verifier_result": str(verifier_path),
            }
        )

        _write_json(results_root / f"{task.id.replace('/', '_')}.json", summary["tasks"][-1])

    passed = sum(1 for item in summary["tasks"] if item["status"] == "PASS")
    summary["passed"] = passed
    summary["failed"] = len(summary["tasks"]) - passed
    summary["pass_rate"] = passed / len(summary["tasks"]) if summary["tasks"] else 0.0
    _write_json(results_root / "summary.json", summary)

    return 0 if summary["failed"] == 0 else 1


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
    )


if __name__ == "__main__":
    raise SystemExit(main())
