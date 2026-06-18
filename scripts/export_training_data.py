#!/usr/bin/env python3
"""Export session data to Unsloth/HF-compatible training format.

Reads mined session data and produces OpenAI messages format JSONL
with tool_calls and loss masks, filtered by token budget.

Usage:
    python3 scripts/export_training_data.py --input results/training_data/mined_sessions.jsonl --output results/training_data/sft_traces.jsonl
"""
from __future__ import annotations
import json, os, argparse
from pathlib import Path


MAX_CHARS = 16384  # ~4096 tokens at 4 chars/token


def to_openai_format(mined_example: dict) -> dict:
    """Convert mined example to clean OpenAI messages format."""
    messages = []
    for i, msg in enumerate(mined_example["messages"]):
        role = msg.get("role", "user")
        content = msg.get("content")
        entry = {"role": role}

        if content is not None:
            entry["content"] = content
        else:
            entry["content"] = None

        # Include tool_calls for assistant messages
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.get("id", f"call_{i}"),
                    "type": "function",
                    "function": {
                        "name": tc.get("function", {}).get("name", ""),
                        "arguments": tc.get("function", {}).get("arguments", "{}"),
                    },
                }
                for tc in tool_calls
            ]

        # Include tool_call_id for tool messages
        tool_call_id = msg.get("tool_call_id")
        if tool_call_id:
            entry["tool_call_id"] = tool_call_id

        messages.append(entry)

    return {
        "messages": messages,
        "loss_mask": mined_example["loss_mask"],
        "source": mined_example["source"],
        "model": mined_example["model"],
        "tools_used": mined_example["categories"],
    }


def estimate_tokens(messages: list[dict]) -> int:
    """Estimate token count (~4 chars per token)."""
    total_chars = 0
    for m in messages:
        total_chars += len(m.get("content", "") or "")
        total_chars += len(json.dumps(m.get("tool_calls", []) or []))
    return total_chars // 4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="results/training_data/mined_sessions.jsonl")
    parser.add_argument("--output", default="results/training_data/sft_traces.jsonl")
    parser.add_argument("--max-tokens", type=int, default=4096)
    args = parser.parse_args()

    max_chars = args.max_tokens * 4

    with open(args.input) as f:
        mined = [json.loads(line) for line in f if line.strip()]

    exported = []
    stats = {"total": 0, "filtered_budget": 0, "filtered_quality": 0}

    for ex in mined:
        stats["total"] += 1

        # Quality gate: must have at least 1 successful tool call
        if ex.get("quality_score", 0) < 1:
            stats["filtered_quality"] += 1
            continue

        formatted = to_openai_format(ex)

        # Token budget
        if estimate_tokens(formatted["messages"]) > args.max_tokens:
            stats["filtered_budget"] += 1
            continue

        exported.append(formatted)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        for ex in exported:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print(f"Exported {len(exported)} examples")
    print(f"Filtered: {stats['filtered_budget']} (budget), {stats['filtered_quality']} (quality)")
    print(f"Output: {args.output}")
    print(f"Format: OpenAI messages with tool_calls + loss_mask")


if __name__ == "__main__":
    main()
