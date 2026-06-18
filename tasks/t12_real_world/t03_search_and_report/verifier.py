"""Verifier for t12_real_world/t03_search_and_report.

Model searches for TODO and reports results.
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
    used_search = any(
        (tc.get("function") or {}).get("name") == "search_files"
        for msg in trace if msg.get("role") == "assistant"
        for tc in (msg.get("tool_calls") or [])
    )

    if not used_search:
        # Check if terminal was used with grep
        for msg in trace:
            if msg.get("role") == "assistant":
                for tc in (msg.get("tool_calls") or []):
                    args = tc.get("function", {}).get("arguments", "")
                    if "grep" in str(args) or "TODO" in str(args):
                        used_search = True
                        break

    if not used_search:
        return VerifierResult(status="FAIL", reason="model did not search")

    # Check final response mentions results
    for msg in reversed(trace):
        if msg.get("role") == "assistant" and msg.get("content"):
            if "todo" in msg["content"].lower() or "no " in msg["content"].lower():
                return VerifierResult(status="PASS", reason="ok")
            break

    return VerifierResult(status="FAIL", reason="model did not report search results")
