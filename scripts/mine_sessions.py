#!/usr/bin/env python3
"""Mine hermes-agent session data for training quality examples.

Scans all session files, extracts tool call patterns, scores quality,
deduplicates, and categorizes by benchmark task type.

Usage:
    python3 scripts/mine_sessions.py --output results/training_data/mined_sessions.jsonl
"""
from __future__ import annotations
import json, os, glob, hashlib, argparse
from pathlib import Path
from collections import Counter, defaultdict


def load_session_messages(filepath: str) -> tuple[list[dict], dict]:
    """Load messages from a session file (JSON or JSONL)."""
    meta = {}
    try:
        if filepath.endswith(".jsonl"):
            # Could be one-blob export or per-message JSONL
            with open(filepath) as f:
                first_line = f.readline().strip()
                if not first_line:
                    return [], meta
                data = json.loads(first_line)
                if "messages" in data:
                    # One-blob export
                    meta = {k: v for k, v in data.items() if k != "messages"}
                    return data["messages"], meta
                else:
                    # Per-message JSONL
                    msgs = [data]
                    for line in f:
                        line = line.strip()
                        if line:
                            msgs.append(json.loads(line))
                    return msgs, meta
        else:
            with open(filepath) as f:
                data = json.load(f)
                if isinstance(data, dict) and "messages" in data:
                    meta = {k: v for k, v in data.items() if k != "messages"}
                    return data["messages"], meta
    except Exception:
        pass
    return [], meta


def score_session(messages: list[dict]) -> dict:
    """Score a session for training quality."""
    tools = [tc for m in messages for tc in (m.get("tool_calls") or [])]
    tool_names = [t.get("function", {}).get("name", "") for t in tools]

    roles = [m.get("role") for m in messages]
    has_pattern = "user" in roles and "assistant" in roles and "tool" in roles

    successful = sum(1 for m in messages if m.get("role") == "tool"
                    and "error" not in str(m.get("content", "") or "").lower()[:200])

    diversity = len(set(tool_names))

    return {
        "has_pattern": has_pattern,
        "successful_tools": successful,
        "diversity": diversity,
        "message_count": len(messages),
        "tool_count": len(tool_names),
        "quality": min(successful * diversity, 100),
    }


def dedup_hash(messages: list[dict]) -> str:
    """Hash first 5 tool calls for deduplication."""
    tools = []
    for m in messages:
        for tc in (m.get("tool_calls") or []):
            name = tc.get("function", {}).get("name", "")
            args = tc.get("function", {}).get("arguments", "")[:100]
            tools.append(f"{name}:{args}")
    return hashlib.md5("|".join(tools[:5]).encode()).hexdigest()


def categorize_session(messages: list[dict]) -> list[str]:
    """Categorize session by tool patterns matching benchmark tasks."""
    tool_names = set()
    for m in messages:
        for tc in (m.get("tool_calls") or []):
            tool_names.add(tc.get("function", {}).get("name", ""))

    categories = []
    if "terminal" in tool_names:
        categories.append("terminal")
    if "read_file" in tool_names:
        categories.append("read_file")
    if "patch" in tool_names:
        categories.append("patch")
    if "search_files" in tool_names:
        categories.append("search")
    if "write_file" in tool_names:
        categories.append("write")
    if "process" in tool_names:
        categories.append("process_mgmt")
    if "todo" in tool_names:
        categories.append("todo")
    if "execute_code" in tool_names:
        categories.append("execute_code")
    if "web_search" in tool_names or "web_extract" in tool_names:
        categories.append("web_lookup")
    if "memory" in tool_names:
        categories.append("memory")

    # Check for error recovery
    for m in messages:
        content = str(m.get("content", "") or "").lower()
        if m.get("role") == "tool" and ("error" in content[:200] or "traceback" in content[:200]):
            categories.append("error_recovery")
            break

    return categories


def fits_budget(messages: list[dict], max_chars: int = 16384) -> bool:
    """Check if messages fit within token budget (~4 chars/token)."""
    total = sum(
        len(m.get("content", "") or "") +
        len(json.dumps(m.get("tool_calls", []) or []))
        for m in messages
    )
    return total <= max_chars


def extract_segment(messages: list[dict], max_chars: int = 16384) -> list[dict]:
    """For long sessions, extract from first user message up to budget."""
    start = 0
    for i, m in enumerate(messages):
        if m.get("role") == "user":
            start = i
            break
    total = 0
    for i in range(start, len(messages)):
        msg_chars = len(messages[i].get("content", "") or "")
        msg_chars += len(json.dumps(messages[i].get("tool_calls", []) or []))
        if total + msg_chars > max_chars:
            return messages[start:i]
        total += msg_chars
    return messages[start:]


def main():
    parser = argparse.ArgumentParser(description="Mine hermes session data")
    parser.add_argument("--sessions-dir", default=os.path.expanduser("~/.hermes/sessions"))
    parser.add_argument("--output", default="results/training_data/mined_sessions.jsonl")
    parser.add_argument("--max-chars", type=int, default=16384)
    args = parser.parse_args()

    sessions_dir = args.sessions_dir
    jsonl_files = sorted(glob.glob(f"{sessions_dir}/*.jsonl"))
    json_files = sorted(glob.glob(f"{sessions_dir}/session_*.json"))

    all_files = jsonl_files + json_files
    print(f"Scanning {len(all_files)} session files...")

    seen_hashes = set()
    examples = []
    stats = Counter()

    for filepath in all_files:
        messages, meta = load_session_messages(filepath)
        if not messages:
            continue

        score = score_session(messages)
        if not score["has_pattern"] or score["successful_tools"] < 1:
            continue

        # Dedup
        h = dedup_hash(messages)
        if h in seen_hashes:
            stats["deduped"] += 1
            continue
        seen_hashes.add(h)

        # Token budget
        if not fits_budget(messages, args.max_chars):
            messages = extract_segment(messages, args.max_chars)
            stats["truncated"] += 1

        categories = categorize_session(messages)

        example = {
            "messages": [
                {"role": m.get("role"), "content": m.get("content"),
                 "tool_calls": m.get("tool_calls"),
                 "tool_call_id": m.get("tool_call_id")}
                for m in messages
            ],
            "loss_mask": [1 if m.get("role") == "assistant" else 0 for m in messages],
            "source": os.path.basename(filepath),
            "model": meta.get("model", "unknown"),
            "categories": categories,
            "quality_score": score["quality"],
            "dedup_hash": h,
        }
        examples.append(example)
        for cat in categories:
            stats[cat] += 1
        stats["total"] += 1

    # Sort by quality
    examples.sort(key=lambda x: x["quality_score"], reverse=True)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print(f"\nResults: {len(examples)} quality examples")
    print(f"Deduped: {stats['deduped']}, Truncated: {stats['truncated']}")
    print(f"\nBy category:")
    for cat, count in stats.most_common():
        if cat not in ("total", "deduped", "truncated"):
            print(f"  {cat:<20} {count:>4}")
    print(f"\nOutput: {args.output}")


if __name__ == "__main__":
    main()
