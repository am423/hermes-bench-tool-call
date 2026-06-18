"""Q-test: per-source sampling functions return the expected schema."""

from __future__ import annotations

from hermesbench.statsd.sources import cpu, gpu_nvidia, memory, nvme, process


def test_cpu_sample_shape() -> None:
    s = cpu.sample()
    assert "per_core_util" in s
    assert "util_pct" in s
    assert "pkg_temp_c" in s
    assert isinstance(s["per_core_util"], list)
    assert isinstance(s["util_pct"], (int, float))


def test_gpu_sample_shape() -> None:
    s = gpu_nvidia.sample()
    assert isinstance(s, list)
    if s:  # there might not be a GPU in CI
        g = s[0]
        assert "name" in g
        assert "util_pct" in g
        assert "temp_c" in g
        assert "power_w" in g


def test_memory_sample_shape() -> None:
    s = memory.sample()
    assert "used_mib" in s
    assert "total_mib" in s
    assert s["total_mib"] > 0


def test_nvme_sample_shape() -> None:
    s = nvme.sample()
    # s is None if no NVMe hwmon
    if s is not None:
        assert "temp_c" in s


def test_process_sample_shape() -> None:
    import os

    s = process.sample([os.getpid()])
    if s is not None:
        assert "rss_mib" in s
        assert "threads" in s
        assert "cpu_pct" in s
        assert s["n_procs"] >= 1
