from __future__ import annotations

import subprocess
from pathlib import Path

from hermesbench.run_real import _detect_infra_error


def test_detect_infra_error_for_connection_failure_without_trajectory(tmp_path: Path) -> None:
    log = tmp_path / "run_agent.log"
    log.write_text("API call failed after 3 retries: Connection error.\n", encoding="utf-8")
    completed = subprocess.CompletedProcess(["run_agent.py"], 1, "", "")

    reason = _detect_infra_error(
        completed=completed,
        log_path=log,
        selected_trajectory_path=None,
    )

    assert reason is not None
    assert "infrastructure/API failure" in reason


def test_detect_infra_error_does_not_mask_model_failure_with_trajectory(tmp_path: Path) -> None:
    log = tmp_path / "run_agent.log"
    log.write_text("APIConnectionError happened earlier but trajectory exists\n", encoding="utf-8")
    trajectory = tmp_path / "failed_trajectories.jsonl"
    trajectory.write_text("{}\n", encoding="utf-8")
    completed = subprocess.CompletedProcess(["run_agent.py"], 1, "", "")

    reason = _detect_infra_error(
        completed=completed,
        log_path=log,
        selected_trajectory_path=trajectory,
    )

    assert reason is None
