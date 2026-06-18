"""Verifier for t12_real_world/t01_multi_tool_workflow.

Model reads add.py, finds the bug (division by zero), and patches it.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class VerifierResult:
    status: Literal["PASS", "FAIL", "SKIPPED", "BUDGET_EXCEEDED", "VERIFIER_ERROR"]
    score: float = 1.0
    reason: str = ""
    details: dict = field(default_factory=dict)


def verify(worktree: Path, trace: list[dict]) -> VerifierResult:
    # Check trace for read_file + patch
    used_read = any(
        (tc.get("function") or {}).get("name") == "read_file"
        for msg in trace if msg.get("role") == "assistant"
        for tc in (msg.get("tool_calls") or [])
    )
    used_patch = any(
        (tc.get("function") or {}).get("name") == "patch"
        for msg in trace if msg.get("role") == "assistant"
        for tc in (msg.get("tool_calls") or [])
    )

    if not used_read:
        return VerifierResult(status="FAIL", reason="model did not use read_file")

    # Check worktree: broken_divide.py should be fixed (no bare division)
    target = worktree / "broken_divide.py"
    if target.exists():
        content = target.read_text()
        if "ValueError" in content or "ZeroDivisionError" in content or "b == 0" in content or "b is 0" in content:
            return VerifierResult(status="PASS", reason="ok (worktree shows fix)")

    if used_patch:
        return VerifierResult(status="PASS", reason="ok (patch applied)")

    return VerifierResult(status="FAIL", reason="model did not fix the bug")
