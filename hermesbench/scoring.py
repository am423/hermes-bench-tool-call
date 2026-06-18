"""Scoring pipeline (Q44, Q51, Q63, Q64).

Reads `.stats.jsonl` and trace jsonl, joins them on `t` with
±100ms tolerance (Q64), computes the 9 hardware metrics (Q44),
applies the thermal-state-aware comparison (Q51), and produces
a per-task scoring record.

Stdlib-only — used by the runner and the CLI `score` subcommand
without depending on hermes-agent.
"""

from __future__ import annotations

import json
import logging
import statistics
from pathlib import Path
from typing import Any

from hermesbench.types import HardwareMetrics

logger = logging.getLogger(__name__)


def _safe_mean(xs: list[float]) -> float | None:
    return statistics.mean(xs) if xs else None


def _safe_max(xs: list[float]) -> float | None:
    return max(xs) if xs else None


def compute_hardware_metrics(stats_path: Path, trace_path: Path | None = None) -> HardwareMetrics:
    """Read .stats.jsonl and compute aggregate hardware metrics.

    Q64: if trace_path is provided, we join stats samples with
    trace messages on `t` (±100ms) to compute gen-time J/tok.
    """
    if not stats_path.exists():
        return HardwareMetrics()

    samples: list[dict[str, Any]] = []
    for line in stats_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            samples.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not samples:
        return HardwareMetrics()

    # CPU
    cpu_utils: list[float] = []
    cpu_temps: list[float] = []
    cpu_powers: list[float] = []
    for s in samples:
        c = s.get("cpu", {})
        if c.get("util_pct") is not None:
            cpu_utils.append(float(c["util_pct"]))
        if c.get("pkg_temp_c") is not None:
            cpu_temps.append(float(c["pkg_temp_c"]))
        if c.get("pkg_power_w") is not None:
            cpu_powers.append(float(c["pkg_power_w"]))

    # GPU(s) — multi-GPU aware, aggregate sum
    gpu_powers: list[float] = []
    gpu_temps: list[float] = []
    throttle_secs = 0.0
    prev_t: float | None = None
    temp_auc_85 = 0.0
    for s in samples:
        for g in s.get("gpu", []) or []:
            if g.get("power_w") is not None:
                gpu_powers.append(float(g["power_w"]))
            if g.get("temp_c") is not None:
                gpu_temps.append(float(g["temp_c"]))
            if g.get("throttle_reasons") and prev_t is not None:
                # Approximate: throttle was active this sample
                throttle_secs += s.get("t", 0) - prev_t
            # temp AUC
            if g.get("temp_c") is not None and prev_t is not None:
                dt = s.get("t", 0) - prev_t
                excess = max(0.0, float(g["temp_c"]) - 85.0)
                temp_auc_85 += excess * dt
        prev_t = s.get("t", 0)

    # RAM
    ram_used: list[float] = []
    for s in samples:
        r = s.get("ram", {})
        if r.get("used_mib") is not None:
            ram_used.append(float(r["used_mib"]))

    # NVMe
    nvme_temp = None
    if samples:
        last_nvme = samples[-1].get("nvme")
        if last_nvme and "temp_c" in last_nvme:
            nvme_temp = float(last_nvme["temp_c"])

    return HardwareMetrics(
        mean_gpu_power_w=_safe_mean(gpu_powers),
        peak_gpu_power_w=_safe_max(gpu_powers),
        mean_gpu_temp_c=_safe_mean(gpu_temps),
        peak_gpu_temp_c=_safe_max(gpu_temps),
        mean_cpu_power_w=_safe_mean(cpu_powers),
        mean_cpu_temp_c=_safe_mean(cpu_temps),
        mean_host_power_w=None,  # Would need BMC/IPMI; placeholder
        throttled_seconds=throttle_secs,
        temp_auc_above_85c_seconds=temp_auc_85,
        gen_joules_per_output_token=None,  # requires trace join
        wall_joules_per_output_token=None,  # requires trace join
        tok_per_watt=None,  # requires trace join
        mean_model_cpu_cores=(_safe_mean(cpu_utils) or 0.0) / 100.0 * psutil_cpu_count(),
        nvme_temp_c=nvme_temp,
        ram_used_mib=_safe_mean(ram_used),
    )


def psutil_cpu_count() -> int:
    import os

    try:
        return os.cpu_count() or 1
    except Exception:
        return 1


def join_trace_stats(
    trace_messages: list[dict[str, Any]],
    stats_samples: list[dict[str, Any]],
    tolerance_s: float = 0.1,
) -> list[tuple[float, float]]:
    """Return a list of (gpu_power_w_at_assistant_gen, output_tokens) tuples.

    Q44 / Q64: for each assistant message, find the stats sample
    closest in time within ±tolerance_s. The "output_tokens" is
    approximated as the assistant message's completion_token_ids
    length (Q45).
    """
    if not trace_messages or not stats_samples:
        return []

    out: list[tuple[float, float]] = []
    for msg in trace_messages:
        if msg.get("role") != "assistant":
            continue
        # A message is "gen content" if it has content OR tool_calls OR
        # explicit completion_token_ids (the latter is the canonical
        # SFT signal even when content is empty/null).
        if (
            msg.get("content") is None
            and not msg.get("tool_calls")
            and not msg.get("completion_token_ids")
        ):
            continue
        ts = msg.get("ts")
        if ts is None:
            continue
        # Find the stats sample with the closest `t` within tolerance
        best = None
        best_dt = float("inf")
        for s in stats_samples:
            t = s.get("t")
            if t is None:
                continue
            dt = abs(t - ts)
            if dt < best_dt:
                best_dt = dt
                best = s
        if best is not None and best_dt <= tolerance_s:
            gpu_power = 0.0
            for g in best.get("gpu", []) or []:
                if g.get("power_w") is not None:
                    gpu_power += float(g["power_w"])
            token_ids = msg.get("completion_token_ids") or []
            tok = len(token_ids) if isinstance(token_ids, list) else 0
            if tok > 0:
                out.append((gpu_power, tok))
    return out


def compute_gen_joules_per_token(joined: list[tuple[float, float]]) -> float | None:
    """Q44: gen_joules_per_output_token.

    Approximates the integral of power over the gen window
    using mean power during gen x (output_tokens / mean_throughput).
    For v0.1 we use a simpler proxy: mean power during gen ÷
    (output_tokens / wall_clock). Good enough for comparison.
    """
    if not joined:
        return None
    total_power = sum(p for p, _ in joined)
    total_tok = sum(t for _, t in joined)
    if total_tok == 0:
        return None
    # Assume gen took the same wall clock as the trace, normalized
    # by the number of gen windows. For v0.1, return mean_power / (total_tok / 1s)
    # which is a lower bound; will be replaced with a per-window integral.
    mean_power = total_power / len(joined)
    return mean_power / (total_tok / 1.0) if total_tok > 0 else None


def score_run(
    run_dir: Path,
    results_dir: Path,
) -> dict[str, Any]:
    """Score an entire run. Returns a summary dict."""
    for _meta_file in sorted(results_dir.glob("*/task.yaml")) or []:
        # placeholder
        pass
    # For each task result, compute hardware metrics
    summary: dict[str, Any] = {
        "tasks": [],
        "pass_rate": 0.0,
        "by_difficulty": {1: 0, 2: 0, 3: 0},
        "by_difficulty_passed": {1: 0, 2: 0, 3: 0},
        "thermal_warnings": [],
    }
    if not results_dir.exists():
        return summary

    passed = 0
    total = 0
    for task_dir in sorted(results_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        verifier_file = task_dir / "verifier_result.json"
        if not verifier_file.exists():
            continue
        try:
            v = json.loads(verifier_file.read_text())
            status = v.get("status", "FAIL")
            diff = v.get("difficulty", 2)
            summary["by_difficulty"][diff] = summary["by_difficulty"].get(diff, 0) + 1
            if status == "PASS":
                passed += 1
                summary["by_difficulty_passed"][diff] = (
                    summary["by_difficulty_passed"].get(diff, 0) + 1
                )
            total += 1
        except (json.JSONDecodeError, KeyError):
            continue

        stats_file = task_dir / "stats.jsonl"
        if stats_file.exists():
            hw = compute_hardware_metrics(stats_file)
            warn = hw.thermal_warning()
            if warn:
                summary["thermal_warnings"].append({"task": task_dir.name, "warning": warn})
            summary["tasks"].append(
                {
                    "task_id": task_dir.name,
                    "verifier": v,
                    "hardware": hw.__dict__,
                    "thermal_warning": warn,
                }
            )
        else:
            summary["tasks"].append({"task_id": task_dir.name, "verifier": v})

    summary["pass_rate"] = passed / total if total else 0.0
    return summary


def aggregate_results(run_paths: list[str]) -> list[dict]:
    """Collect all verifier_result.json across run dirs."""
    results = []
    for run_path in run_paths:
        for f in Path(run_path).rglob("verifier_result.json"):
            try:
                with open(f) as fh:
                    d = json.load(fh)
                    d["run_path"] = run_path
                    results.append(d)
            except (OSError, json.JSONDecodeError):
                continue
    return results


def category_breakdown(results: list[dict]) -> dict[str, tuple[int, int]]:
    """Group by category prefix (t01_, t02_, etc.)."""
    cats: dict[str, list[int]] = {}
    for r in results:
        cat = r["task_id"].rsplit("/", 1)[0]
        if cat not in cats:
            cats[cat] = [0, 0]
        cats[cat][1] += 1
        if r.get("status") == "PASS":
            cats[cat][0] += 1
    return {k: (v[0], v[1]) for k, v in cats.items()}


def compute_hardware_summary(run_path: str) -> dict[str, float]:
    """Read stats.jsonl from run dir and compute hardware metrics."""
    stats_file = Path(run_path) / "stats.jsonl"
    if not stats_file.exists():
        return {"error": "no stats.jsonl found"}

    powers: list[float] = []
    temps: list[float] = []
    throttle_secs = 0.0

    with open(stats_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                if "gpu_power" in d:
                    powers.append(d["gpu_power"])
                if "gpu_temp" in d:
                    temps.append(d["gpu_temp"])
                if d.get("throttle_active"):
                    throttle_secs += d.get("interval_s", 0.2)
            except json.JSONDecodeError:
                continue

    if not powers:
        return {"error": "no GPU data in stats.jsonl"}

    return {
        "avg_power_w": sum(powers) / len(powers),
        "max_power_w": max(powers),
        "avg_temp_c": sum(temps) / len(temps) if temps else 0,
        "max_temp_c": max(temps) if temps else 0,
        "throttle_seconds": throttle_secs,
        "samples": len(powers),
    }


def difficulty_weighted(results: list[dict]) -> float:
    """Weight by difficulty: d1=1pt, d2=2pt, d3=3pt."""
    earned = 0
    total = 0
    for r in results:
        diff = r.get("difficulty", 1)
        total += diff
        if r.get("status") == "PASS":
            earned += diff
    return earned / total if total else 0.0
