"""hermesbench CLI: list, validate, run, score, render, doctor, archive, etc."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from hermesbench import __version__
from hermesbench.types import TaskSpec

REPO = Path(__file__).resolve().parent.parent
console = Console(stderr=True)


def _discover_tasks(repo_root: Path | None = None) -> list[Path]:
    """Return all task directories (each containing task.yaml)."""
    root = (repo_root or REPO).resolve()
    out: list[Path] = []
    tasks_root = root / "tasks"
    for p in sorted(tasks_root.rglob("task.yaml")):
        if "_template" in p.parts:
            continue
        out.append(p.parent)
    return out


def _load_task(task_dir: Path) -> TaskSpec:
    return TaskSpec.from_yaml(task_dir / "task.yaml")


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """hermesbench: a benchmark for local models in the Hermes Agent harness."""


@main.command("list")
@click.option("--category", "-c", help="Filter by category (e.g. t03_patch_edit)")
@click.option("--difficulty", "-d", type=int, help="Filter by difficulty (1, 2, or 3)")
def list_tasks_cmd(category: str | None, difficulty: int | None) -> None:
    """List all available tasks."""
    table = Table("ID", "Name", "Difficulty", "Tags")
    for td in _discover_tasks():
        try:
            spec = _load_task(td)
        except Exception as e:
            console.print(f"[red]error loading {td}: {e}[/red]")
            continue
        if category and not spec.id.startswith(category):
            continue
        if difficulty and spec.difficulty != difficulty:
            continue
        table.add_row(spec.id, spec.name, str(spec.difficulty), ", ".join(spec.tags))
    console.print(table)


@main.command()
@click.option(
    "--path",
    "paths",
    multiple=True,
    type=str,
    help="Path to validate (can be repeated)",
)
@click.option("--lint-only", is_flag=True, help="Lint fixtures/tasks without running")
def validate(paths: tuple[str, ...], lint_only: bool) -> None:
    """Validate task.yaml files and (if not --lint-only) try to import verifiers.

    Exit 0 on success, 4 (USER_ERROR) on bad input.
    """
    targets = [Path(p) for p in paths] if paths else [REPO / "fixtures", REPO / "tasks"]
    errors: list[tuple[Path, str]] = []
    for target in targets:
        if target.is_file() and target.name == "task.yaml":
            try:
                spec = _load_task(target.parent)
                console.print(f"[green]OK[/green] {spec.id}")
            except Exception as e:
                errors.append((target, str(e)))
        elif target.is_dir():
            for td in sorted(target.rglob("task.yaml")):
                if "_template" in td.parts:
                    continue
                try:
                    spec = _load_task(td.parent)
                    console.print(f"[green]OK[/green] {spec.id}")
                except Exception as e:
                    errors.append((td, str(e)))
        else:
            errors.append((target, "not a file or directory"))
    if errors:
        for p, e in errors:
            console.print(f"[red]FAIL[/red] {p}: {e}")
        sys.exit(4)
    console.print(f"[green]All {len(targets)} target(s) valid[/green]")


def _resolve_run_task_ids(
    root: Path,
    *,
    tasks: tuple[str, ...],
    category: str | None,
    run_all: bool,
) -> list[str] | None:
    if run_all:
        return None
    ids: list[str] = [*tasks]
    if category:
        for td in _discover_tasks(root):
            spec = _load_task(td)
            if (spec.id.startswith(category + "/") or spec.id == category) and spec.id not in ids:
                ids.append(spec.id)
    if not ids:
        return []
    known = {_load_task(td).id for td in _discover_tasks(root)}
    for tid in ids:
        if tid not in known:
            console.print(f"[red]task not found: {tid}[/red]")
            raise SystemExit(4)
    return ids


def _invoke_benchmark_run(
    *,
    model: str,
    base_url: str,
    use_hermes_config: bool,
    toolsets: str,
    run_id: str | None,
    tasks: tuple[str, ...],
    category: str | None,
    run_all: bool,
    max_turns: int | None,
    timeout_overhead: int,
    hermes_agent_path: Path | None,
    repo_root: Path | None,
    dry_run: bool,
) -> None:
    from hermesbench.run_real import run_real_benchmark

    root = (repo_root or REPO).resolve()
    task_list = _resolve_run_task_ids(root, tasks=tasks, category=category, run_all=run_all)
    if task_list == []:
        if category and not tasks:
            console.print(f"[red]no tasks in category: {category}[/red]")
        else:
            console.print("[red]Specify --task (repeatable), --category, or --all[/red]")
        raise SystemExit(4)

    if dry_run:
        if task_list is None:
            n = len(_discover_tasks(root))
            console.print(f"[green]dry-run[/green]: would run all {n} tasks with model={model}")
        else:
            console.print(
                f"[green]dry-run[/green]: would run {len(task_list)} task(s): {', '.join(task_list)}"
            )
        raise SystemExit(0)

    code = run_real_benchmark(
        repo_root=root,
        model=model,
        base_url=base_url,
        use_hermes_config=use_hermes_config,
        toolsets=toolsets,
        run_id=run_id,
        task_ids=task_list,
        max_turns=max_turns,
        timeout_overhead=timeout_overhead,
        hermes_agent_path=hermes_agent_path,
    )
    raise SystemExit(code)


def _invoke_legacy_run(
    *,
    model: str | None,
    base_url: str | None,
    tasks: tuple[str, ...],
    category: str | None,
    run_all: bool,
    dry_run: bool,
    real_agent: bool,
    results_dir: str,
    n_runs: int,
    resume_dir: str | None,
    config_path: str | None,
    repo_root: Path | None,
) -> None:
    from hermesbench.config import load_config
    from hermesbench.runner import run_task

    cfg = load_config(config_path)
    model = model or cfg.get("model", {}).get("name")
    base_url = base_url or cfg.get("model", {}).get("base_url")
    if cfg.get("hermes", {}).get("real_agent", False):
        real_agent = True

    root = (repo_root or REPO).resolve()
    task_list = _resolve_run_task_ids(root, tasks=tasks, category=category, run_all=run_all)
    if task_list == []:
        if category and not tasks:
            console.print(f"[red]no tasks in category: {category}[/red]")
        else:
            console.print("[red]Specify --task (repeatable), --category, or --all[/red]")
        raise SystemExit(4)

    if not model:
        console.print("[red]--model required (or set model.name in hermesbench.yaml)[/red]")
        raise SystemExit(2)
    if not base_url and not dry_run:
        console.print("[red]--base-url required (or set model.base_url in hermesbench.yaml)[/red]")
        raise SystemExit(2)

    if task_list is None:
        targets = [_load_task(td) for td in _discover_tasks(root)]
    else:
        id_to_spec = {_load_task(td).id: _load_task(td) for td in _discover_tasks(root)}
        targets = [id_to_spec[tid] for tid in task_list]

    if dry_run:
        console.print(
            f"[green]dry-run[/green] (legacy): would run {len(targets)} task(s) with model={model}"
        )
        raise SystemExit(0)

    console.print(f"[cyan]legacy engine[/cyan]: running {len(targets)} task(s) against {model}")
    if real_agent:
        console.print("[cyan]using real hermes-agent[/cyan]")

    passed = 0
    total = 0
    for _ in range(n_runs):
        for spec in targets:
            total += 1
            console.print(f"  -> {spec.id}...", end=" ")
            result = run_task(
                spec,
                model=model,
                base_url=base_url or "",
                dry_run=False,
                use_real_agent=real_agent,
            )
            if result.verifier_result.status.value == "PASS":
                console.print("[green]PASS[/green]")
                passed += 1
            else:
                console.print(
                    f"[red]{result.verifier_result.status.value}[/red] "
                    f"{result.verifier_result.reason}"
                )
    rate = passed / total if total else 0
    console.print(f"\n[bold]pass rate: {passed}/{total} ({rate:.0%})[/bold]")
    if passed < total:
        raise SystemExit(1)


@main.command("run")
@click.option("--model", "-m", default="grok-composer-2.5-fast", help="Model name for run_agent.py")
@click.option(
    "--base-url",
    default="https://api.kilo.ai/api/gateway",
    help="OpenAI-compatible base URL (ignored with --use-hermes-config)",
)
@click.option(
    "--use-hermes-config", is_flag=True, help="Use ~/.hermes/config.yaml provider (xai-oauth, etc.)"
)
@click.option("--toolsets", default="all", help="enabled_toolsets for Hermes")
@click.option("--run-id", default=None, help="Results/traces directory name")
@click.option("--task", "tasks", multiple=True, help="Task ID (repeatable)")
@click.option("--category", "-c", default=None, help="Run all tasks in this category prefix")
@click.option("--all", "run_all", is_flag=True, help="Run all 48 tasks")
@click.option("--max-turns", type=int, default=None)
@click.option("--timeout-overhead", type=int, default=30)
@click.option("--hermes-agent-path", type=click.Path(path_type=Path), default=None)
@click.option("--repo-root", type=click.Path(path_type=Path), default=None)
@click.option("--dry-run", is_flag=True, help="List selected tasks without calling Hermes")
@click.option(
    "--engine",
    type=click.Choice(["real", "legacy"]),
    default="real",
    help="real=run_agent.py (default); legacy=local tmux runner + statsd",
)
@click.option("--real-agent", is_flag=True, help="(legacy engine) Use real hermes-agent CLI")
@click.option("--results-dir", "-r", default="./results", help="(legacy engine) Output directory")
@click.option("--n-runs", "-n", type=int, default=1, help="(legacy engine) Run each task N times")
@click.option("--resume", "resume_dir", default=None, help="(legacy engine) Resume from run dir")
@click.option(
    "--config", "config_path", default=None, help="(legacy engine) Path to hermesbench.yaml"
)
def run_benchmark_cmd(
    model: str,
    base_url: str,
    use_hermes_config: bool,
    toolsets: str,
    run_id: str | None,
    tasks: tuple[str, ...],
    category: str | None,
    run_all: bool,
    max_turns: int | None,
    timeout_overhead: int,
    hermes_agent_path: Path | None,
    repo_root: Path | None,
    dry_run: bool,
    engine: str,
    real_agent: bool,
    results_dir: str,
    n_runs: int,
    resume_dir: str | None,
    config_path: str | None,
) -> None:
    """Run benchmark tasks (default: real Hermes Agent via run_agent.py)."""
    if engine == "legacy":
        _invoke_legacy_run(
            model=model,
            base_url=base_url,
            tasks=tasks,
            category=category,
            run_all=run_all,
            dry_run=dry_run,
            real_agent=real_agent,
            results_dir=results_dir,
            n_runs=n_runs,
            resume_dir=resume_dir,
            config_path=config_path,
            repo_root=repo_root,
        )
        return
    _invoke_benchmark_run(
        model=model,
        base_url=base_url,
        use_hermes_config=use_hermes_config,
        toolsets=toolsets,
        run_id=run_id,
        tasks=tasks,
        category=category,
        run_all=run_all,
        max_turns=max_turns,
        timeout_overhead=timeout_overhead,
        hermes_agent_path=hermes_agent_path,
        repo_root=repo_root,
        dry_run=dry_run,
    )


@main.command("run-real", deprecated=True)
@click.option("--model", "-m", default="grok-composer-2.5-fast")
@click.option("--base-url", default="https://api.kilo.ai/api/gateway")
@click.option("--use-hermes-config", is_flag=True)
@click.option("--toolsets", default="all")
@click.option("--run-id", default=None)
@click.option("--task", "tasks", multiple=True)
@click.option("--category", "-c", default=None)
@click.option("--all", "run_all", is_flag=True)
@click.option("--max-turns", type=int, default=None)
@click.option("--timeout-overhead", type=int, default=30)
@click.option("--hermes-agent-path", type=click.Path(path_type=Path), default=None)
@click.option("--repo-root", type=click.Path(path_type=Path), default=None)
@click.option("--dry-run", is_flag=True)
def run_real_cmd(
    model: str,
    base_url: str,
    use_hermes_config: bool,
    toolsets: str,
    run_id: str | None,
    tasks: tuple[str, ...],
    category: str | None,
    run_all: bool,
    max_turns: int | None,
    timeout_overhead: int,
    hermes_agent_path: Path | None,
    repo_root: Path | None,
    dry_run: bool,
) -> None:
    """Deprecated alias for `hermesbench run`."""
    console.print("[yellow]run-real is deprecated; use: hermesbench run[/yellow]")
    _invoke_benchmark_run(
        model=model,
        base_url=base_url,
        use_hermes_config=use_hermes_config,
        toolsets=toolsets,
        run_id=run_id,
        tasks=tasks,
        category=category,
        run_all=run_all,
        max_turns=max_turns,
        timeout_overhead=timeout_overhead,
        hermes_agent_path=hermes_agent_path,
        repo_root=repo_root,
        dry_run=dry_run,
    )


@main.command()
@click.option("--install", is_flag=True, help="pip install missing Python packages")
@click.option(
    "--profile",
    default="all",
    type=click.Choice(["all", "validate", "run", "run-real", "render", "video"]),
)
def doctor(install: bool, profile: str) -> None:
    """Pre-flight checks; use --install to fix pip dependencies."""
    from hermesbench.preflight import run_doctor

    raise SystemExit(run_doctor(install=install, profile=profile))


@main.command()
@click.option("--dev", is_flag=True, help="Install .[dev] for contributors")
@click.option("--hermes", is_flag=True, help="Verify Hermes Agent checkout and venv")
@click.option("--check-only", is_flag=True, help="Run doctor after setup (no venv creation)")
def setup(dev: bool, hermes: bool, check_only: bool) -> None:
    """Create .venv and pip install -e . (recommended after git clone)."""
    from hermesbench.preflight import run_doctor
    from hermesbench.setup_env import check_hermes_agent, ensure_repo_venv

    if not check_only:
        py = ensure_repo_venv(dev=dev)
        console.print(f"[green]Installed[/green] editable package in {py.parent.parent}")
        console.print(f"Activate: [bold]source {py.parent.parent}/bin/activate[/bold]")
    if hermes:
        ok, msg = check_hermes_agent()
        if ok:
            console.print(f"[green]Hermes Agent OK[/green] at {msg}")
        else:
            console.print(f"[yellow]{msg}[/yellow]")
    code = run_doctor(install=False, profile="run-real")
    if code != 0:
        console.print("[dim]Run: hermesbench doctor --install[/dim]")
    raise SystemExit(0 if check_only else code)


@main.command()
@click.option("--run-id", required=True, help="Run directory under results/")
@click.option("--repo-root", type=click.Path(path_type=Path), default=None)
@click.option("--render-video", is_flag=True, help="Also run npx hyperframes render (needs Node)")
def report(run_id: str, repo_root: Path | None, render_video: bool) -> None:
    """Generate REPORT.md, event timeline, and HyperFrames index from summary.json."""
    from hermesbench.reporting import generate_run_artifacts

    root = (repo_root or REPO).resolve()
    paths = generate_run_artifacts(root, run_id, render_video=render_video)
    for name, p in paths.items():
        console.print(f"[green]{name}[/green]: {p}")


@main.command()
@click.option(
    "--path",
    "paths",
    multiple=True,
    type=str,
    required=True,
    help="Path to score (can be repeated)",
)
def score(paths: tuple[str, ...]) -> None:
    """Re-score existing results."""
    from hermesbench.scoring import score_run

    targets: list[Path] = [Path(p) for p in paths]
    for p in targets:
        if not p.exists():
            console.print(f"[red]path does not exist: {p}[/red]")
            continue
        if not p.is_dir():
            console.print(f"[red]not a directory: {p}[/red]")
            continue
        # Detect whether `p` is a single run-dir or a single task-dir.
        # A run-dir has subdirs each containing verifier_result.json.
        # A task-dir contains verifier_result.json itself.
        is_task_dir = (p / "verifier_result.json").exists()
        if is_task_dir:
            from hermesbench.scoring import score_run

            parent = p.parent
            summary = score_run(parent, parent)
            console.print(
                f"[bold]{p.name}[/bold] pass_rate={summary['pass_rate']:.0%} "
                f"({len(summary['tasks'])} tasks, "
                f"{len(summary['thermal_warnings'])} thermal warnings)"
            )
            for w in summary["thermal_warnings"]:
                console.print(f"  [yellow]⚠[/yellow] {w['task']}: {w['warning']}")
            continue
        # Otherwise treat as a run-dir
        from hermesbench.scoring import score_run

        summary = score_run(p, p)
        console.print(
            f"[bold]{p.name}[/bold] pass_rate={summary['pass_rate']:.0%} "
            f"({len(summary['tasks'])} tasks, "
            f"{len(summary['thermal_warnings'])} thermal warnings)"
        )
        for w in summary["thermal_warnings"]:
            console.print(f"  [yellow]⚠[/yellow] {w['task']}: {w['warning']}")


@main.command()
@click.option("--path", "-p", required=True, help="Run directory")
def stats(path: str) -> None:
    """Show hardware stats summary for a run."""
    from hermesbench.scoring import compute_hardware_summary

    summary = compute_hardware_summary(path)
    console.print(f"Run: {path}")
    for key, val in summary.items():
        if isinstance(val, float):
            console.print(f"  {key}: {val:.2f}")
        else:
            console.print(f"  {key}: {val}")


@main.command()
@click.option("--model", "-m", required=True, help="Model path or HF ID")
@click.option("--port", "-p", default=8999, help="Port for vLLM server")
@click.option("--quantization", default=None, help="Quantization method")
@click.option("--served-name", default=None, help="Served model name")
@click.option("--config", "-c", default=None, help="Path to hermesbench.yaml")
def serve(
    model: str,
    port: int,
    quantization: str | None,
    served_name: str | None,
    config: str | None,
) -> None:
    """Launch a vLLM server with benchmark-correct flags."""
    from hermesbench.serve import launch_vllm

    launch_vllm(model, port, quantization, config, served_name)


@main.command()
@click.argument("cast_path", type=click.Path(exists=True))
@click.option("--format", "-f", "fmt", type=click.Choice(["gif", "mp4"]), default="gif")
@click.option("--out", "-o", help="Output file path")
def render(cast_path: str, fmt: str, out: str | None) -> None:
    """Render an asciinema .cast file to .gif or .mp4."""
    from hermesbench.render import render_cast

    try:
        result = render_cast(cast_path, fmt, out)
        console.print(f"Rendered: {result}")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@main.command(name="export-sft")
@click.option("--path", "-p", "run_paths", multiple=True, required=True, help="Run directory")
@click.option("--out", "-o", required=True, help="Output .jsonl file")
def export_sft(run_paths: tuple[str, ...], out: str) -> None:
    """Export conversation traces to SFT-ready JSONL with loss masks."""
    from hermesbench.sft_export import export_sft as do_export

    count = do_export(list(run_paths), out)
    console.print(f"Exported {count} examples to {out}")


@main.command()
@click.option(
    "--path",
    "-p",
    "run_paths",
    multiple=True,
    required=True,
    help="Run directories to compare (at least 2)",
)
@click.option("--html", "-o", help="Output HTML comparison report")
def compare(run_paths: tuple[str, ...], html: str | None) -> None:
    """Compare results across multiple model runs."""
    from hermesbench.compare import compare_runs
    from hermesbench.scoring import aggregate_results

    results = {}
    for p in run_paths:
        results[p] = aggregate_results([p])

    if len(results) < 2:
        console.print("[yellow]Warning: need at least 2 runs for comparison[/yellow]")

    table = compare_runs(results)
    console.print(table)

    if html:
        from hermesbench.report import generate_comparison_html

        generate_comparison_html(results, html)
        console.print(f"HTML report: {html}")


@main.command()
@click.option("--model", "-m", required=True, help="Model name")
@click.option("--base-url", required=True, help="Model base URL")
@click.option("--output", "-o", default="videos/hyperframes.mp4", help="Output video path")
@click.option("--duration", "-d", type=int, default=1800, help="Recording duration (seconds)")
@click.option("--real-agent/--fake-agent", default=True, help="Use real hermes-agent")
@click.option(
    "--attach/--headless",
    default=False,
    help="--attach: manual recording. --headless: auto-record via Xvfb+ffmpeg",
)
def record(
    model: str,
    base_url: str,
    output: str,
    duration: int,
    real_agent: bool,
    attach: bool,
) -> None:
    """Record a hyperframes video of the benchmark with live telemetry."""
    from hermesbench.record import HyperframesRecorder

    rec = HyperframesRecorder(
        model=model,
        base_url=base_url,
        output=output,
        duration=duration,
        real_agent=real_agent,
        attach_mode=attach,
    )
    rec.run()


@main.command(name="post-process")
@click.argument("video_path", type=click.Path(exists=True))
@click.option("--trim-start", "-s", type=int, default=0, help="Trim first N seconds")
@click.option("--trim-end", "-e", type=int, default=0, help="Trim last N seconds")
@click.option("--thumbnail", "-t", is_flag=True, help="Extract thumbnail at 25% mark")
@click.option("--out", "-o", help="Output path")
def post_process(
    video_path: str,
    trim_start: int,
    trim_end: int,
    thumbnail: bool,
    out: str | None,
) -> None:
    """Trim video and/or extract thumbnail frame."""
    import subprocess

    vp = Path(video_path)
    base_out = out or str(vp.with_stem(vp.stem + "_final"))

    if trim_start or trim_end:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(vp)],
            capture_output=True,
            text=True,
        )
        duration = float(json.loads(result.stdout)["format"]["duration"])
        start = trim_start
        end = duration - trim_end
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(start),
                "-to",
                str(end),
                "-i",
                str(vp),
                "-c",
                "copy",
                base_out + ".mp4",
            ],
            check=True,
        )
        console.print(f"Trimmed: {base_out}.mp4 ({end - start:.0f}s)")

    if thumbnail:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(vp)],
            capture_output=True,
            text=True,
        )
        duration = float(json.loads(result.stdout)["format"]["duration"])
        thumb_time = duration * 0.25
        thumb_path = (out or str(vp.with_stem(vp.stem + "_thumb"))) + ".png"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(thumb_time),
                "-i",
                str(vp),
                "-vframes",
                "1",
                "-q:v",
                "2",
                thumb_path,
            ],
            check=True,
        )
        console.print(f"Thumbnail: {thumb_path}")


if __name__ == "__main__":
    main()
