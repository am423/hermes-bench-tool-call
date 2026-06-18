"""Tests for scoring aggregation and category breakdown."""

import json
import tempfile
from pathlib import Path

from hermesbench.scoring import aggregate_results, category_breakdown, difficulty_weighted


def test_aggregate_results():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "run" / "t01_smoke" / "t01_echo"
        d.mkdir(parents=True)
        (d / "verifier_result.json").write_text(
            json.dumps({"task_id": "t01_smoke/t01_echo", "status": "PASS", "difficulty": 1})
        )
        results = aggregate_results([tmp])
        assert len(results) == 1
        assert results[0]["status"] == "PASS"


def test_category_breakdown():
    results = [
        {"task_id": "t01_smoke/echo", "status": "PASS"},
        {"task_id": "t01_smoke/ls", "status": "FAIL"},
        {"task_id": "t02_read/head", "status": "PASS"},
    ]
    cats = category_breakdown(results)
    assert cats["t01_smoke"] == (1, 2)
    assert cats["t02_read"] == (1, 1)


def test_difficulty_weighted():
    results = [
        {"task_id": "a", "status": "PASS", "difficulty": 1},
        {"task_id": "b", "status": "FAIL", "difficulty": 3},
        {"task_id": "c", "status": "PASS", "difficulty": 2},
    ]
    assert difficulty_weighted(results) == 0.5
