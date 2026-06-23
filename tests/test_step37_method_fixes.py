from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from hermesbench.backend.worktree import setup_worktree
from hermesbench.cli import _load_task
from hermesbench.run_real import _detect_infra_error

REPO = Path(__file__).resolve().parent.parent


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_big_file_fixture_exists_for_paginated_read() -> None:
    text = (REPO / "fixtures/small_repo/big_file.py").read_text(encoding="utf-8")
    assert "def generated_function_001" in text
    assert len(text.splitlines()) >= 150


def test_big_block_fixture_starts_without_bar() -> None:
    text = (REPO / "fixtures/small_repo/big_block.py").read_text(encoding="utf-8")
    assert "def method_10" in text
    assert "def bar" not in text


def test_setup_worktree_recreates_stale_task_dir(tmp_path: Path) -> None:
    task = _load_task(REPO / "tasks/t03_patch_edit/t04_multiline")
    stale = tmp_path / "run1" / task.id / "worktree"
    stale.mkdir(parents=True)
    (stale / "stale.txt").write_text("old", encoding="utf-8")
    (stale / "big_block.py").write_text("class Foo:\n    def bar(self):\n        return 42\n", encoding="utf-8")

    worktree = setup_worktree(task, run_id="run1", repo_root=REPO, traces_root=tmp_path)

    assert not (worktree / "stale.txt").exists()
    text = (worktree / "big_block.py").read_text(encoding="utf-8")
    assert "def method_10" in text
    assert "def bar" not in text


def test_humaneval_5_verifier_reuses_prompt_imports_for_full_function() -> None:
    mod = _load_module(REPO / "tasks/t13_humaneval_micro/humaneval_5/verifier.py")
    prob = __import__("json").loads(
        (REPO / "fixtures/humaneval_micro/humaneval_5/humaneval.json").read_text(encoding="utf-8")
    )
    completion = """```python
def intersperse(numbers: List[int], delimeter: int) -> List[int]:
    result = []
    for i, num in enumerate(numbers):
        result.append(num)
        if i != len(numbers) - 1:
            result.append(delimeter)
    return result
```"""

    ok, reason = mod._run_humaneval_check(
        prob["prompt"], completion, prob["test"], prob["entry_point"]
    )

    assert ok, reason


def test_prompt_verifier_alignment_for_prior_step37_failures() -> None:
    glob_prompt = (REPO / "tasks/t04_search_grep/t02_glob/task.yaml").read_text(encoding="utf-8")
    kill_prompt = (REPO / "tasks/t06_process_mgmt/t02_kill/task.yaml").read_text(encoding="utf-8")
    poll_prompt = (REPO / "tasks/t06_process_mgmt/t03_poll/task.yaml").read_text(encoding="utf-8")
    zombie_prompt = (REPO / "tasks/t06_process_mgmt/t05_zombie/task.yaml").read_text(encoding="utf-8")
    todo_prompt = (REPO / "tasks/t07_todo_plan/t02_update/task.yaml").read_text(encoding="utf-8")
    no_result_prompt = (REPO / "tasks/t09_web_lookup/t03_no_result/task.yaml").read_text(encoding="utf-8")

    assert "search_files" in glob_prompt and "file_glob" in glob_prompt
    assert "process` tool" in kill_prompt and 'action: "kill"' in kill_prompt
    assert "process` tool" in poll_prompt and 'action: "poll"' in poll_prompt
    assert "ps -eo pid,ppid,stat,comm" in zombie_prompt and "Do not use `ps aux`" in zombie_prompt
    assert "todo` tool" in todo_prompt and "completed" in todo_prompt
    assert "web_search" in no_result_prompt


def test_detect_infra_error_for_context_overflow_crash_without_trajectory(tmp_path: Path) -> None:
    log = tmp_path / "run_agent.log"
    log.write_text(
        "BadRequestError [HTTP 400]\nmaximum context length\n"
        "Context length exceeded and cannot compress further.\n"
        "KeyError: 'final_response'\n",
        encoding="utf-8",
    )
    completed = subprocess.CompletedProcess(["run_agent.py"], 1, "", "")

    reason = _detect_infra_error(
        completed=completed,
        log_path=log,
        selected_trajectory_path=None,
    )

    assert reason is not None
    assert "infrastructure/API failure" in reason
