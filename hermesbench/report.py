"""HermesBench HTML report generators."""

from __future__ import annotations

import csv
import html
import json
import re
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value))


def _pct(passed: int, total: int) -> float:
    return (passed / total * 100.0) if total else 0.0


def _category(task_id: str) -> str:
    return task_id.split("/", 1)[0]


def _status_class(rate: float) -> str:
    if rate >= 80:
        return "good"
    if rate >= 40:
        return "mid"
    return "bad"


def _simple_yaml_field(text: str, key: str) -> str:
    """Tiny YAML reader for task prompt/name/timeout without adding deps here."""
    block = re.search(rf"^{re.escape(key)}:\s*\|\s*\n((?:  .*\n?)*)", text, flags=re.M)
    if block:
        lines = []
        for line in block.group(1).splitlines():
            lines.append(line[2:] if line.startswith("  ") else line)
        return "\n".join(lines).strip()
    scalar = re.search(rf"^{re.escape(key)}:\s*(.*)$", text, flags=re.M)
    if not scalar:
        return ""
    value = scalar.group(1).strip()
    if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
        value = value[1:-1]
    return value


def _task_meta(repo_root: Path, task_id: str) -> dict[str, str]:
    task_yaml = repo_root / "tasks" / task_id / "task.yaml"
    if not task_yaml.exists():
        return {"prompt": "", "allowed_tools": "", "timeout": ""}
    text = task_yaml.read_text(encoding="utf-8", errors="ignore")
    allowed = ""
    match = re.search(r"^allowed_tools:\s*\n((?:  - .*\n?)*)", text, flags=re.M)
    if match:
        allowed = ", ".join(
            line.strip()[2:].strip()
            for line in match.group(1).splitlines()
            if line.strip().startswith("- ")
        )
    return {
        "prompt": _simple_yaml_field(text, "prompt"),
        "allowed_tools": allowed,
        "timeout": _simple_yaml_field(text, "timeout_seconds"),
    }


def _telemetry_summary(path: Path) -> dict[str, float | int]:
    values: dict[str, list[float]] = {"temp": [], "power": [], "util": []}
    if not path.exists() or path.stat().st_size == 0:
        return {"samples": 0}
    with path.open(newline="", encoding="utf-8", errors="ignore") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            for key, column in (
                ("temp", "temperature.gpu"),
                ("power", "power.draw"),
                ("util", "utilization.gpu"),
            ):
                raw = str(row.get(column, "")).replace(" W", "").strip()
                if not raw or raw == "[N/A]":
                    continue
                try:
                    values[key].append(float(raw))
                except ValueError:
                    continue
    out: dict[str, float | int] = {
        "samples": max(len(xs) for xs in values.values()) if values else 0,
    }
    for key, xs in values.items():
        if xs:
            out[f"{key}_mean"] = statistics.mean(xs)
            out[f"{key}_max"] = max(xs)
    return out


def _telemetry_card(name: str, data: dict[str, float | int]) -> str:
    if not data or int(data.get("samples", 0)) == 0:
        return f"<div class='tele'><b>{_esc(name)}</b><span>No samples captured</span></div>"
    return f"""<div class='tele'><b>{_esc(name)}</b>
      <span>{int(data.get('samples', 0))} samples</span>
      <span>temp mean/max: {float(data.get('temp_mean', 0)):.1f} / {float(data.get('temp_max', 0)):.0f} °C</span>
      <span>power mean/max: {float(data.get('power_mean', 0)):.1f} / {float(data.get('power_max', 0)):.1f} W</span>
      <span>util mean/max: {float(data.get('util_mean', 0)):.0f} / {float(data.get('util_max', 0)):.0f}%</span>
    </div>"""


INFRA_ERROR_PATTERNS = (
    "APIConnectionError",
    "API call failed after",
    "Connection error.",
    "EngineDeadError",
    "HTTP Error 5",
    "ReadTimeout",
    "ConnectTimeout",
    "RemoteProtocolError",
)


def _display_status(task: dict[str, Any]) -> str:
    """Best-effort status for reports, including old summaries before INFRA_ERROR existed."""
    status = str(task.get("status") or "UNKNOWN")
    if status != "FAIL":
        return status
    trace = Path(str(task.get("trace") or ""))
    raw_log = Path(str(task.get("raw_log") or ""))
    try:
        trace_empty = (not trace.exists()) or trace.stat().st_size == 0
    except OSError:
        trace_empty = True
    if not trace_empty or not raw_log.exists():
        return status
    text = raw_log.read_text(encoding="utf-8", errors="ignore")
    if any(pattern in text for pattern in INFRA_ERROR_PATTERNS):
        return "INFRA_ERROR"
    return status


def generate_run_html_report(summary_path: Path, out_path: Path | None = None, repo_root: Path | None = None) -> Path:
    """Generate the canonical self-contained flat-dark HTML report for one run.

    The report is intentionally richer than REPORT.md: it includes category scores,
    all task prompts, verifier reasons, trace/log paths, and optional telemetry CSV
    summaries when present under results/<run_id>/.
    """
    root = (repo_root or REPO).resolve()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    tasks = summary.get("tasks") or []
    run_id = summary.get("run_id", summary_path.parent.name)
    model = summary.get("model", "unknown")
    passed = sum(1 for t in tasks if _display_status(t) == "PASS")
    total = len(tasks)
    infra = sum(1 for t in tasks if _display_status(t) == "INFRA_ERROR")
    failed = sum(1 for t in tasks if _display_status(t) == "FAIL")
    rate = _pct(passed, total)

    by_cat: dict[str, dict[str, Any]] = defaultdict(lambda: {"pass": 0, "fail": 0, "elapsed": 0.0, "tasks": []})
    for task in tasks:
        cat = _category(task.get("task_id", "unknown"))
        status = _display_status(task)
        if status == "PASS":
            by_cat[cat]["pass"] += 1
        elif status == "INFRA_ERROR":
            by_cat[cat].setdefault("infra", 0)
            by_cat[cat]["infra"] += 1
        else:
            by_cat[cat]["fail"] += 1
        by_cat[cat]["elapsed"] += float(task.get("elapsed_seconds") or 0)
        by_cat[cat]["tasks"].append(task)

    cat_rows = []
    for cat, data in sorted(by_cat.items()):
        cat_total = int(data["pass"] + data["fail"] + data.get("infra", 0))
        cat_rate = _pct(int(data["pass"]), cat_total)
        cls = _status_class(cat_rate)
        cat_rows.append(
            f"""
<tr>
  <td><code>{_esc(cat)}</code></td><td>{data['pass']}/{cat_total}</td><td><span class='pill {cls}'>{cat_rate:.0f}%</span></td>
  <td>{int(data.get('infra', 0))}</td><td>{float(data['elapsed']) / 60:.1f} min</td>
  <td><div class='bar'><i style='width:{cat_rate:.1f}%'></i></div></td>
</tr>"""
        )

    task_cards = []
    for task in tasks:
        task_id = task.get("task_id", "")
        meta = _task_meta(root, task_id)
        status = _display_status(task)
        ok = status == "PASS"
        cls = "pass" if ok else "infra" if status == "INFRA_ERROR" else "fail"
        elapsed_s = float(task.get("elapsed_seconds") or 0)
        task_cards.append(
            f"""
<details class='task {cls}'>
  <summary>
    <span class='status {cls}'>{_esc(status)}</span>
    <code>{_esc(task_id)}</code>
    <span>{_esc(task.get('name', ''))}</span>
    <em>{elapsed_s:.1f}s</em>
  </summary>
  <div class='taskbody'>
    <div class='kv'><b>Difficulty</b><span>{_esc(task.get('difficulty'))}</span></div>
    <div class='kv'><b>Allowed tools</b><span>{_esc(meta.get('allowed_tools') or '—')}</span></div>
    <div class='kv'><b>Verifier reason</b><span>{_esc(task.get('reason', ''))}</span></div>
    <h4>Prompt</h4><pre>{_esc(meta.get('prompt', ''))}</pre>
    <h4>Artifacts</h4>
    <pre>{_esc(task.get('trace', ''))}\n{_esc(task.get('raw_log', ''))}\n{_esc(task.get('verifier_result', ''))}</pre>
  </div>
</details>"""
        )

    failed_list = "".join(
        f"<li><code>{_esc(t.get('task_id', ''))}</code> — {_esc(t.get('reason', ''))}</li>"
        for t in tasks
        if _display_status(t) != "PASS"
    ) or "<li>No failed tasks.</li>"

    run_dir = summary_path.parent
    tele1 = _telemetry_summary(run_dir / "telemetry_node1.csv")
    tele2 = _telemetry_summary(run_dir / "telemetry_node2.csv")
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    rate_cls = _status_class(rate)
    html_doc = f"""<!doctype html>
<html lang='en'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>HermesBench Report — {_esc(model)}</title>
<style>
:root {{--bg:#080a10;--panel:#101522;--panel2:#151c2e;--line:#29324a;--text:#e8edf8;--muted:#9aa7bd;--green:#00e58f;--red:#ff4d6d;--yellow:#ffd166;--blue:#6ea8ff;}}
*{{box-sizing:border-box}} body{{margin:0;background:radial-gradient(circle at 20% 0%,#18213a 0,#080a10 38%,#05060a 100%);color:var(--text);font:14px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;}}
.wrap{{max-width:1220px;margin:0 auto;padding:36px 20px 64px}} .hero{{border:1px solid var(--line);border-radius:28px;padding:30px;background:linear-gradient(135deg,rgba(21,28,46,.96),rgba(12,16,28,.92));box-shadow:0 24px 80px rgba(0,0,0,.45);position:relative;overflow:hidden}} .hero:after{{content:'';position:absolute;inset:auto -120px -120px auto;width:360px;height:360px;background:radial-gradient(circle,rgba(0,229,143,.18),transparent 65%)}}
h1{{margin:0;font-size:clamp(30px,5vw,64px);letter-spacing:-.05em;line-height:.95}} .sub{{color:var(--muted);margin-top:12px;font-size:16px}} .grid{{display:grid;gap:16px;grid-template-columns:repeat(4,1fr);margin-top:22px}} .card{{border:1px solid var(--line);background:rgba(16,21,34,.84);border-radius:20px;padding:18px}} .metric .num{{display:block;font-size:34px;font-weight:800;letter-spacing:-.04em}} .metric .label{{color:var(--muted);text-transform:uppercase;letter-spacing:.12em;font-size:11px}}
.good{{color:var(--green)}} .bad{{color:var(--red)}} .mid{{color:var(--yellow)}} section{{margin-top:28px}} h2{{margin:0 0 12px;font-size:24px;letter-spacing:-.02em}} table{{width:100%;border-collapse:collapse;overflow:hidden;border-radius:16px}} th,td{{padding:12px 14px;border-bottom:1px solid var(--line);text-align:left}} th{{color:#c8d3e6;background:#121a2b;font-size:12px;text-transform:uppercase;letter-spacing:.08em}} tr:hover td{{background:rgba(255,255,255,.025)}} code{{color:#dbeafe;background:rgba(110,168,255,.10);padding:.12em .35em;border-radius:6px}} .pill{{display:inline-flex;min-width:58px;justify-content:center;border-radius:999px;border:1px solid currentColor;padding:2px 8px;font-weight:800}} .bar{{height:9px;background:#263149;border-radius:999px;overflow:hidden}} .bar i{{display:block;height:100%;background:linear-gradient(90deg,var(--red),var(--yellow),var(--green));border-radius:999px}}
.telegrid{{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}} .tele{{display:grid;gap:6px;color:var(--muted)}} .tele b{{color:var(--text);font-size:16px}} .task{{border:1px solid var(--line);background:rgba(16,21,34,.72);border-radius:16px;margin:10px 0;overflow:hidden}} .task summary{{cursor:pointer;display:grid;grid-template-columns:96px minmax(260px,1fr) 1.2fr 80px;gap:12px;align-items:center;padding:12px 14px}} .task.pass{{border-left:4px solid var(--green)}} .task.fail{{border-left:4px solid var(--red)}} .task.infra{{border-left:4px solid var(--yellow)}} .status{{border-radius:999px;padding:3px 9px;font-weight:900;font-size:11px;text-align:center}} .status.pass{{color:#001b10;background:var(--green)}} .status.fail{{color:#2a0008;background:var(--red)}} .status.infra{{color:#2a1d00;background:var(--yellow)}} .task summary em{{color:var(--muted);font-style:normal;text-align:right}} .taskbody{{padding:0 14px 16px 106px;color:#d8e0ef}} .kv{{display:grid;grid-template-columns:150px 1fr;gap:12px;padding:4px 0}} .kv b{{color:var(--muted)}} pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#080c15;border:1px solid #222b40;border-radius:12px;padding:12px;color:#cbd5e1}} .failbox{{max-height:360px;overflow:auto}} .footer{{color:var(--muted);margin-top:28px;border-top:1px solid var(--line);padding-top:18px}}
@media(max-width:900px){{.grid{{grid-template-columns:repeat(2,1fr)}}.telegrid{{grid-template-columns:1fr}}.task summary{{grid-template-columns:70px 1fr}}.task summary span:nth-child(3),.task summary em{{display:none}}.taskbody{{padding:0 12px 14px}}}}
</style>
</head><body><div class='wrap'>
<header class='hero'><h1>HermesBench<br>{_esc(model)}</h1><div class='sub'>Canonical full HTML report · generated {_esc(generated_at)}</div><div class='grid'>
<div class='card metric'><span class='num {rate_cls}'>{rate:.1f}%</span><span class='label'>pass rate</span></div><div class='card metric'><span class='num'>{passed}/{total}</span><span class='label'>passed tasks</span></div><div class='card metric'><span class='num'>{failed}</span><span class='label'>model/verifier fails</span></div><div class='card metric'><span class='num mid'>{infra}</span><span class='label'>infra errors</span></div>
</div></header>
<section class='card'><h2>Run metadata</h2><div class='kv'><b>Run ID</b><span><code>{_esc(run_id)}</code></span></div><div class='kv'><b>Model</b><span><code>{_esc(model)}</code></span></div><div class='kv'><b>Endpoint</b><span><code>{_esc(summary.get('base_url'))}</code></span></div><div class='kv'><b>Hermes SHA</b><span><code>{_esc(summary.get('hermes_sha'))}</code></span></div><div class='kv'><b>Toolsets</b><span><code>{_esc(summary.get('toolsets'))}</code></span></div></section>
<section class='card'><h2>Category breakdown</h2><table><thead><tr><th>Category</th><th>Pass</th><th>Rate</th><th>Infra</th><th>Elapsed</th><th>Bar</th></tr></thead><tbody>{''.join(cat_rows)}</tbody></table></section>
<section class='card'><h2>GPU telemetry</h2><div class='telegrid'>{_telemetry_card('Node1 / head', tele1)}{_telemetry_card('Node2 / worker', tele2)}</div></section>
<section class='card'><h2>Failed task reasons</h2><ol class='failbox'>{failed_list}</ol></section>
<section><h2>All task prompts, results, and artifacts</h2>{''.join(task_cards)}</section>
<div class='footer'>Raw artifacts: <code>{_esc(summary_path)}</code> · traces: <code>{_esc(root / 'traces' / str(run_id))}</code></div>
</div></body></html>
"""
    dest = out_path or summary_path.parent / "report.html"
    dest.write_text(html_doc, encoding="utf-8")
    return dest


def generate_html_report(results: list[dict], out_path: str, model_name: str = "") -> None:
    """Compatibility wrapper for callers that only have task result dicts."""
    summary = {
        "run_id": Path(out_path).parent.name,
        "model": model_name or "unknown",
        "base_url": "",
        "toolsets": "",
        "tasks": results,
        "passed": sum(1 for r in results if r.get("status") == "PASS"),
    }
    tmp = Path(out_path).with_suffix(".summary.tmp.json")
    tmp.write_text(json.dumps(summary), encoding="utf-8")
    try:
        generate_run_html_report(tmp, Path(out_path), REPO)
    finally:
        tmp.unlink(missing_ok=True)


def generate_comparison_html(results: dict[str, list[dict]], out_path: str) -> None:
    """Side-by-side HTML comparison of multiple model runs using the canonical dark style."""
    all_cats: set[str] = set()
    summaries: dict[str, dict[str, Any]] = {}
    for run_path, res in results.items():
        label = Path(run_path).name
        total = len(res)
        passed = sum(1 for r in res if r.get("status") == "PASS")
        cats: dict[str, list[int]] = {}
        for r in res:
            cat = _category(r.get("task_id", "unknown"))
            cats.setdefault(cat, [0, 0])
            cats[cat][1] += 1
            if r.get("status") == "PASS":
                cats[cat][0] += 1
        summaries[label] = {"total": total, "passed": passed, "cats": cats}
        all_cats.update(cats.keys())

    labels = list(summaries.keys())
    header = "<tr><th>Category</th>" + "".join(f"<th>{_esc(label)}</th>" for label in labels) + "</tr>"
    rows = []
    overall = "<td><b>Overall</b></td>"
    for label in labels:
        s = summaries[label]
        rate = _pct(int(s["passed"]), int(s["total"]))
        overall += f"<td><b>{s['passed']}/{s['total']} ({rate:.0f}%)</b></td>"
    rows.append(f"<tr>{overall}</tr>")
    for cat in sorted(all_cats):
        row = f"<td><code>{_esc(cat)}</code></td>"
        for label in labels:
            p, t = summaries[label]["cats"].get(cat, (0, 0))
            row += f"<td>{p}/{t} ({_pct(p, t):.0f}%)</td>" if t else "<td>—</td>"
        rows.append(f"<tr>{row}</tr>")

    doc = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>HermesBench Comparison</title><style>
:root{{--bg:#080a10;--panel:#101522;--line:#29324a;--text:#e8edf8;--muted:#9aa7bd;--blue:#6ea8ff}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 20% 0%,#18213a 0,#080a10 38%,#05060a 100%);color:var(--text);font:14px/1.5 ui-sans-serif,system-ui,sans-serif}}.wrap{{max-width:1100px;margin:0 auto;padding:36px 20px}}.card{{border:1px solid var(--line);background:rgba(16,21,34,.86);border-radius:22px;padding:20px;overflow:auto}}h1{{font-size:44px;letter-spacing:-.04em}}table{{width:100%;border-collapse:collapse}}th,td{{padding:12px 14px;border-bottom:1px solid var(--line);text-align:left}}th{{background:#121a2b;color:#c8d3e6;text-transform:uppercase;font-size:12px;letter-spacing:.08em}}code{{color:#dbeafe;background:rgba(110,168,255,.10);padding:.12em .35em;border-radius:6px}}</style></head><body><div class='wrap'><h1>HermesBench Comparison</h1><div class='card'><table>{header}{''.join(rows)}</table></div></div></body></html>"""
    Path(out_path).write_text(doc, encoding="utf-8")
