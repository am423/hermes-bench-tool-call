"""Tests for config loading."""

import os
import tempfile

from hermesbench.config import load_config


def test_load_config_from_file():
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write("model:\n  name: test-model\n  base_url: http://localhost:8000/v1\n")
        f.flush()
        cfg = load_config(f.name)
    os.unlink(f.name)
    assert cfg["model"]["name"] == "test-model"
    assert cfg["model"]["base_url"] == "http://localhost:8000/v1"


def test_load_config_missing_returns_empty():
    cfg = load_config("/nonexistent/path.yaml")
    assert cfg == {}


def test_load_config_defaults_from_cwd():
    cfg = load_config()
    assert isinstance(cfg, dict)
