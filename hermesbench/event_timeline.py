"""Build HyperFrames event timeline from a real-model summary.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FAMILY_ORDER = [
    ("t01_terminal_smoke", "1 terminal smoke", "Terminal Smoke"),
    ("t02_file_read", "2 file read", "File Read"),
    ("t03_patch_edit", "3 patch edit", "Patch Edit"),
    ("t04_search_grep", "4 search grep", "Search Grep"),
    ("t05_write_new", "5 write new", "Write New"),
    ("t06_process_mgmt", "6 process mgmt", "Process Mgmt"),
    ("t07_todo_plan", "7 todo plan", "Todo Plan"),
    ("t08_execute_code", "8 execute code", "Execute Code"),
    ("t09_web_lookup", "9 web lookup", "Web Lookup"),
    ("t10_memory_facts", "0 memory facts", "Memory Facts"),
    ("t11_error_recovery", "1 error recovery", "Error Recovery"),
]

# Left-panel montage blocks (multiple families may share one DOM block)
TERM_BLOCK_GROUPS: list[tuple[list[str], str]] = [
    (["t01_terminal_smoke"], "term-smoke"),
    (["t02_file_read"], "term-file-read"),
    (["t03_patch_edit"], "term-patch"),
    (["t04_search_grep", "t05_write_new"], "term-search"),
    (
        [
            "t06_process_mgmt",
            "t07_todo_plan",
            "t08_execute_code",
            "t09_web_lookup",
            "t10_memory_facts",
        ],
        "term-exec",
    ),
    (["t11_error_recovery"], "term-final"),
]


def family_for_task_id(task_id: str) -> tuple[str, str]:
    prefix = task_id.split("/")[0] if "/" in task_id else task_id
    for p, key, label in FAMILY_ORDER:
        if task_id.startswith(p) or prefix == p:
            return key, label
    return "unknown", "Other"


def short_id(task_id: str) -> str:
    return task_id.split("/")[-1] if "/" in task_id else task_id


def _build_family_segments(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_prefix: dict[str, dict[str, Any]] = {}
    for p, _key, label in FAMILY_ORDER:
        by_prefix[p] = {
            "prefix": p,
            "label": label,
            "start_sec": None,
            "end_sec": None,
        }
    for ev in events:
        tid = ev["task_id"]
        prefix = tid.split("/")[0]
        if prefix not in by_prefix:
            continue
        s = ev["start_sec"]
        e = ev["end_sec"]
        seg = by_prefix[prefix]
        if seg["start_sec"] is None or s < seg["start_sec"]:
            seg["start_sec"] = s
        if seg["end_sec"] is None or e > seg["end_sec"]:
            seg["end_sec"] = e
    out: list[dict[str, Any]] = []
    for p, _key, label in FAMILY_ORDER:
        seg = by_prefix[p]
        if seg["start_sec"] is None:
            continue
        out.append(
            {
                "prefix": p,
                "label": label,
                "start_sec": round(seg["start_sec"], 2),
                "end_sec": round(seg["end_sec"], 2),
            }
        )
    return out


def _build_term_segments(family_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_prefix = {s["prefix"]: s for s in family_segments}
    term_segments: list[dict[str, Any]] = []
    for prefixes, term_id in TERM_BLOCK_GROUPS:
        starts: list[float] = []
        ends: list[float] = []
        labels: list[str] = []
        for p in prefixes:
            if p in by_prefix:
                starts.append(by_prefix[p]["start_sec"])
                ends.append(by_prefix[p]["end_sec"])
                labels.append(by_prefix[p]["label"])
        if not starts:
            continue
        term_segments.append(
            {
                "term_id": term_id,
                "start_sec": round(min(starts), 2),
                "end_sec": round(max(ends), 2),
                "labels": labels,
            }
        )
    return term_segments


def build_timeline_from_summary(
    summary: dict[str, Any],
    *,
    video_duration: float | None = None,
    hook_seconds: float = 4.0,
    finale_seconds: float = 8.0,
    hold_after_last: float = 0.35,
    outro_seconds: float = 8.0,
) -> dict[str, Any]:
    tasks = summary.get("tasks") or []
    if not tasks:
        raise ValueError("summary has no tasks")

    total_elapsed = sum(float(t.get("elapsed_seconds") or 0) for t in tasks)
    if total_elapsed <= 0:
        total_elapsed = float(len(tasks))

    # Task montage length (independent of final MP4 length — outro is appended after).
    target_playable = 86.0
    if video_duration is not None:
        target_playable = max(40.0, video_duration - hook_seconds - outro_seconds)
    playable = target_playable
    scale = playable / total_elapsed

    families: dict[str, dict[str, Any]] = {}
    for _p, key, _label in FAMILY_ORDER:
        families[key] = {"passed": 0, "failed": 0, "tasks": []}

    events: list[dict[str, Any]] = []
    t_video = hook_seconds
    for t in tasks:
        tid = t["task_id"]
        fam_key, fam_label = family_for_task_id(tid)
        status = (t.get("status") or "FAIL").upper()
        elapsed = float(t.get("elapsed_seconds") or 1.0)
        dur = max(0.35, elapsed * scale)
        end_sec = t_video + dur
        ev = {
            "task_id": tid,
            "family": fam_key,
            "family_label": fam_label,
            "task_num": short_id(tid),
            "name": t.get("name") or short_id(tid),
            "difficulty": t.get("difficulty", 1),
            "status": status,
            "reason": (t.get("reason") or "")[:120],
            "elapsed": elapsed,
            "start_sec": round(t_video, 2),
            "end_sec": round(end_sec, 2),
        }
        events.append(ev)
        t_video = end_sec
        if fam_key in families:
            families[fam_key]["tasks"].append(tid)
            if status == "PASS":
                families[fam_key]["passed"] += 1
            else:
                families[fam_key]["failed"] += 1

    last_event_end = round(t_video, 2)
    last_event_start = round(events[-1]["start_sec"], 2) if events else hook_seconds
    # Outro begins soon after the last task appears on the scoreboard (~0.55s after its event).
    finale_start = round(last_event_start + 0.55, 2)
    fade_out = round(finale_start + outro_seconds - 0.4, 2)
    computed_duration = round(fade_out + 0.4, 1)
    video_duration = computed_duration

    family_segments = _build_family_segments(events)
    term_segments = _build_term_segments(family_segments)

    passed = sum(1 for t in tasks if (t.get("status") or "").upper() == "PASS")
    failed = len(tasks) - passed
    return {
        "run_id": summary.get("run_id", ""),
        "model": summary.get("model", ""),
        "total_tasks": len(tasks),
        "passed": passed,
        "failed": failed,
        "pass_rate": passed / len(tasks) if tasks else 0.0,
        "total_elapsed": round(total_elapsed, 1),
        "video_duration": video_duration,
        "hook_seconds": hook_seconds,
        "last_event_end": last_event_end,
        "last_event_start": last_event_start,
        "hold_after_last": hold_after_last,
        "finale_start": finale_start,
        "outro_seconds": outro_seconds,
        "fade_out": fade_out,
        "finale_seconds": finale_seconds,
        "families": families,
        "family_segments": family_segments,
        "term_segments": term_segments,
        "events": events,
    }


def write_event_timeline(
    summary_path: Path,
    out_path: Path,
    *,
    video_duration: float | None = None,
) -> dict[str, Any]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    out = build_timeline_from_summary(summary, video_duration=video_duration)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out
