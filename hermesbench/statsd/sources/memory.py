"""RAM and swap stats."""

from __future__ import annotations

import psutil


def sample() -> dict:
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    return {
        "used_mib": vm.used / (1024 * 1024),
        "total_mib": vm.total / (1024 * 1024),
        "available_mib": vm.available / (1024 * 1024),
        "percent": vm.percent,
        "swap_mib": sw.used / (1024 * 1024),
    }
