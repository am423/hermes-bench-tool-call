"""GPU stats: NVIDIA via pynvml, AMD/Intel via sysfs.

Q15: hard dep on pynvml when an NVIDIA GPU is present; graceful
degrade to sysfs for AMD/Intel.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_NVML_INITIALIZED = False
_NVML_HANDLE: list = []


def _init_nvml() -> bool:
    global _NVML_INITIALIZED, _NVML_HANDLE
    if _NVML_INITIALIZED:
        return len(_NVML_HANDLE) > 0
    try:
        import pynvml  # type: ignore[import-not-found]
    except ImportError:
        _NVML_INITIALIZED = True
        return False
    try:
        pynvml.nvmlInit()
        count = pynvml.nvmlDeviceGetCount()
        for i in range(count):
            _NVML_HANDLE.append(pynvml.nvmlDeviceGetHandleByIndex(i))
        _NVML_INITIALIZED = True
        return count > 0
    except Exception as e:
        logger.debug("nvmlInit failed: %s", e)
        _NVML_INITIALIZED = True
        return False


def _read_nvidia(handle) -> dict:
    import pynvml  # type: ignore[import-not-found]

    name = pynvml.nvmlDeviceGetName(handle)
    if isinstance(name, bytes):
        name = name.decode("utf-8", "replace")
    name = str(name)
    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
    try:
        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
    except Exception:
        temp = None
    try:
        power_mw = pynvml.nvmlDeviceGetPowerUsage(handle)
        power_w = float(power_mw) / 1000.0
    except Exception:
        power_w = None
    try:
        power_limit_mw = pynvml.nvmlDeviceGetPowerManagementLimit(handle)
        power_limit_w = float(power_limit_mw) / 1000.0
    except Exception:
        power_limit_w = None
    try:
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        vram_used_mib = float(mem.used) / (1024 * 1024)
        vram_total_mib = float(mem.total) / (1024 * 1024)
    except Exception:
        vram_used_mib = None
        vram_total_mib = None
    throttle_raw = 0
    return {
        "vendor": "nvidia",
        "name": name,
        "util_pct": util.gpu,
        "mem_util_pct": util.memory,
        "temp_c": float(temp) if temp is not None else None,
        "power_w": power_w,
        "power_limit_w": power_limit_w,
        "vram_used_mib": vram_used_mib,
        "vram_total_mib": vram_total_mib,
        "throttle_reasons": [hex(throttle_raw)] if throttle_raw else [],
    }


def _read_amd_intel_sysfs() -> list[dict]:
    """Best-effort AMD/Intel GPU stats from /sys/class/drm/card*/device/hwmon/."""
    out: list[dict] = []
    for card in Path("/sys/class/drm").glob("card*"):
        device = card / "device"
        for hwmon in device.glob("hwmon/hwmon*"):
            name = (hwmon / "name").read_text().strip() if (hwmon / "name").exists() else ""
            if name not in ("amdgpu", "i915", "xe"):
                continue
            entry: dict = {"vendor": name, "name": f"card{card.name.split('card')[-1]}"}
            t = hwmon / "temp1_input"
            if t.exists():
                with contextlib.suppress(ValueError):
                    entry["temp_c"] = int(t.read_text().strip()) / 1000.0
            p = hwmon / "power1_average"
            if p.exists():
                with contextlib.suppress(ValueError):
                    entry["power_w"] = int(p.read_text().strip()) / 1_000_000.0
            out.append(entry)
    return out


def sample() -> list[dict]:
    """Return a list of GPU stats (one per device). Empty list if no GPU."""
    if _init_nvml() and _NVML_HANDLE:
        return [_read_nvidia(h) for h in _NVML_HANDLE]
    return _read_amd_intel_sysfs()
