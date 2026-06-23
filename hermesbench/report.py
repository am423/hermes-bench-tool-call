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


def _task_trace_metrics(task: dict[str, Any]) -> dict[str, Any]:
    trace_path = Path(str(task.get("trace") or ""))
    tool_counts: dict[str, int] = defaultdict(int)
    if trace_path.is_file() and trace_path.stat().st_size > 0:
        for line in trace_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(msg.get("tool_calls"), list):
                for tc in msg["tool_calls"]:
                    name = ((tc.get("function") or {}).get("name") or "tool")
                    tool_counts[str(name)] += 1
    raw_log = Path(str(task.get("raw_log") or ""))
    api_calls = 0
    if raw_log.is_file():
        text = raw_log.read_text(encoding="utf-8", errors="ignore")
        api_calls = len(re.findall(r"Making API call #", text))
    return {
        "api_calls": api_calls,
        "tool_calls": sum(tool_counts.values()),
        "tools": ", ".join(f"{name}x{count}" for name, count in sorted(tool_counts.items(), key=lambda x: (-x[1], x[0]))),
    }


def _median(xs: list[float]) -> float:
    return statistics.median(xs) if xs else 0.0


def _display_model_title(model: str) -> str:
    lower = model.lower()
    if "stepfun" in lower or "step" in lower:
        return "Step 3.7 Flash NVFP4"
    if "qwen36" in lower or "qwen3.6" in lower:
        return "Qwen 3.6 27B NVFP4"
    return model.replace("_", "-")


def _quality_label(infra: int, trace_ok: bool, endpoint_ok: bool) -> tuple[str, str]:
    if infra == 0 and trace_ok and endpoint_ok:
        return "QUALITY GATE PASS", "trusted"
    return "QUALITY GATE FAIL", "fail"


def generate_run_html_report(summary_path: Path, out_path: Path | None = None, repo_root: Path | None = None) -> Path:
    """Generate the canonical Qwen-style self-contained flat-dark HTML report."""
    root = (repo_root or REPO).resolve()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    tasks = summary.get("tasks") or []
    run_id = str(summary.get("run_id", summary_path.parent.name))
    model = str(summary.get("model", "unknown"))
    base_url = str(summary.get("base_url") or "")
    title = _display_model_title(model)

    display_statuses = [_display_status(t) for t in tasks]
    passed = sum(1 for s in display_statuses if s == "PASS")
    infra = sum(1 for s in display_statuses if s == "INFRA_ERROR")
    total = len(tasks)
    rate = _pct(passed, total)
    elapsed_values = [float(t.get("elapsed_seconds") or 0) for t in tasks]
    total_elapsed = sum(elapsed_values)
    median_elapsed = _median(elapsed_values)

    metrics_by_task = {t.get("task_id", ""): _task_trace_metrics(t) for t in tasks}
    api_calls = sum(int(m["api_calls"]) for m in metrics_by_task.values())
    tool_calls = sum(int(m["tool_calls"]) for m in metrics_by_task.values())

    trace_present = 0
    endpoint_logs = 0
    for task in tasks:
        trace = Path(str(task.get("trace") or ""))
        if trace.exists() and trace.stat().st_size > 0:
            trace_present += 1
        raw_log = Path(str(task.get("raw_log") or ""))
        if raw_log.exists() and (not base_url or base_url in raw_log.read_text(encoding="utf-8", errors="ignore")):
            endpoint_logs += 1
    trace_ok = trace_present == total and total > 0
    endpoint_ok = endpoint_logs == total and total > 0
    quality_text, quality_class = _quality_label(infra, trace_ok, endpoint_ok)

    by_cat: dict[str, dict[str, Any]] = defaultdict(lambda: {"pass": 0, "fail": 0, "infra": 0, "elapsed": [], "tasks": []})
    for task, status in zip(tasks, display_statuses, strict=True):
        cat = _category(task.get("task_id", "unknown"))
        if status == "PASS":
            by_cat[cat]["pass"] += 1
        elif status == "INFRA_ERROR":
            by_cat[cat]["infra"] += 1
        else:
            by_cat[cat]["fail"] += 1
        by_cat[cat]["elapsed"].append(float(task.get("elapsed_seconds") or 0))
        by_cat[cat]["tasks"].append(task)

    cat_cards = []
    for cat, data in sorted(by_cat.items()):
        cat_total = int(data["pass"] + data["fail"] + data["infra"])
        cat_rate = _pct(int(data["pass"]), cat_total)
        extra = f" · infra {data['infra']}" if data["infra"] else ""
        label = "HumanEval Micro" if cat == "t13_humaneval_micro" else cat
        cat_cards.append(
            f"<article class='card cat'><div class='split'><b>{_esc(label)}</b><span>{data['pass']}/{cat_total}</span></div>"
            f"<div class='bar'><i style='width:{cat_rate:.1f}%'></i></div>"
            f"<small>{cat_rate:.1f}% · median {_median(data['elapsed']):.1f}s{extra}</small></article>"
        )

    failure_reasons = defaultdict(int)
    failed_rows = []
    all_rows = []
    for task, status in zip(tasks, display_statuses, strict=True):
        task_id = str(task.get("task_id", ""))
        meta = _task_meta(root, task_id)
        reason = str(task.get("reason") or "")
        metrics = metrics_by_task.get(task_id, {"api_calls": 0, "tool_calls": 0, "tools": ""})
        elapsed_s = float(task.get("elapsed_seconds") or 0)
        if status != "PASS":
            failure_reasons[reason or status] += 1
            failed_rows.append(
                f"<tr class='{_esc(status.lower())}'><td><code>{_esc(task_id)}</code></td><td>{_esc(task.get('name',''))}</td>"
                f"<td>{_esc(reason)}</td><td>{elapsed_s:.1f}s</td><td>{_esc(metrics.get('tools',''))}</td></tr>"
            )
        all_rows.append(
            f"<tr class='{_esc(status.lower())}'><td><code>{_esc(task_id)}</code><br><small>{_esc(task.get('name',''))}</small></td>"
            f"<td><span class='pill {('pass' if status == 'PASS' else 'infra' if status == 'INFRA_ERROR' else 'fail')}'>{_esc(status)}</span></td>"
            f"<td>{_esc(meta.get('prompt',''))}</td><td>{_esc(reason)}</td><td>{elapsed_s:.1f}s</td>"
            f"<td>{int(metrics.get('api_calls', 0))}</td><td>{int(metrics.get('tool_calls', 0))}<br><small>{_esc(metrics.get('tools',''))}</small></td></tr>"
        )

    chips = "".join(
        f"<span class='chip'>{_esc(reason)} <b>{count}</b></span>"
        for reason, count in sorted(failure_reasons.items(), key=lambda x: (-x[1], x[0]))[:20]
    ) or "<span class='chip'>No failures <b>0</b></span>"

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    report_md = summary_path.parent / "REPORT.md"
    quality_gate = summary_path.parent / "QUALITY_GATE.json"
    video = root / "video" / f"{run_id}_benchmark.mp4"
    pass_rate_text = f"{rate:.2f}% pass rate"

    doc = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>HermesBench Report · {_esc(run_id)}</title><style>
:root{{color-scheme:dark;--bg:#060913;--panel:#0f172a;--panel2:#111827;--text:#e5edf7;--muted:#91a4bd;--line:#26364f;--green:#22c55e;--red:#fb7185;--amber:#f59e0b;--cyan:#22d3ee;--violet:#a78bfa}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 15% -10%,#1e3a8a 0,#0b1020 35%,#060913 100%);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,Segoe UI,Arial,sans-serif}}main{{max-width:1440px;margin:0 auto;padding:34px 22px 80px}}.hero{{position:relative;overflow:hidden;border:1px solid #2b3a55;background:linear-gradient(135deg,rgba(15,23,42,.97),rgba(2,6,23,.95));border-radius:32px;padding:34px;box-shadow:0 30px 100px #0009}}.hero:after{{content:"";position:absolute;inset:auto -10% -40% 40%;height:280px;background:radial-gradient(circle,#22d3ee33,transparent 60%)}}.kicker{{color:var(--cyan);font-weight:900;letter-spacing:.16em;text-transform:uppercase;font-size:12px}}.title{{font-size:clamp(30px,5vw,62px);line-height:1;margin:12px 0}}.score{{font-size:clamp(64px,12vw,150px);line-height:.9;font-weight:1000;margin:20px 0;background:linear-gradient(90deg,#fff,#67e8f9,#a78bfa);-webkit-background-clip:text;color:transparent}}.score small{{font-size:.28em;color:var(--muted);-webkit-text-fill-color:var(--muted)}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px}}.card{{border:1px solid var(--line);background:linear-gradient(180deg,rgba(17,24,39,.88),rgba(15,23,42,.72));border-radius:20px;padding:16px}}.metric .label{{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}}.metric .value{{font-size:26px;font-weight:900;margin-top:6px}}.split{{display:flex;justify-content:space-between;gap:12px}}.cat{{min-width:0;overflow:hidden}}.cat .split{{align-items:flex-start;gap:10px}}.cat .split b{{min-width:0;overflow-wrap:anywhere;word-break:break-word;line-height:1.15;padding-right:4px}}.cat .split span{{flex:0 0 auto}}.bar{{height:10px;background:#1f2937;border-radius:99px;overflow:hidden;margin:12px 0}}.bar i{{display:block;height:100%;background:linear-gradient(90deg,var(--green),var(--cyan));border-radius:99px}}.section{{margin-top:26px}}h2{{font-size:26px;margin:0 0 12px}}.chips{{display:flex;flex-wrap:wrap;gap:8px}}.pill,.chip{{display:inline-flex;gap:8px;align-items:center;border:1px solid #334155;background:#1e293b;color:var(--text);border-radius:999px;padding:5px 11px;font-weight:800}}.pill.pass,.pill.trusted,.trusted{{color:#22c55e}}.pill.fail,.fail{{color:var(--red)}}.pill.infra,.infra{{color:var(--amber)}}.chip b{{color:#fff}}code{{color:#bae6fd;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}.scroll{{overflow:auto;border-radius:18px;border:1px solid #1f2a44}}table{{width:100%;border-collapse:collapse;background:#0b1220}}th,td{{padding:12px;border-bottom:1px solid #1f2a44;text-align:left;vertical-align:top}}th{{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#dbeafe}}tr.pass td{{background:#052e1a11}}tr.fail td{{background:#4c051911}}tr.infra_error td{{background:#451a0318}}small{{color:var(--muted)}}footer{{color:var(--muted);margin-top:28px}}@media(max-width:800px){{main{{padding:18px 12px}}.hero{{padding:22px}}.score{{font-size:80px}}}}
</style></head><body><main>
<section class="hero"><div class="kicker">HermesBench · method-quality clean baseline</div><h1 class="title">{_esc(title)}</h1><div class="score">{passed}<small>/{total}</small></div><div class="chips"><span class="pill {quality_class}">{quality_text}</span><span class="pill">{pass_rate_text}</span><span class="pill">{_esc(run_id)}</span></div><div class="grid" style="margin-top:22px"><article class="card metric"><div class="label">Model</div><div class="value">{_esc(model)}</div></article><article class="card metric"><div class="label">Endpoint</div><div class="value" style="font-size:16px"><code>{_esc(base_url)}</code></div></article><article class="card metric"><div class="label">Total elapsed</div><div class="value">{total_elapsed/60:.1f}m</div></article><article class="card metric"><div class="label">API calls</div><div class="value">{api_calls}</div></article><article class="card metric"><div class="label">Tool calls</div><div class="value">{tool_calls}</div></article><article class="card metric"><div class="label">Median task</div><div class="value">{median_elapsed:.1f}s</div></article></div></section>
<section class="section"><h2>Trust diagnostics</h2><article class="card"><ul><li>{'No benchmark-method issues detected.' if infra == 0 else f'{infra} infrastructure/API failures detected; pass rate is not a clean model score.'}</li><li>Fixture integrity after run: <b class="trusted">check report log</b></li><li>Endpoint routing: <b class="{'trusted' if endpoint_ok else 'fail'}">{endpoint_logs}/{total} logs used {_esc(base_url)}</b></li><li>Trace artifacts: <b class="{'trusted' if trace_ok else 'fail'}">{trace_present}/{total} present and non-empty</b></li><li>Hermes SHA: <code>{_esc(summary.get('hermes_sha',''))}</code></li></ul></article></section>
<section class="section"><h2>Category heatmap</h2><div class="grid">{''.join(cat_cards)}</div></section>
<section class="section"><h2>Failure analysis</h2><div class="chips">{chips}</div><div class="scroll" style="margin-top:12px"><table><thead><tr><th>Task</th><th>Name</th><th>Reason</th><th>Elapsed</th><th>Tools</th></tr></thead><tbody>{''.join(failed_rows)}</tbody></table></div></section>
<section class="section"><h2>All {total} questions, metrics, and telemetry</h2><div class="scroll"><table><thead><tr><th>Task</th><th>Status</th><th>Question / prompt</th><th>Verifier reason</th><th>Elapsed</th><th>API</th><th>Tool calls</th></tr></thead><tbody>{''.join(all_rows)}</tbody></table></div></section>
<section class="section"><h2>Artifacts</h2><article class="card"><p>Summary: <code>{_esc(summary_path)}</code></p><p>Markdown report: <code>{_esc(report_md)}</code></p><p>Quality gate: <code>{_esc(quality_gate)}</code></p><p>Video: <code>{_esc(video)}</code></p><p>Trace directory: <code>{_esc(root / 'traces' / run_id)}</code></p></article></section>
<footer>Generated {generated_at} · self-contained static HTML · secrets/log bodies not embedded.</footer>
</main></body></html>'''
    dest = out_path or summary_path.parent / "report.html"
    dest.write_text(doc, encoding="utf-8")
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
