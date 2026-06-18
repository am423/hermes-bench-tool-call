"""Model process tree: RSS, threads, %CPU, %MEM, num FDs (Q41)."""

from __future__ import annotations

import contextlib

import psutil


def sample(pids: list[int]) -> dict | None:
    """Return aggregate process stats for the model + its children.

    Returns None if all pids are dead.
    """
    total_rss = 0
    total_threads = 0
    total_cpu = 0.0
    total_fds = 0
    n = 0
    for pid in pids:
        try:
            p = psutil.Process(pid)
            with p.oneshot():
                total_rss += p.memory_info().rss
                total_threads += p.num_threads()
                total_cpu += p.cpu_percent(interval=None)
                with contextlib.suppress(psutil.AccessDenied, OSError):
                    total_fds += len(p.open_files())
            n += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    if n == 0:
        return None
    return {
        "n_procs": n,
        "rss_mib": total_rss / (1024 * 1024),
        "threads": total_threads,
        "cpu_pct": total_cpu,
        "num_fds": total_fds,
    }
