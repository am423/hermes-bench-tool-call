"""hermesbench/record.py — hyperframes 5-pane video capture."""

from __future__ import annotations

import contextlib
import os
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class HyperframesRecorder:
    def __init__(
        self,
        model,
        base_url,
        output="videos/hyperframes.mp4",
        duration=1800,
        real_agent=True,
        session_name="hb-record",
        attach_mode=False,
    ):
        self.model = model
        self.base_url = base_url
        self.output = str(Path(output).resolve())
        self.duration = duration
        self.real_agent = real_agent
        self.session = session_name
        self.attach_mode = attach_mode
        self.trigger = f"/tmp/{session_name}_go"
        self.runner_log = f"/tmp/{session_name}_runner.log"

    def _tmux(self, *args):
        return subprocess.run(["tmux", *args], capture_output=True, text=True)

    def build_armed_session(self):
        self._tmux("kill-session", "-t", self.session)

        def armed(title, cmd):
            return (
                f"printf '\\033]2;{title}\\033\\\\'; "
                f"tput civis; "
                f"echo '  ARMED: {title}'; "
                f"while [ ! -f {self.trigger} ]; do sleep 0.2; done; "
                f"clear; {cmd}"
            )

        real_flag = "--real-agent" if self.real_agent else ""
        runner_cmd = (
            f"cd {REPO_ROOT} && "
            f"python3 -m hermesbench run --all "
            f"--model {self.model} --base-url {self.base_url} "
            f"{real_flag} 2>&1 | tee {self.runner_log}"
        )
        vllm_base = self.base_url.rsplit("/v1", 1)[0].rstrip("/")
        metrics_cmd = (
            f"python3 -m hermesbench.metrics_panel "
            f"--vllm-url {vllm_base} --runner-log {self.runner_log}"
        )
        agent_cmd = (
            f"while true; do "
            f"  S=$(tmux list-sessions 2>/dev/null | "
            f"grep 'hb-' | grep -v '{self.session}' | "
            f"head -1 | cut -d: -f1); "
            f'  if [ -n "$S" ]; then tmux capture-pane -t "$S" -p -S -20; '
            f"  else echo '(waiting for agent session...)'; fi; "
            f"  sleep 1; done"
        )
        score_cmd = (
            f"while true; do clear; "
            f"  P=$(grep -c PASS {self.runner_log} 2>/dev/null || echo 0); "
            f"  F=$(grep -c FAIL {self.runner_log} 2>/dev/null || echo 0); "
            f"  echo '  Scoreboard: PASS:' $P 'FAIL:' $F; sleep 2; done"
        )
        telemetry_cmd = (
            "while true; do "
            "  nvidia-smi --query-gpu=utilization.gpu,temperature.gpu,power.draw "
            "--format=csv,noheader,nounits 2>/dev/null | "
            "awk -F, '{printf \"GPU: %s%%  Temp: %sC  Pwr: %sW\\n\", $1, $2, $3}'; "
            "  sleep 1; done"
        )

        r = self._tmux(
            "new-session",
            "-d",
            "-s",
            self.session,
            "-x",
            "200",
            "-y",
            "56",
            "-P",
            "-F",
            "#{pane_id}",
            armed("Runner", runner_cmd),
        )
        pane0 = r.stdout.strip()

        r = self._tmux(
            "split-window",
            "-h",
            "-t",
            pane0,
            "-l",
            "45%",
            "-P",
            "-F",
            "#{pane_id}",
            armed("Metrics", metrics_cmd),
        )
        pane1 = r.stdout.strip()

        r = self._tmux(
            "split-window",
            "-v",
            "-t",
            pane0,
            "-l",
            "55%",
            "-P",
            "-F",
            "#{pane_id}",
            armed("Agent", agent_cmd),
        )
        pane2 = r.stdout.strip()

        r = self._tmux(
            "split-window",
            "-v",
            "-t",
            pane1,
            "-l",
            "55%",
            "-P",
            "-F",
            "#{pane_id}",
            armed("Scoreboard", score_cmd),
        )
        r.stdout.strip()

        r = self._tmux(
            "split-window",
            "-v",
            "-t",
            pane2,
            "-l",
            "20%",
            "-P",
            "-F",
            "#{pane_id}",
            armed("Telemetry", telemetry_cmd),
        )

        self._tmux("select-layout", "-t", f"{self.session}:0", "tiled")
        self._tmux("set-option", "-t", self.session, "pane-border-status", "top")
        self._tmux(
            "set-option",
            "-t",
            self.session,
            "pane-border-format",
            "#[bold,fg=cyan] #{pane_index}: #[fg=yellow]#{pane_title} ",
        )
        self._tmux("set-option", "-t", self.session, "status-left", "#[bold,fg=green] HYPERFRAMES ")

        self._tmux(
            "list-panes", "-t", self.session, "-F", "#{pane_index}: #{pane_width}x#{pane_height}"
        )

    def run_headless(self):
        display = ":98"
        xvfb = subprocess.Popen(["Xvfb", display, "-screen", "0", "1920x1080x24", "-nocursor"])
        time.sleep(2)
        xterm = subprocess.Popen(
            [
                "xterm",
                "-display",
                display,
                "-geometry",
                "240x65+0+0",
                "-bg",
                "#0a0a14",
                "-fg",
                "#e0e0e8",
                "-cr",
                "#0a0a14",
                "-ms",
                "#0a0a14",
                "-xrm",
                "XTerm*cursorBlink: false",
                "-fa",
                "Monospace",
                "-fs",
                "9",
                "-e",
                "tmux",
                "attach",
                "-t",
                self.session,
            ]
        )
        time.sleep(3)
        ffmpeg = subprocess.Popen(
            [
                "ffmpeg",
                "-y",
                "-f",
                "x11grab",
                "-draw_mouse",
                "0",
                "-video_size",
                "1920x1080",
                "-framerate",
                "30",
                "-i",
                display,
                "-t",
                str(self.duration),
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                self.output,
            ]
        )
        time.sleep(2)
        Path(self.trigger).touch()
        try:
            ffmpeg.wait(timeout=self.duration + 30)
        except subprocess.TimeoutExpired:
            ffmpeg.terminate()
        for p in [xterm, xvfb]:
            with contextlib.suppress(Exception):
                p.terminate()
        out = Path(self.output)
        size_mb = out.stat().st_size / 1e6 if out.exists() else 0
        if size_mb > 1.0:
            pass
        else:
            pass

    def run(self):
        os.makedirs(Path(self.output).parent, exist_ok=True)
        if os.path.exists(self.trigger):
            os.remove(self.trigger)
        self.build_armed_session()
        if self.attach_mode:
            return
        input()
        self.run_headless()
        self._tmux("kill-session", "-t", self.session)
