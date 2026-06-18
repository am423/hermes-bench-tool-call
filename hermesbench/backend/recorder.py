"""pyte-based asciinema v2 recorder.

Reads ANSI escape sequences from stdin (typically piped from
`tmux pipe-pane`) and writes an asciinema v2 .cast file to the
output path. Uses `pyte` to maintain a screen buffer, then flushes
diffs at a 100ms tick.

Asciinema v2 format: each frame is a JSON array
`[<time_seconds>, "o", "<text>"]` written one per line.

Run standalone:
    python -m hermesbench.backend.recorder --out /tmp/x.cast --cols 200 --rows 50

The Q3.1a test (`test_recorder_roundtrip`) verifies that a
5-line bash session produces a valid .cast that re-renders.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    import pyte
except ImportError as e:  # pragma: no cover
    raise SystemExit(2) from e


def _screen_to_text(screen: pyte.Screen) -> str:
    """Render the pyte screen buffer as a list of lines.

    Compatible with pyte 0.8.x (Char dataclass with .data) and
    0.9+ if it ever changes shape again.
    """
    lines: list[str] = []
    for y in range(screen.lines):
        row = screen.buffer[y]
        # pyte 0.8.x: row is a StaticDefaultDict of (x -> Char)
        text = "".join(_char_data(ch) for ch in row.values())
        lines.append(text.rstrip())
    return "\r\n".join(lines)


def _char_data(ch: object) -> str:
    """Extract the data from a pyte Char-like object.

    Works for:
    - pyte 0.8.x: Char(data='x', fg=..., bg=..., ...)
    - pyte < 0.8: (char, attr) tuples (legacy)
    """
    data = getattr(ch, "data", None)
    if data is not None:
        return str(data)
    if isinstance(ch, (tuple, list)) and len(ch) >= 1:
        return str(ch[0])
    return str(ch)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="pyte -> asciinema v2 recorder")
    p.add_argument("--out", required=True, type=Path, help=".cast output file")
    p.add_argument("--cols", type=int, default=200)
    p.add_argument("--rows", type=int, default=50)
    p.add_argument("--tick-ms", type=int, default=100, help="Flush interval")
    args = p.parse_args(argv)

    screen = pyte.Screen(args.cols, args.rows)
    stream = pyte.Stream(screen)

    # Write the asciinema v2 header
    args.out.parent.mkdir(parents=True, exist_ok=True)
    header = json.dumps(
        {
            "version": 2,
            "width": args.cols,
            "height": args.rows,
            "timestamp": int(time.time()),
            "env": {"TERM": "xterm-256color", "SHELL": "/bin/bash"},
        }
    )
    with args.out.open("w") as f:
        f.write(header + "\n")

    screen = pyte.Screen(args.cols, args.rows)
    stream = pyte.Stream(screen)

    # Write an initial blank frame so consumers know the recorder is alive
    initial = _screen_to_text(screen) + "\r\n"
    with args.out.open("a") as f:
        f.write(json.dumps([0.0, "o", initial]) + "\n")

    start = time.time()
    last_text = initial

    # Read raw bytes from stdin (the tmux pipe-pane output)
    # pyte.Stream.feed expects str
    import select

    last_flush = start
    iterations = 0
    bytes_read = 0
    while True:
        # Read available input (non-blocking-ish)
        rlist, _, _ = select.select([sys.stdin], [], [], args.tick_ms / 1000.0)
        if rlist:
            chunk = sys.stdin.read(4096)
            if not chunk:
                break  # EOF
            bytes_read += len(chunk)
            stream.feed(chunk)
            # Debug: write to stderr so test can capture
            if os.environ.get("HERMESBENCH_DEBUG"):
                pass
        # Flush if enough time has passed
        now = time.time()
        if now - last_flush >= args.tick_ms / 1000.0:
            text = _screen_to_text(screen)
            # Always write at least one frame after first input arrives
            if text != last_text:
                rel_t = now - start
                frame = json.dumps([round(rel_t, 3), "o", text + "\r\n"])
                with args.out.open("a") as f:
                    f.write(frame + "\n")
                last_text = text
            last_flush = now
        iterations += 1
        if iterations > 2000:  # safety: max 200s of recording
            break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
