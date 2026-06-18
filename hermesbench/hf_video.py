"""Generate HyperFrames scoreboard index.html from event timeline JSON."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE = REPO / "video" / "hf-scoreboard" / "index.html"
DEFAULT_OUT_DIR = REPO / "video" / "hf-grok-composer"


def build_task_rows(events: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    last_family = None
    for ev in events:
        fam = ev.get("family_label") or "Tasks"
        if fam != last_family:
            lines.append(f'        <div class="sb-family-header" data-family="{fam}">{fam}</div>')
            last_family = fam
        status = (ev.get("status") or "FAIL").upper()
        cls = "pass" if status == "PASS" else "fail"
        tid = ev.get("task_num") or ev.get("task_id", "")
        name = ev.get("name", "")
        reason = ev.get("reason") or ""
        reason_html = ""
        if cls == "fail" and reason:
            esc = reason.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")[:60]
            reason_html = f'<div class="sb-task-reason">{esc}</div>'
        lines.append(
            f'        <div class="sb-task-row" data-task-id="{tid}">'
            f'<span class="sb-task-id">{tid}</span>'
            f'<span class="sb-task-name">{name}</span>'
            f'<span class="sb-task-status {cls}">{status}</span>'
            f"{reason_html}</div>"
        )
    return "\n".join(lines)


def build_events_js(events: list[dict[str, Any]]) -> str:
    rows = []
    for i, ev in enumerate(events):
        t = ev.get("start_sec", 4.0 + i * 0.9)
        tid = ev.get("task_num") or f"task_{i}"
        name = (ev.get("name") or "").replace('"', '\\"')
        is_pass = (ev.get("status") or "").upper() == "PASS"
        rows.append(f'  [{t}, "{tid}", "{name}", {"true" if is_pass else "false"}]')
    return "var EVENTS = [\n" + ",\n".join(rows) + "\n];"


def build_families_js(families: dict[str, Any]) -> str:
    parts = []
    for _p, key, label in [
        ("t01", "1 terminal smoke", "Terminal Smoke"),
        ("t02", "2 file read", "File Read"),
        ("t03", "3 patch edit", "Patch Edit"),
        ("t04", "4 search grep", "Search Grep"),
        ("t05", "5 write new", "Write New"),
        ("t06", "6 process mgmt", "Process Mgmt"),
        ("t07", "7 todo plan", "Todo Plan"),
        ("t08", "8 execute code", "Execute Code"),
        ("t09", "9 web lookup", "Web Lookup"),
        ("t10", "0 memory facts", "Memory Facts"),
        ("t11", "1 error recovery", "Error Recovery"),
    ]:
        f = families.get(key, {"passed": 0, "failed": 0})
        parts.append(f'  "{label}": {{ pass: {f.get("passed", 0)}, fail: {f.get("failed", 0)} }}')
    return "var families = {\n" + ",\n".join(parts) + "\n};"


def build_timeline_js(timeline: dict[str, Any]) -> str:
    payload = {
        "hook_seconds": timeline.get("hook_seconds", 4.0),
        "last_event_end": timeline.get("last_event_end"),
        "finale_start": timeline.get("finale_start"),
        "video_duration": timeline.get("video_duration", 105),
        "term_segments": timeline.get("term_segments", []),
        "family_segments": timeline.get("family_segments", []),
    }
    return "var TIMELINE = " + json.dumps(payload, indent=2) + ";"


def build_dynamic_timeline_js(timeline: dict[str, Any]) -> str:
    finale = float(timeline.get("finale_start", 91))
    vid_dur = float(timeline.get("video_duration", finale + 8))
    fade_out = float(timeline.get("fade_out", vid_dur - 0.4))
    float(timeline.get("last_event_end", finale))
    term_lines: list[str] = ["// --- TERMINAL BLOCKS (timeline-driven) ---"]
    for seg in timeline.get("term_segments", []):
        tid = seg["term_id"]
        start = seg["start_sec"]
        end = seg["end_sec"]
        term_lines.append(f'tl.to("#{tid}", {{ opacity: 1, duration: 0.3 }}, {start});')
        term_lines.append(f'tl.to("#{tid}", {{ opacity: 0, duration: 0.3 }}, {end});')

    return (
        "\n".join(term_lines)
        + f"""

// --- SCOREBOARD COUNTERS ---
var counterPass = document.getElementById("counter-pass");
var counterFail = document.getElementById("counter-fail");
var counterTotal = document.getElementById("counter-total");
var counterRate = document.getElementById("counter-rate");
var progressFill = document.getElementById("sb-progress-fill");
var progressPct = document.getElementById("sb-progress-pct");
var statusText = document.getElementById("status-text");
var statusTasks = document.getElementById("status-tasks");
var statusElapsed = document.getElementById("status-elapsed");

var taskList = document.getElementById("sb-task-list");
var taskInner = document.getElementById("sb-task-inner");
var allRows = taskInner.querySelectorAll(".sb-task-row");

function computeScrollTargets(listEl, rows) {{
  var maxScroll = Math.max(0, listEl.scrollHeight - listEl.clientHeight);
  var listRect = listEl.getBoundingClientRect();
  var targets = [];
  for (var r = 0; r < rows.length; r++) {{
    var rowRect = rows[r].getBoundingClientRect();
    var rowTopInContent = listEl.scrollTop + (rowRect.top - listRect.top);
    var want = rowTopInContent - listEl.clientHeight * 0.55;
    var t = Math.min(maxScroll, Math.max(0, want));
    if (r > 0 && t < targets[r - 1]) t = targets[r - 1];
    targets.push(t);
  }}
  return {{ targets: targets, maxScroll: maxScroll }};
}}

var scrollData = computeScrollTargets(taskList, allRows);
var scrollTargets = scrollData.targets;
var maxScroll = scrollData.maxScroll;

var passCount = 0;
var failCount = 0;

EVENTS.forEach(function(ev, i) {{
  var time = ev[0];
  var taskId = ev[1];
  var name = ev[2];
  var isPass = ev[3];
  var row = taskInner.querySelector('.sb-task-row[data-task-id="' + taskId + '"]') || allRows[i];
  var target = scrollTargets[i] !== undefined ? scrollTargets[i] : maxScroll;

  tl.to(taskList, {{ scrollTop: target, duration: 0.45, ease: "power2.out" }}, time);
  tl.fromTo(row, {{ opacity: 0, x: 30 }}, {{ opacity: 1, x: 0, duration: 0.25, ease: "power2.out" }}, time + 0.15);

  var statusEl = row.querySelector(".sb-task-status");
  if (statusEl) {{
    tl.fromTo(statusEl, {{ opacity: 0 }}, {{ opacity: 1, duration: 0.2 }}, time + 0.15);
    var glowColor = isPass ? "#00FFAA" : "#FF3355";
    tl.fromTo(statusEl, {{ textShadow: "0 0 12px " + glowColor }}, {{ textShadow: "0 0 0px " + glowColor, duration: 0.4 }}, time + 0.4);
  }}

  tl.call(function() {{
    if (isPass) passCount++; else failCount++;
    var total = i + 1;
    var rate = Math.round(passCount / total * 100);
    counterPass.textContent = passCount;
    counterFail.textContent = failCount;
    counterTotal.textContent = total;
    counterRate.textContent = rate + "%";
    statusTasks.textContent = total + "/" + TOTAL_TASKS;
    statusText.textContent = "Task: " + taskId + " — " + name + " → " + (isPass ? "PASS" : "FAIL");
    progressPct.textContent = Math.round(total / TOTAL_TASKS * 100) + "%";
    progressFill.style.width = Math.round(total / TOTAL_TASKS * 100) + "%";
    var mins = Math.floor(time / 60);
    var secs = Math.floor(time % 60);
    statusElapsed.textContent = String(mins).padStart(2, "0") + ":" + String(secs).padStart(2, "0");
  }}, null, time);

  if (isPass) {{
    tl.fromTo(counterPass, {{ scale: 1.3 }}, {{ scale: 1, duration: 0.3, ease: "back.out(2)" }}, time);
  }} else {{
    tl.fromTo(counterFail, {{ scale: 1.3 }}, {{ scale: 1, duration: 0.3, ease: "back.out(2)" }}, time);
  }}
}});

// --- OUTRO (results) ---
var F = {finale};
tl.to("#terminal-area", {{ opacity: 0, duration: 0.35 }}, F);
tl.to("#scoreboard", {{ opacity: 0, duration: 0.35 }}, F);
tl.to("#status-bar", {{ opacity: 0, duration: 0.25 }}, F);
tl.fromTo("#final-overlay", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.45, ease: "power2.out" }}, F);
tl.fromTo("#final-score", {{ scale: 0.55, opacity: 0 }}, {{ scale: 1, opacity: 1, duration: 0.55, ease: "back.out(1.7)" }}, F + 0.12);
tl.fromTo("#final-sub", {{ opacity: 0, y: 8 }}, {{ opacity: 1, y: 0, duration: 0.35 }}, F + 0.45);
tl.fromTo("#final-model", {{ opacity: 0, y: 8 }}, {{ opacity: 1, y: 0, duration: 0.35 }}, F + 0.55);
var finalRate = document.getElementById("final-rate");
if (finalRate) {{
  tl.fromTo(finalRate, {{ opacity: 0, scale: 0.9 }}, {{ opacity: 1, scale: 1, duration: 0.4, ease: "back.out(1.5)" }}, F + 0.65);
}}
tl.to("#final-families", {{ opacity: 1, duration: 0.3 }}, F + 0.75);

var finalFamiliesEl = document.getElementById("final-families");
var famKeys = Object.keys(families);
famKeys.forEach(function(fam, idx) {{
  var f = families[fam];
  var total = f.pass + f.fail;
  var passPct = total ? Math.round(f.pass / total * 100) : 0;
  var cardEl = document.createElement("div");
  cardEl.className = "final-family-card";
  cardEl.innerHTML =
    '<div class="final-family-name">' + fam + '</div>' +
    '<div style="font-family:JetBrains Mono,monospace;font-size:16px;color:var(--text-primary);margin:4px 0">' + f.pass + '/' + total + '</div>' +
    '<div class="final-family-bar-outer">' +
      '<div class="final-family-pass" style="width:' + passPct + '%"></div>' +
      '<div class="final-family-fail" style="width:' + (100-passPct) + '%"></div>' +
    '</div>';
  cardEl.style.opacity = "0";
  cardEl.style.transform = "translateY(16px)";
  finalFamiliesEl.appendChild(cardEl);
  tl.to(cardEl, {{ opacity: 1, y: 0, duration: 0.28, ease: "back.out(1.3)" }}, F + 0.85 + idx * 0.11);
}});

tl.fromTo("#final-cta", {{ opacity: 0, y: 10 }}, {{ opacity: 1, y: 0, duration: 0.4 }}, F + 2.4);
tl.to("#final-score", {{ textShadow: "0 0 36px rgba(0,255,170,0.55)", duration: 0.45 }}, F + 1.2);
tl.to("#final-score", {{ textShadow: "0 0 8px rgba(0,255,170,0.15)", duration: 0.45 }}, F + 2.0);
tl.to("#composition", {{ opacity: 0, duration: 0.35, ease: "power2.in" }}, {fade_out});
"""
    )


def generate_hf_index(
    timeline: dict[str, Any],
    *,
    template_path: Path = DEFAULT_TEMPLATE,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> Path:
    events = timeline["events"]
    model = timeline.get("model", "unknown-model")
    passed = timeline.get("passed", 0)
    total = timeline.get("total_tasks", len(events))
    rate = timeline.get("pass_rate", 0) * 100
    vid_dur = timeline.get("video_duration", 105)

    html = template_path.read_text(encoding="utf-8")

    if ".sb-task-reason" not in html:
        html = html.replace(
            "  .sb-task-row {",
            "  .sb-task-reason { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: var(--fail); opacity: 0.85; margin-top: 2px; grid-column: 1 / -1; }\n  .sb-task-row {",
        )
    if "#term-complete" not in html:
        html = html.replace(
            '        <div style="margin-top:24px; text-align:center">\n'
            '          <span style="font-size:16px; color:var(--pass); font-weight:700">▌BENCHMARK COMPLETE</span>\n'
            "        </div>\n"
            "      </div>",
            "      </div>\n"
            '      <div id="term-complete" class="term-block" style="top:24px; left:32px; text-align:center;">\n'
            '        <span style="font-size:20px; color:var(--pass); font-weight:700">▌BENCHMARK COMPLETE</span>\n'
            "      </div>",
        )
    if (
        ".sb-task-status.pass" in html
        and "opacity: 0" not in html.split(".sb-task-status {")[1][:200]
    ):
        html = html.replace(
            "  .sb-task-status {\n    font-weight: 700;",
            "  .sb-task-status {\n    opacity: 0;\n    font-weight: 700;",
        )

    html = html.replace("--pass: #00FF88;", "--pass: #00FFAA;")
    html = html.replace("nex-agi/nex-n2-pro:free", model)
    html = html.replace("via kilocode", "xAI · Hermes Agent")
    html = re.sub(r'data-duration="\d+"', f'data-duration="{int(vid_dur)}"', html, count=1)
    html = re.sub(
        r'<div id="final-score">\d+/\d+</div>',
        f'<div id="final-score">{passed}/{total}</div>',
        html,
    )
    html = re.sub(
        r'<div id="final-rate"[^>]*>[\d.]+%</div>',
        f'<div id="final-rate" style="font-size:36px;color:var(--gold);margin-top:6px;font-family:\'JetBrains Mono\',monospace;font-weight:700;opacity:0">{rate:.1f}%</div>',
        html,
        count=1,
    )
    if 'id="final-rate"' not in html:
        html = re.sub(
            r'(<div id="final-model">[^<]+</div>\n)',
            r'\1    <div id="final-rate" style="font-size:36px;color:var(--gold);margin-top:6px;font-family:\'JetBrains Mono\',monospace;font-weight:700;opacity:0">'
            + f"{rate:.1f}%"
            + "</div>\n",
            html,
            count=1,
        )
        html = re.sub(
            r"<div style=\"font-size:36px; color:var\(--gold\);[^\"]*\"[^>]*>[\d.]+%</div>\n",
            "",
            html,
            count=1,
        )

    rows_html = build_task_rows(events)
    html = re.sub(
        r'<div id="sb-task-inner">.*?</div>\s*</div>\s*</div>\s*<!-- Hook overlay -->',
        f'<div id="sb-task-inner">\n{rows_html}\n      </div>\n    </div>\n  </div>\n\n  <!-- Hook overlay -->',
        html,
        count=1,
        flags=re.S,
    )

    events_js = build_events_js(events)
    html = re.sub(r"var EVENTS = \[.*?\];", events_js, html, count=1, flags=re.S)

    fam_js = build_families_js(timeline.get("families", {}))
    html = re.sub(r"var families = \{.*?\};", fam_js, html, count=1, flags=re.S)

    timeline_js = build_timeline_js(timeline)
    if "var TIMELINE =" in html:
        html = re.sub(r"var TIMELINE = \{[\s\S]*?\};", timeline_js, html, count=1)
    else:
        html = html.replace(
            "var TOTAL_TASKS = EVENTS.length;", f"{timeline_js}\n\nvar TOTAL_TASKS = EVENTS.length;"
        )

    dynamic_js = build_dynamic_timeline_js(timeline)
    html = re.sub(
        r"// --- TERMINAL BLOCKS ---.*?tl\.to\(\"#composition\".*?\);",
        dynamic_js.strip(),
        html,
        count=1,
        flags=re.S,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("package.json", "hyperframes.json", "meta.json", "DESIGN.md", "AGENTS.md"):
        src = template_path.parent / name
        if not src.exists():
            continue
        dest = out_dir / name
        if name == "meta.json":
            dest.write_text(
                json.dumps(
                    {"id": "hf-benchmark", "name": f"HermesBench {model}", "version": "1.0.0"},
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        elif name == "DESIGN.md" and dest.exists():
            continue
        elif not dest.exists():
            shutil.copy2(src, dest)

    index_path = out_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")
    return index_path
