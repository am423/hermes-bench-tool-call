"""Main collector loop: 5 Hz by default, writes one JSON line per sample.

Run as: `python -m hermesbench.statsd --out /path/to/stats.jsonl --hz 5`
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Make hermesbench importable when run as a module
_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from hermesbench.statsd import pinning  # noqa: E402
from hermesbench.statsd.sources import cpu, gpu_nvidia, memory, nvme, process  # noqa: E402

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="hermesbench system statistics collector")
    p.add_argument("--out", required=True, type=Path, help=".stats.jsonl output")
    p.add_argument("--hz", type=float, default=5.0, help="samples per second")
    p.add_argument(
        "--model-pids",
        type=int,
        nargs="*",
        default=[],
        help="PIDs to track (the model process tree)",
    )
    p.add_argument(
        "--no-pin",
        action="store_true",
        help="Skip core pinning (Q62 fallback)",
    )
    args = p.parse_args(argv)

    # Lower our own priority
    if not args.no_pin:
        pinned_core = pinning.setup_statsd_process(args.model_pids)
        if pinned_core is None:
            logger.warning("statsd pinned-core fallback engaged, measurement noise +X%")
    else:
        pinning.lower_priority()

    args.out.parent.mkdir(parents=True, exist_ok=True)

    interval = 1.0 / args.hz
    start = time.time()
    prev_rapl_uj: int | None = None
    prev_rapl_t: float | None = None
    sample_idx = 0

    # Initial sample (so downstream consumers don't have to handle "empty file")
    while True:
        try:
            t = time.time() - start
            cpu_data = cpu.sample()
            gpu_data = gpu_nvidia.sample()
            ram_data = memory.sample()
            nvme_data = nvme.sample()
            proc_data = process.sample(args.model_pids) if args.model_pids else None

            # RAPL delta
            pkg_power_w = None
            try:
                energy_uj_file = Path("/sys/class/powercap/intel-rapl:0/energy_uj")
                if energy_uj_file.exists():
                    cur_uj = int(energy_uj_file.read_text().strip())
                    cur_t = time.time()
                    if prev_rapl_uj is not None:
                        d_uj = cur_uj - prev_rapl_uj
                        d_t = cur_t - (prev_rapl_t or cur_t)
                        if d_t > 0:
                            pkg_power_w = (d_uj / 1_000_000) / d_t
                    prev_rapl_uj = cur_uj
                    prev_rapl_t = cur_t
            except (FileNotFoundError, PermissionError, ValueError):
                pass
            cpu_data["pkg_power_w"] = pkg_power_w

            record = {
                "t": t,
                "sample_idx": sample_idx,
                "elapsed_s": t,
                "cpu": cpu_data,
                "gpu": gpu_data,
                "ram": ram_data,
                "nvme": nvme_data,
                "model_process": proc_data,
            }
            with args.out.open("a") as f:
                f.write(json.dumps(record) + "\n")
            sample_idx += 1
        except Exception as e:
            logger.exception("sample failed: %s", e)
        time.sleep(interval)

    return 0  # unreachable


if __name__ == "__main__":
    raise SystemExit(main())
