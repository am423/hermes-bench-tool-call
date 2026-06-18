"""Environment checks and optional Python dependency installation for hermesbench."""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Maps import name -> pip package name when they differ
PIP_NAMES: dict[str, str] = {
    "yaml": "pyyaml",
}


@dataclass(frozen=True)
class Check:
    name: str
    required_for: frozenset[str]  # validate, run, run-real, render, video
    ok: bool
    remediation: str
    pip_package: str | None = None
    soft: bool = False  # failure does not fail doctor for run-real-only users


def _import_ok(module: str) -> bool:
    try:
        importlib.import_module(module)
        return True
    except ImportError:
        return False


def _repo_venv_python() -> Path | None:
    py = REPO_ROOT / ".venv" / "bin" / "python"
    return py if py.is_file() else None


def _hermes_fire_ok(hermes_path: Path) -> bool:
    from hermesbench.hermes_invocation import hermes_python

    try:
        r = subprocess.run(
            [hermes_python(hermes_path), "-c", "import fire"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return r.returncode == 0
    except Exception:
        return False


def _provider_configured() -> bool:
    import os

    if os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_BASE_URL"):
        return True
    cfg = Path.home() / ".hermes" / "config.yaml"
    return cfg.is_file()


def collect_checks(*, profile: str = "run-real") -> list[Check]:
    """Gather checks. profile filters which hard failures count."""
    checks: list[Check] = []

    py_ok = sys.version_info >= (3, 11)
    checks.append(
        Check(
            "python>=3.11",
            frozenset({"validate", "run", "run-real", "render", "video"}),
            py_ok,
            f"need Python 3.11+, have {sys.version.split()[0]}",
        )
    )

    venv_py = _repo_venv_python()
    checks.append(
        Check(
            "repo .venv",
            frozenset({"run-real"}),
            venv_py is not None,
            "run: hermesbench setup  (creates .venv and pip install -e .)",
            soft=True,
        )
    )

    for mod, pip_pkg in [
        ("yaml", "pyyaml"),
        ("pyte", "pyte"),
        ("psutil", "psutil"),
        ("rich", "rich"),
        ("click", "click"),
    ]:
        ok = _import_ok(mod)
        checks.append(
            Check(
                mod,
                frozenset({"validate", "run", "run-real"}),
                ok,
                "hermesbench doctor --install",
                pip_package=pip_pkg,
            )
        )

    pynvml_ok = _import_ok("pynvml")
    checks.append(
        Check(
            "pynvml",
            frozenset({"run", "run-real"}),
            pynvml_ok,
            "pip install pynvml (optional without NVIDIA GPU)",
            pip_package="pynvml",
            soft=True,
        )
    )

    checks.append(
        Check(
            "tmux",
            frozenset({"run"}),
            shutil.which("tmux") is not None,
            "sudo apt install tmux  (or brew install tmux)",
            soft=True,
        )
    )
    checks.append(
        Check(
            "bash",
            frozenset({"run", "run-real"}),
            shutil.which("bash") is not None,
            "",
        )
    )
    checks.append(
        Check(
            "ffmpeg",
            frozenset({"render", "video"}),
            shutil.which("ffmpeg") is not None,
            "sudo apt install ffmpeg",
            soft=True,
        )
    )
    checks.append(
        Check(
            "agg",
            frozenset({"render"}),
            shutil.which("agg") is not None,
            "https://github.com/asciinema/agg",
            soft=True,
        )
    )

    hermes_path: Path | None = None
    try:
        from hermesbench.hermes_invocation import find_hermes_agent

        hermes_path = find_hermes_agent()
        checks.append(
            Check(
                "hermes-agent",
                frozenset({"run-real"}),
                True,
                f"at {hermes_path}",
            )
        )
    except FileNotFoundError:
        checks.append(
            Check(
                "hermes-agent",
                frozenset({"run-real"}),
                False,
                "see docs/GETTING_STARTED.md — clone to ~/.hermes/hermes-agent",
            )
        )

    if hermes_path is not None:
        venv_ok = (hermes_path / ".venv" / "bin" / "python").is_file()
        checks.append(
            Check(
                "hermes-agent .venv",
                frozenset({"run-real"}),
                venv_ok,
                f"cd {hermes_path} && python3 -m venv .venv && .venv/bin/pip install -e .",
            )
        )
        if venv_ok:
            checks.append(
                Check(
                    "hermes-agent fire",
                    frozenset({"run-real"}),
                    _hermes_fire_ok(hermes_path),
                    f"cd {hermes_path} && .venv/bin/pip install -e .",
                )
            )

    checks.append(
        Check(
            "provider config",
            frozenset({"run-real"}),
            _provider_configured(),
            "~/.hermes/config.yaml or OPENAI_API_KEY / OPENAI_BASE_URL — see docs/PROVIDERS.md",
            soft=True,
        )
    )

    archives = Path.home() / ".hermes" / "archives"
    try:
        archives.mkdir(parents=True, exist_ok=True)
        test = archives / ".doctor_test"
        test.write_text("ok", encoding="utf-8")
        test.unlink()
        arch_ok, arch_msg = True, f"at {archives}"
    except Exception as e:
        arch_ok, arch_msg = False, str(e)
    checks.append(
        Check(
            "archives dir",
            frozenset({"run", "run-real"}),
            arch_ok,
            arch_msg,
            soft=True,
        )
    )

    node_ok = shutil.which("node") is not None
    checks.append(
        Check(
            "node (video)",
            frozenset({"video"}),
            node_ok,
            "install Node 18+ for HyperFrames render",
            soft=True,
        )
    )

    return checks


def checks_for_profile(checks: list[Check], profile: str) -> list[Check]:
    return [c for c in checks if profile in c.required_for or profile == "all"]


def install_python_packages(packages: list[str], *, python: str | None = None) -> None:
    exe = python or sys.executable
    unique = []
    seen: set[str] = set()
    for p in packages:
        if p and p not in seen:
            seen.add(p)
            unique.append(p)
    if not unique:
        return
    subprocess.run(
        [exe, "-m", "pip", "install", *unique],
        check=True,
    )


def run_doctor(
    *,
    install: bool = False,
    profile: str = "all",
    console_print: Callable[[str], None] | None = None,
) -> int:
    """Run checks; optionally pip-install missing packages. Returns 0 or 4."""
    from rich.console import Console
    from rich.table import Table

    console = Console(stderr=True)
    log = console_print or (lambda s: console.print(s))

    checks = collect_checks()
    visible = checks if profile == "all" else checks_for_profile(checks, profile)

    if install:
        to_install = [c.pip_package for c in visible if not c.ok and c.pip_package]
        if to_install:
            log(f"[bold]Installing:[/bold] {', '.join(to_install)}")
            try:
                install_python_packages(to_install)
            except subprocess.CalledProcessError as e:
                log(f"[red]pip install failed: {e}[/red]")
                return 4
            checks = collect_checks()
            visible = checks if profile == "all" else checks_for_profile(checks, profile)

    table = Table("Check", "Status", "Remediation")
    all_ok = True
    for c in visible:
        status = (
            "[green]✓[/green]" if c.ok else ("[yellow]~[/yellow]" if c.soft else "[red]✗[/red]")
        )
        if not c.ok and not c.soft:
            all_ok = False
        table.add_row(c.name, status, c.remediation)
    console.print(table)
    if not all_ok:
        console.print("[dim]Tip: hermesbench doctor --install  or  ./scripts/bootstrap.sh[/dim]")
        return 4
    return 0
