"""hermesbench/config.py — load hermesbench.yaml defaults."""

from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATHS = [
    Path.cwd() / "hermesbench.yaml",
    Path.home() / ".hermesbench.yaml",
]


def load_config(path: str | None = None) -> dict[str, Any]:
    """Load config from hermesbench.yaml. Returns {} if not found."""
    paths = [Path(path)] if path else DEFAULT_CONFIG_PATHS
    for p in paths:
        if p.exists():
            with open(p) as f:
                return yaml.safe_load(f) or {}
    return {}
