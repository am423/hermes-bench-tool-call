"""hermesbench/sft_export.py — export traces to SFT-ready JSONL."""

from __future__ import annotations

import json
from pathlib import Path


def export_sft(run_paths: list[str], out_path: str) -> int:
    """Export all traces from run dirs to a single SFT JSONL.

    Each example has messages, loss_mask (0 for non-assistant, 1 for assistant),
    source path, and task_id.
    """
    examples = []
    for run_path in run_paths:
        p = Path(run_path)
        for trace_file in p.rglob("trace.jsonl"):
            messages = []
            with open(trace_file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    messages.append(msg)

            if not messages:
                continue

            formatted_msgs = []
            loss_mask = []
            for m in messages:
                role = m.get("role", "user")
                content = m.get("content", "")
                formatted_msgs.append({"role": role, "content": content})
                loss_mask.append(1 if role == "assistant" else 0)

            task_id = ""
            parts = trace_file.parts
            for i, part in enumerate(parts):
                if part.startswith("t") and i > 0 and "results" in str(parts[i - 1]):
                    task_id = part
                    break

            examples.append(
                {
                    "messages": formatted_msgs,
                    "loss_mask": loss_mask,
                    "source": str(trace_file),
                    "task_id": task_id,
                }
            )

    with open(out_path, "w") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    return len(examples)
