"""hermesbench/render.py — render asciinema .cast to .gif or .mp4."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def render_cast(
    cast_path: str,
    fmt: str = "gif",
    out: str | None = None,
    overlay_stats: bool = False,
) -> str:
    """Render an asciinema .cast file to .gif or .mp4."""
    cast = Path(cast_path)
    if not cast.exists():
        raise FileNotFoundError(f"Cast file not found: {cast}")

    if not out:
        out = str(cast.with_suffix(f".{fmt}"))
    out_path = Path(out)

    if not shutil.which("agg"):
        raise RuntimeError(
            "agg not installed. Install: cargo install agg\nOr: https://github.com/asciinema/agg"
        )

    if fmt == "gif":
        subprocess.run(["agg", str(cast), str(out_path)], check=True)
    elif fmt == "mp4":
        with tempfile.NamedTemporaryFile(suffix=".gif", delete=False) as tmp:
            gif_tmp = tmp.name
        try:
            subprocess.run(["agg", str(cast), gif_tmp], check=True)
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    gif_tmp,
                    "-vf",
                    "fps=30",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    str(out_path),
                ],
                check=True,
            )
        finally:
            os.unlink(gif_tmp)
    else:
        raise ValueError(f"Unsupported format: {fmt}. Use 'gif' or 'mp4'.")

    return str(out_path)
