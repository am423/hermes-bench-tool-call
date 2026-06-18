"""Verifier for t12_real_world/t02_error_recovery.

Model tries to read a missing file, then recovers by reading the existing one.
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
    read_calls = []
    for msg in trace:
        if msg.get("role") == "assistant":
            for tc in (msg.get("tool_calls") or []):
                if (tc.get("function") or {}).get("name") == "read_file":
                    import json
                    args = tc.get("function", {}).get("arguments", "{}")
                    try:
                        if isinstance(args, str):
                            args = json.loads(args)
                    except:
                        args = {}
                    path = str(args.get("path", ""))
                    read_calls.append(path)

    if not read_calls:
        return VerifierResult(status="FAIL", reason="model did not use read_file")

    # Must have attempted the missing path AND then read an existing file
    attempted_missing = any("nonexistent" in p for p in read_calls)
    attempted_real = any("nonexistent" not in p for p in read_calls)

    if attempted_missing and attempted_real:
        return VerifierResult(status="PASS", reason="ok (recovered from missing file)")
    if len(read_calls) >= 2:
        return VerifierResult(status="PASS", reason="ok (multiple read attempts)")

    return VerifierResult(status="FAIL", reason="model did not recover from missing file")
