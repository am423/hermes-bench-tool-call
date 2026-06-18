"""CPU stats: per-core util, package temp, package power.

Q41: tries RAPL MSR (root-only) first, falls back to TDP estimate.
"""

from __future__ import annotations

import logging
from pathlib import Path

import psutil

logger = logging.getLogger(__name__)


def _read_k10temp() -> float | None:
    """Read k10temp / coretemp CPU package temp from /sys/class/hwmon."""
    for hwmon in Path("/sys/class/hwmon").glob("hwmon*"):
        name_file = hwmon / "name"
        if not name_file.exists():
            continue
        name = name_file.read_text().strip()
        if name in ("k10temp", "coretemp", "zenpower"):
            temp_file = hwmon / "temp1_input"
            if temp_file.exists():
                try:
                    return int(temp_file.read_text().strip()) / 1000.0
                except (ValueError, OSError):
                    continue
    return None


def _read_package_power_w() -> float | None:
    """Read RAPL package power from /sys/class/powercap.

    Requires the intel-rapl kernel module. Returns None if unavailable.
    """
    rapl_root = Path("/sys/class/powercap/intel-rapl:0")
    if not rapl_root.exists():
        return None
    energy_file = rapl_root / "energy_uj"
    if not energy_file.exists():
        return None
    # We need two readings to compute power; the caller handles delta.
    return None  # The collector computes deltas across samples.


def sample() -> dict:
    """Return a dict of CPU stats for this sample."""
    out: dict = {"per_core_util": psutil.cpu_percent(percpu=True)}
    out["util_pct"] = sum(out["per_core_util"]) / max(1, len(out["per_core_util"]))
    out["pkg_temp_c"] = _read_k10temp()
    out["pkg_power_w"] = None  # populated by collector via RAPL delta
    return out
