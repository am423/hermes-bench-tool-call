"""NVMe temperature (Q41)."""

from __future__ import annotations

from pathlib import Path


def sample() -> dict | None:
    """Read the first NVMe device's temperature from sysfs."""
    for hwmon in Path("/sys/class/hwmon").glob("hwmon*"):
        name_file = hwmon / "name"
        if not name_file.exists():
            continue
        if name_file.read_text().strip() != "nvme":
            continue
        temp_file = hwmon / "temp1_input"
        if temp_file.exists():
            try:
                return {"temp_c": int(temp_file.read_text().strip()) / 1000.0}
            except ValueError:
                continue
    return None
