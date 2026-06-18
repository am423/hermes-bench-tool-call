"""Q74: tests for the scoring pipeline.

Covers: hardware metrics computation, thermal AUC, pass_rate_by_difficulty,
thermal-state-aware comparison, hardware summary schema.
"""

from __future__ import annotations

import json
from pathlib import Path

from hermesbench.scoring import (
    compute_gen_joules_per_token,
    compute_hardware_metrics,
    join_trace_stats,
    psutil_cpu_count,
    score_run,
)
from hermesbench.types import HardwareMetrics


def test_compute_hardware_metrics_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "empty.stats.jsonl"
    p.write_text("")
    hw = compute_hardware_metrics(p)
    assert isinstance(hw, HardwareMetrics)
    assert hw.mean_gpu_power_w is None


def test_compute_hardware_metrics_with_data(tmp_path: Path) -> None:
    p = tmp_path / "stats.jsonl"
    samples = [
        {
            "t": 0.0,
            "cpu": {
                "util_pct": 50.0,
                "pkg_temp_c": 60.0,
                "pkg_power_w": 100.0,
                "per_core_util": [50, 50],
            },
            "gpu": [
                {
                    "name": "RTX 3090",
                    "util_pct": 90,
                    "temp_c": 75.0,
                    "power_w": 300.0,
                    "throttle_reasons": [],
                }
            ],
            "ram": {"used_mib": 10000, "total_mib": 60000},
            "nvme": {"temp_c": 40.0},
        },
        {
            "t": 0.2,
            "cpu": {
                "util_pct": 60.0,
                "pkg_temp_c": 65.0,
                "pkg_power_w": 110.0,
                "per_core_util": [60, 60],
            },
            "gpu": [
                {
                    "name": "RTX 3090",
                    "util_pct": 95,
                    "temp_c": 80.0,
                    "power_w": 320.0,
                    "throttle_reasons": [],
                }
            ],
            "ram": {"used_mib": 11000, "total_mib": 60000},
            "nvme": {"temp_c": 41.0},
        },
    ]
    p.write_text("\n".join(json.dumps(s) for s in samples))
    hw = compute_hardware_metrics(p)
    assert hw.mean_gpu_power_w == 310.0  # (300 + 320) / 2
    assert hw.peak_gpu_temp_c == 80.0
    assert hw.mean_cpu_power_w == 105.0
    assert hw.nvme_temp_c == 41.0
    assert hw.thermal_warning() is None  # 80 < 90


def test_compute_hardware_metrics_thermal_warning(tmp_path: Path) -> None:
    p = tmp_path / "stats.jsonl"
    p.write_text(
        json.dumps(
            {
                "t": 0.0,
                "cpu": {"util_pct": 50, "pkg_temp_c": 60},
                "gpu": [
                    {
                        "name": "X",
                        "util_pct": 99,
                        "temp_c": 92.0,
                        "power_w": 300,
                        "throttle_reasons": [],
                    }
                ],
                "ram": {"used_mib": 1000},
                "nvme": None,
            }
        )
    )
    hw = compute_hardware_metrics(p)
    warn = hw.thermal_warning()
    assert warn is not None
    assert "92" in str(warn)


def test_join_trace_stats_empty() -> None:
    assert join_trace_stats([], []) == []
    assert join_trace_stats([{"role": "user"}], [{"t": 0}]) == []


def test_join_trace_stats_with_messages(tmp_path: Path) -> None:
    trace = [
        {"role": "system"},
        {"role": "user", "ts": 0.5},
        {"role": "assistant", "ts": 1.0, "completion_token_ids": [1, 2, 3, 4, 5]},
        {"role": "tool", "ts": 1.5},
    ]
    stats = [
        {"t": 0.0, "gpu": [{"power_w": 100}]},
        {"t": 1.0, "gpu": [{"power_w": 200}]},
    ]
    joined = join_trace_stats(trace, stats, tolerance_s=0.1)
    assert len(joined) == 1
    power, tok = joined[0]
    assert power == 200
    assert tok == 5


def test_compute_gen_joules_per_token_empty() -> None:
    assert compute_gen_joules_per_token([]) is None


def test_compute_gen_joules_per_token_basic() -> None:
    # 100W during gen of 10 tokens
    result = compute_gen_joules_per_token([(100.0, 10)])
    assert result is not None
    assert result == 10.0  # 100W / (10tok / 1s) = 10 J/tok


def test_score_run_empty_dir(tmp_path: Path) -> None:
    summary = score_run(tmp_path, tmp_path)
    assert summary["pass_rate"] == 0.0
    assert summary["tasks"] == []


def test_score_run_with_passed_task(tmp_path: Path) -> None:
    # Set up: results/<run>/<task>/verifier_result.json
    task_dir = tmp_path / "run1" / "t01_x"
    task_dir.mkdir(parents=True)
    (task_dir / "verifier_result.json").write_text(
        json.dumps({"status": "PASS", "difficulty": 1, "score": 1.0})
    )
    (task_dir / "stats.jsonl").write_text(
        json.dumps(
            {
                "t": 0.0,
                "cpu": {"util_pct": 50, "pkg_temp_c": 60},
                "gpu": [
                    {
                        "name": "X",
                        "util_pct": 90,
                        "temp_c": 80,
                        "power_w": 300,
                        "throttle_reasons": [],
                    }
                ],
                "ram": {"used_mib": 1000},
                "nvme": None,
            }
        )
    )
    summary = score_run(tmp_path, tmp_path / "run1")
    assert summary["pass_rate"] == 1.0
    assert summary["by_difficulty"][1] == 1
    assert summary["by_difficulty_passed"][1] == 1
    assert len(summary["tasks"]) == 1
    assert summary["tasks"][0]["verifier"]["status"] == "PASS"


def test_psutil_cpu_count() -> None:
    n = psutil_cpu_count()
    assert n >= 1
