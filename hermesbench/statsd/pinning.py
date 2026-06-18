"""Core-pin + nice + ionice for the statsd process.

The statsd process must not perturb the model's runtime. We
detect the model's process tree, pick a sibling core with the
lowest current util, and pin to it. If no quiet core is found,
we log a warning (Q62) and fall back to non-pinned.
"""

from __future__ import annotations

import contextlib
import logging
import os
import subprocess

import psutil

logger = logging.getLogger(__name__)

IDLE_UTIL_THRESHOLD = 25.0  # % utilization considered "quiet"


def find_quiet_core() -> int | None:
    """Return the logical core with the lowest current util, or None.

    Requires psutil.cpu_percent(percpu=True) which is a non-blocking
    call that returns the util since the last call. Call it once
    first to seed, then again to get the real values.
    """
    psutil.cpu_percent(percpu=True, interval=None)  # seed
    import time as _t

    _t.sleep(0.1)
    utils = psutil.cpu_percent(percpu=True, interval=None)
    if not utils:
        return None
    quiet = [i for i, u in enumerate(utils) if u < IDLE_UTIL_THRESHOLD]
    if not quiet:
        return None
    # Pick the one with the lowest util among the quiet ones
    return min(quiet, key=lambda i: utils[i])


def lower_priority() -> None:
    """Lower this process's priority to IDLE (Q14, Q62)."""
    with contextlib.suppress(OSError):
        os.nice(19)
    # ionice: best-effort, only on Linux
    with contextlib.suppress(FileNotFoundError):
        subprocess.run(
            ["ionice", "-c", "3", "-p", str(os.getpid())],
            capture_output=True,
            check=False,
        )


def pin_to_core(core_id: int) -> None:
    """Pin this process to a single CPU core (Linux only)."""
    with contextlib.suppress(AttributeError, OSError):
        os.sched_setaffinity(0, {core_id})  # type: ignore[attr-defined]


def model_pids_alive(model_pids: list[int]) -> list[int]:
    """Return the subset of model_pids that are still alive."""
    return [pid for pid in model_pids if psutil.pid_exists(pid)]


def setup_statsd_process(model_pids: list[int]) -> int | None:
    """Apply the full priority-lowering + pinning setup.

    Returns the core we pinned to (or None if we couldn't pin).
    """
    lower_priority()
    core = find_quiet_core()
    if core is None:
        logger.warning("statsd pinned-core fallback engaged, measurement noise +X%")
        return None
    pin_to_core(core)
    logger.info("statsd pinned to core %d (model_pids=%s)", core, model_pids)
    return core
