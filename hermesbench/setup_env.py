"""Create repo venv and install hermesbench."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def ensure_repo_venv(*, dev: bool = False) -> Path:
    venv_dir = REPO / ".venv"
    py = venv_dir / "bin" / "python"
    if not py.is_file():
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True, cwd=REPO)
    subprocess.run([str(py), "-m", "pip", "install", "-U", "pip"], check=True)
    extra = ".[dev]" if dev else "."
    subprocess.run([str(py), "-m", "pip", "install", "-e", extra], check=True, cwd=REPO)
    return py


def check_hermes_agent(*, install_hint: bool = True) -> tuple[bool, str]:
    try:
        from hermesbench.hermes_invocation import find_hermes_agent, hermes_python

        path = find_hermes_agent()
        venv_py = path / ".venv" / "bin" / "python"
        if not venv_py.is_file():
            msg = (
                f"Hermes Agent at {path} has no .venv. Run:\n"
                f"  cd {path} && python3 -m venv .venv && .venv/bin/pip install -e ."
            )
            return False, msg
        r = subprocess.run(
            [hermes_python(path), "-c", "import fire"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if r.returncode != 0:
            msg = f"Hermes venv missing deps. Run: cd {path} && .venv/bin/pip install -e ."
            return False, msg
        return True, str(path)
    except FileNotFoundError:
        msg = (
            "Hermes Agent not found. Clone and install:\n"
            "  git clone https://github.com/NousResearch/hermes-agent ~/.hermes/hermes-agent\n"
            "  cd ~/.hermes/hermes-agent && python3 -m venv .venv && .venv/bin/pip install -e .\n"
            "Or set HERMES_AGENT_PATH to your checkout."
        )
        return False, msg
