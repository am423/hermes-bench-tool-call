from __future__ import annotations

import json
from pathlib import Path

from hermesbench.report import generate_run_html_report
from hermesbench.reporting import generate_run_artifacts


def test_generate_run_artifacts_writes_canonical_html_report(tmp_path: Path) -> None:
    repo = tmp_path
    run_id = "demo_run"
    results = repo / "results" / run_id
    results.mkdir(parents=True)
    (repo / "tasks" / "t01_terminal_smoke" / "t01_echo").mkdir(parents=True)
    (repo / "tasks" / "t01_terminal_smoke" / "t01_echo" / "task.yaml").write_text(
        """
id: t01_terminal_smoke/t01_echo
name: Echo a string
prompt: |
  Run echo hello.
allowed_tools:
  - terminal
timeout_seconds: 60
""".strip()
        + "\n",
        encoding="utf-8",
    )
    summary = {
        "run_id": run_id,
        "model": "demo-model",
        "base_url": "http://127.0.0.1:8000/v1",
        "toolsets": "all",
        "hermes_sha": "abc123",
        "passed": 1,
        "tasks": [
            {
                "task_id": "t01_terminal_smoke/t01_echo",
                "name": "Echo a string",
                "difficulty": 1,
                "status": "PASS",
                "reason": "ok",
                "elapsed_seconds": 1.5,
                "trace": "/tmp/trace.jsonl",
                "raw_log": "/tmp/run_agent.log",
                "verifier_result": "/tmp/verifier_result.json",
            }
        ],
    }
    (results / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    paths = generate_run_artifacts(repo, run_id)

    html_path = paths["html_report"]
    assert html_path == results / "report.html"
    html = html_path.read_text(encoding="utf-8")
    assert "HermesBench" in html
    assert "demo-model" in html
    assert "Run echo hello." in html
    assert "t01_terminal_smoke/t01_echo" in html


def test_generate_run_html_report_supports_infra_status(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "run_id": "infra_run",
                "model": "demo-model",
                "tasks": [
                    {
                        "task_id": "t05_write_new/t01_basic",
                        "name": "Write a new file",
                        "difficulty": 1,
                        "status": "INFRA_ERROR",
                        "reason": "infrastructure/API failure: APIConnectionError",
                        "elapsed_seconds": 2,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    out = generate_run_html_report(summary_path, repo_root=tmp_path)
    html = out.read_text(encoding="utf-8")
    assert "INFRA_ERROR" in html
    assert "APIConnectionError" in html
