"""hermesbench/metrics_panel.py — live GPU/vLLM telemetry panel."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
import urllib.request
from collections import deque
from pathlib import Path


class MetricsPanel:
    def __init__(
        self, vllm_url="http://127.0.0.1:8999", runner_log=None, update_hz=2, brand="@mr-r0b0t"
    ):
        self.vllm_url = vllm_url.rstrip("/")
        self.runner_log = runner_log
        self.interval = 1.0 / update_hz
        self.brand = brand
        self.history = {
            "gpu_util": deque(maxlen=60),
            "power": deque(maxlen=60),
            "temp": deque(maxlen=60),
        }
        self.energy_joules = 0.0
        self.tokens_generated = 0
        self.last_power = 0.0
        self.last_time = time.time()
        self.tasks_done = 0
        self.tasks_pass = 0
        tasks_dir = Path(__file__).resolve().parent.parent / "tasks"
        self.tasks_total = len(list(tasks_dir.rglob("task.yaml")))
        self.start_time = time.time()
        self.current_task = ""

    def poll_gpu(self):
        try:
            out = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,temperature.gpu,"
                    "power.draw,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                timeout=5,
            )
            p = out.strip().split(",")
            return {
                "util": int(p[0].strip()),
                "temp": int(p[1].strip()),
                "power": float(p[2].strip()),
                "mem_used": int(p[3].strip()),
                "mem_total": int(p[4].strip()),
            }
        except Exception:
            return None

    def poll_vllm(self):
        try:
            with urllib.request.urlopen(f"{self.vllm_url}/metrics", timeout=3) as r:
                text = r.read().decode()
            m = {}
            for line in text.splitlines():
                if line.startswith("#"):
                    continue
                if "generation_throughput" in line:
                    v = re.search(r"\s+([\d.]+)$", line)
                    if v:
                        m["decode_tps"] = float(v.group(1))
                elif "gpu_cache_usage_perc" in line:
                    v = re.search(r"\s+([\d.]+)$", line)
                    if v:
                        m["cache_usage"] = float(v.group(1))
                elif "generation_tokens_total" in line and "{" not in line:
                    v = re.search(r"\s+(\d+)$", line)
                    if v:
                        m["gen_tokens"] = int(v.group(1))
            return m
        except Exception:
            return {}

    def parse_runner_log(self):
        if not self.runner_log or not os.path.exists(self.runner_log):
            return
        try:
            with open(self.runner_log) as f:
                lines = f.readlines()
            self.tasks_pass = sum(1 for line in lines if "PASS" in line)
            fail = sum(1 for line in lines if "FAIL" in line)
            self.tasks_done = self.tasks_pass + fail
            for line in reversed(lines):
                m = re.match(r"\s*-> (.+?)\.\.\.", line)
                if m:
                    self.current_task = m.group(1)
                    break
        except Exception:
            pass

    def sparkline(self, data, width=20):
        if not data:
            return ""
        fill = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"
        lo, hi = min(data), max(data)
        if hi == lo:
            return fill[3] * min(len(data), width)
        scaled = [int((v - lo) / (hi - lo) * (len(fill) - 1)) for v in data]
        return "".join(fill[i] for i in scaled[-width:])

    def render(self):
        gpu = self.poll_gpu()
        vllm = self.poll_vllm()
        self.parse_runner_log()

        if gpu:
            self.history["gpu_util"].append(gpu["util"])
            self.history["power"].append(gpu["power"])
            self.history["temp"].append(gpu["temp"])
            now = time.time()
            dt = now - self.last_time
            self.energy_joules += self.last_power * dt
            self.last_power = gpu["power"]
            self.last_time = now
            if "gen_tokens" in vllm:
                self.tokens_generated = vllm["gen_tokens"]

        elapsed = time.time() - self.start_time
        self.tasks_done / self.tasks_total * 100 if self.tasks_total else 0
        (
            elapsed / self.tasks_done * (self.tasks_total - self.tasks_done)
            if self.tasks_done > 0
            else 0
        )
        self.energy_joules / self.tokens_generated if self.tokens_generated > 0 else 0

        os.system("clear")
        if gpu:
            pass
        sys.stdout.flush()

    def run(self):
        while True:
            self.render()
            time.sleep(self.interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--vllm-url", default="http://127.0.0.1:8999")
    parser.add_argument("--runner-log", default=None)
    parser.add_argument("--brand", default="@mr-r0b0t")
    args = parser.parse_args()
    MetricsPanel(vllm_url=args.vllm_url, runner_log=args.runner_log, brand=args.brand).run()
