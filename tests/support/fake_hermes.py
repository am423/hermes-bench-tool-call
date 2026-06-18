"""Fake hermes-agent for optional pipeline tests only — not used by `hermesbench run`."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def emit(
    role: str,
    content: str = "",
    tool_calls: list | None = None,
    reasoning: str = "",
    tool_call_id: str = "",
    tool_name: str = "",
    ts: float = 0.0,
    **extras,
) -> None:
    msg = {"role": role, "ts": ts}
    if content:
        msg["content"] = content
    if tool_calls:
        msg["tool_calls"] = tool_calls
    if reasoning:
        msg["reasoning_content"] = reasoning
    if tool_call_id:
        msg["tool_call_id"] = tool_call_id
    if tool_name:
        msg["name"] = tool_name
    msg.update(extras)


def make_tool_call(name: str, args: dict, call_id: str) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def main() -> int:
    prompt = sys.stdin.readline().strip()
    t = time.time()
    emit("system", content="You are hermes.", ts=t)
    emit("user", content=prompt, ts=t + 0.1)
    t += 0.2
    worktree = Path(os.environ.get("HERMES_TMUX_WORKTREE", "."))
    if "echo" in prompt.lower():
        emit(
            "assistant",
            reasoning="I'll run the echo command.",
            tool_calls=[
                make_tool_call("terminal", {"command": "echo hello-hermesbench"}, "call_e1")
            ],
            ts=t,
        )
        emit(
            "tool",
            tool_call_id="call_e1",
            tool_name="terminal",
            content="[terminal] hello-hermesbench",
            ts=t + 0.3,
        )
        emit("assistant", content="Command output:\n```\nhello-hermesbench\n```", ts=t + 0.4)
    elif "broken_divide" in prompt.lower():
        emit(
            "assistant",
            reasoning="patch",
            tool_calls=[
                make_tool_call(
                    "patch",
                    {"path": "broken_divide.py", "old_string": "x", "new_string": "y"},
                    "call_p1",
                )
            ],
            ts=t,
        )
        broken_path = worktree / "broken_divide.py"
        if broken_path.exists():
            text = broken_path.read_text()
            new_text = text.replace(
                "    # Bug: no zero-division check\n    return a / b",
                "    if b == 0:\n        raise ValueError('division by zero')\n    return a / b",
            )
            if new_text != text:
                broken_path.write_text(new_text)
        emit("assistant", content="patched", ts=t + 0.4)
    else:
        emit("assistant", content=f"Acknowledged: {prompt[:200]}", ts=t)
    return 0


if __name__ == "__main__":
    sys.exit(main())
