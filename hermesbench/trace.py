"""Trace reader: parse the jsonl trace from a hermes session into a list of messages.

This is hermesbench-specific — it implements the wire format
reconciled in `docs/trace_format_reconciliation.md` (Q52).

Stdlib only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_trace(path: Path) -> list[dict[str, Any]]:
    """Read a trace jsonl into a list of normalized message dicts.

    Each returned dict has at minimum: role, content, ts.
    Assistant messages may have: tool_calls, reasoning_content,
    prompt_token_ids, completion_token_ids.
    Tool messages may have: tool_call_id, name (reconstructed).
    """
    out: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append(_normalize(msg))
    return out


def _normalize(msg: dict[str, Any]) -> dict[str, Any]:
    """Normalize a hermes state.db / hermes-agent message into our schema.

    Key reconciliations (Q52):
    - tool_call id format: 'call_<22-char-base62>' (preserved as-is)
    - tool message has no `name` field; reconstruct from `[<name>]` prefix
    - tool arguments are JSON-encoded strings inside `function.arguments`
    """
    out = {"role": msg.get("role"), "content": msg.get("content"), "ts": msg.get("ts", 0.0)}
    if msg.get("tool_calls"):
        out["tool_calls"] = msg["tool_calls"]
    if "tool_call_id" in msg:
        out["tool_call_id"] = msg["tool_call_id"]
    if "reasoning_content" in msg:
        out["reasoning_content"] = msg["reasoning_content"]
    if "prompt_token_ids" in msg:
        out["prompt_token_ids"] = msg["prompt_token_ids"]
    if "completion_token_ids" in msg:
        out["completion_token_ids"] = msg["completion_token_ids"]
    if "token_count" in msg:
        out["token_count"] = msg["token_count"]
    # Reconstruct `name` on tool results from the `[<name>]` prefix
    if msg.get("role") == "tool" and msg.get("content"):
        c = msg["content"]
        if isinstance(c, str) and c.startswith("["):
            end = c.find("]")
            if end > 0:
                out["name"] = c[1:end]
    return out
