"""REPORT.md and optional HyperFrames assets from a completed run."""

from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from hermesbench.event_timeline import write_event_timeline
from hermesbench.hf_video import generate_hf_index

REPO = Path(__file__).resolve().parent.parent


def write_report_md(summary_path: Path, out_path: Path | None = None) -> Path:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    tasks = summary.get("tasks") or []
    cats: dict[str, dict[str, int]] = defaultdict(lambda: {"pass": 0, "fail": 0})
    fails: list[dict[str, Any]] = []
    for t in tasks:
        key = t["task_id"].rsplit("/", 1)[0]
        if t.get("status") == "PASS":
            cats[key]["pass"] += 1
        else:
            cats[key]["fail"] += 1
            fails.append(t)

    rid = summary.get("run_id", summary_path.parent.name)
    passed = summary.get("passed", sum(1 for t in tasks if t.get("status") == "PASS"))
    total = len(tasks)
    rate = summary.get("pass_rate", passed / total if total else 0)

    lines = [
        f"# HermesBench — {summary.get('model', 'unknown')}",
        "",
        f"**Run ID:** `{rid}`",
        f"**Score:** {passed}/{total} ({rate * 100:.1f}%)",
        f"**Hermes SHA:** `{summary.get('hermes_sha', '')}`",
        "",
        "## By category",
        "",
        "| Category | Pass | Fail |",
        "|----------|------|------|",
    ]
    for k in sorted(cats):
        c = cats[k]
        lines.append(f"| `{k}` | {c['pass']} | {c['fail']} |")
    lines += ["", "## Failed tasks", ""]
    for t in fails:
        lines.append(f"- `{t['task_id']}` — {t.get('reason', '')}")
    lines += [
        "",
        "## Artifacts",
        f"- Summary: `{summary_path}`",
        f"- Traces: `{REPO / 'traces' / rid}`",
    ]
    dest = out_path or summary_path.parent / "REPORT.md"
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def generate_run_artifacts(
    repo_root: Path,
    run_id: str,
    *,
    video_duration: float | None = None,
    render_video: bool = False,
) -> dict[str, Path]:
    """Write REPORT, timeline JSON, and HyperFrames index for a run."""
    summary_path = repo_root / "results" / run_id / "summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError(f"missing {summary_path}")

    report_path = write_report_md(summary_path)
    timeline_path = repo_root / "video" / f"{run_id}_event_timeline.json"
    timeline = write_event_timeline(summary_path, timeline_path, video_duration=video_duration)
    hf_dir = repo_root / "video" / "hf-grok-composer"
    index_path = generate_hf_index(timeline, out_dir=hf_dir)

    out: dict[str, Path] = {
        "report": report_path,
        "timeline": timeline_path,
        "hf_index": index_path,
    }

    if render_video:
        mp4 = repo_root / "video" / f"{run_id}_benchmark.mp4"
        subprocess.run(
            [
                "npx",
                "--yes",
                "hyperframes@0.6.31",
                "render",
                "--quality",
                "high",
                "--output",
                str(mp4),
            ],
            cwd=hf_dir,
            check=False,
        )
        if mp4.is_file():
            out["video"] = mp4

    return out
