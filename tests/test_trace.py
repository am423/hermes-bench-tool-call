"""Q52: tests that the trace reader correctly normalizes the state.db format.

The wire format is documented in docs/trace_format_reconciliation.md.
"""

from __future__ import annotations

import json
from pathlib import Path

from hermesbench.trace import read_trace


def test_read_trace_skips_blank_lines(tmp_path: Path) -> None:
    p = tmp_path / "x.jsonl"
    p.write_text(
        json.dumps({"role": "user", "content": "hi", "ts": 0.0}) + "\n"
        "\n" + json.dumps({"role": "assistant", "content": "hello", "ts": 1.0}) + "\n"
    )
    trace = read_trace(p)
    assert len(trace) == 2


def test_read_trace_normalizes_tool_message(tmp_path: Path) -> None:
    """Tool messages have no `name` field in state.db; reconstruct from [name] prefix."""
    p = tmp_path / "x.jsonl"
    p.write_text(
        json.dumps(
            {
                "role": "tool",
                "tool_call_id": "call_abc",
                "content": "[read_file] read /foo.py (123 chars)\n<contents>",
                "ts": 2.0,
            }
        )
    )
    trace = read_trace(p)
    assert trace[0]["name"] == "read_file"
    assert trace[0]["tool_call_id"] == "call_abc"


def test_read_trace_preserves_tool_calls(tmp_path: Path) -> None:
    p = tmp_path / "x.jsonl"
    p.write_text(
        json.dumps(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path":"/x"}'},
                    }
                ],
                "ts": 0.0,
            }
        )
    )
    trace = read_trace(p)
    assert trace[0]["tool_calls"][0]["function"]["arguments"] == '{"path":"/x"}'


def test_read_trace_preserves_reasoning_content(tmp_path: Path) -> None:
    p = tmp_path / "x.jsonl"
    p.write_text(
        json.dumps(
            {
                "role": "assistant",
                "content": "Done.",
                "reasoning_content": "I should think first.",
                "ts": 0.0,
            }
        )
    )
    trace = read_trace(p)
    assert trace[0]["reasoning_content"] == "I should think first."


def test_read_trace_preserves_token_ids(tmp_path: Path) -> None:
    """Q45: prompt_token_ids and completion_token_ids are preserved for SFT loss masks."""
    p = tmp_path / "x.jsonl"
    p.write_text(
        json.dumps(
            {
                "role": "assistant",
                "content": "x",
                "prompt_token_ids": [1, 2, 3],
                "completion_token_ids": [4, 5, 6, 7],
                "ts": 0.0,
            }
        )
    )
    trace = read_trace(p)
    assert trace[0]["prompt_token_ids"] == [1, 2, 3]
    assert trace[0]["completion_token_ids"] == [4, 5, 6, 7]
