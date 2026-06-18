# HermesBench merge status — Phase 0 inventory

**Date:** 2026-06-18  
**Source (proven v0.1.2):** `/home/am/projects/hermesbenchv0_1`  
**Target (canonical public repo):** `/home/am/projects/hermes-bench-tool-call` (`am423/hermes-bench-tool-call`)  
**Merge branch:** `merge/v0.3-run-real-hyperframes`  
**Phase:** 0 — inventory only (no file copies yet)

## Disposition legend

| Code | Meaning |
|------|---------|
| **ADD** | Present only in v0.1.2 — copy into GitHub repo during merge |
| **MODIFY** | Present in both repos but content differs — merge / reconcile |
| **KEEP** | Present only in GitHub, or byte-identical in both — retain GitHub version unless noted |

## Executive summary

v0.1.2 is a **real-Hermes benchmark fork** (`hermesbench run` → `run_real.py` + `run_agent.py`, `preflight`, `setup`, HyperFrames video pipeline). GitHub **v0.2.0** is a **broader harness** (YAML config, fake/real toggle via `runner.py`, SFT export, compare, metrics panel, `t12_real_world` tasks). `backend/` and `statsd/` Python sources are aligned; the largest gaps are the **missing real-run engine**, **CLI surface**, and **reporting/video** stack on GitHub.

---

## Required module matrix

| Path | Disposition | Notes |
|------|-------------|-------|
| `hermesbench/run_real.py` | **ADD** | ~440 lines; core benchmark engine (not in GitHub) |
| `hermesbench/preflight.py` | **ADD** | `doctor --install`, profile-based pip fixes |
| `hermesbench/setup_env.py` | **ADD** | `hermesbench setup`, venv + Hermes checkout checks |
| `hermesbench/event_timeline.py` | **ADD** | Event timeline for reports / HyperFrames |
| `hermesbench/hf_video.py` | **ADD** | HyperFrames video index + render helpers (~332 lines) |
| `hermesbench/reporting.py` | **ADD** | REPORT.md, timeline, HF index (`hermesbench report`) |
| `hermesbench/cli.py` | **MODIFY** | v0.1.2: `run`→`run_real`, `setup`, rich `doctor`, `report --render-video`; GitHub: `run`→`runner`, `config.py`, minimal `doctor` |
| `hermesbench/hermes_invocation.py` | **MODIFY** | v0.1.2: `find_hermes_agent`, `hermes_python` for real runs |
| `hermesbench/runner.py` | **MODIFY** | GitHub: tmux/fake/real toggle; v0.1.2: legacy path, diverged |
| `hermesbench/report.py` | **KEEP** | GitHub-only; trace/report utilities — reconcile with `reporting.py` in Phase 1+ |
| `hermesbench/render.py` | **KEEP** | GitHub-only cast/video render path |
| `hermesbench/sft_export.py` | **KEEP** | GitHub-only training export |
| `hermesbench/compare.py` | **KEEP** | GitHub-only run comparison |
| `hermesbench/metrics_panel.py` | **KEEP** | GitHub-only metrics UI |
| `hermesbench/scoring.py` | **MODIFY** | Both differ (GitHub has v2 tests) |
| `hermesbench/__init__.py` | **MODIFY** | v0.1.2 `0.1.2` vs GitHub `0.2.0` |
| `hermesbench/config.py` | **KEEP** | GitHub-only YAML config loader |
| `hermesbench/record.py` | **KEEP** | GitHub-only live record |
| `hermesbench/serve.py` | **KEEP** | GitHub-only serve helper |
| `hermesbench/trace.py` | **KEEP** | Identical |
| `hermesbench/types.py` | **KEEP** | Identical |
| `hermesbench/__main__.py` | **KEEP** | Identical |

---

## `hermesbench/backend/` (all `.py`)

| File | Disposition |
|------|-------------|
| `backend/__init__.py` | **KEEP** (identical) |
| `backend/base.py` | **KEEP** (identical) |
| `backend/registry.py` | **KEEP** (identical) |
| `backend/worktree.py` | **KEEP** (identical) |
| `backend/tmux_isolated.py` | **KEEP** (identical) |
| `backend/recorder.py` | **KEEP** (identical) |

---

## `hermesbench/statsd/` (all `.py`)

| File | Disposition |
|------|-------------|
| `statsd/__init__.py` | **KEEP** (identical) |
| `statsd/__main__.py` | **KEEP** (identical) |
| `statsd/collector.py` | **KEEP** (identical) |
| `statsd/pinning.py` | **KEEP** (identical) |
| `statsd/sources/__init__.py` | **KEEP** (identical) |
| `statsd/sources/cpu.py` | **KEEP** (identical) |
| `statsd/sources/gpu_nvidia.py` | **KEEP** (identical) |
| `statsd/sources/memory.py` | **KEEP** (identical) |
| `statsd/sources/nvme.py` | **KEEP** (identical) |
| `statsd/sources/process.py` | **KEEP** (identical) |
| `statsd/presets/` | **ADD** | Only in v0.1.2 (if still needed for video/metrics) |

---

## Other `hermesbench/` paths

| Path | Disposition | Notes |
|------|-------------|-------|
| `hermesbench/tasks/_template/` | **ADD** | v0.1.2 internal task template package (GitHub uses repo `tasks/_template` only) |

---

## `tasks/` directory

`diff -rq` (excluding `__pycache__`):

- **KEEP (identical):** All shared categories `t01`–`t11` task trees match between repos.
- **KEEP (GitHub-only):** `tasks/t12_real_world/` — extra category on GitHub; retain.
- No substantive task YAML/verifier diffs reported outside `t12` and cache dirs.

---

## Top-level scripts & docs

| Path | Disposition | Notes |
|------|-------------|-------|
| `scripts/bootstrap.sh` | **ADD** | v0.1.2 clone-and-run setup |
| `scripts/build_event_timeline.py` | **ADD** | v0.1.2 video/report pipeline |
| `scripts/build_hf_grok_index.py` | **ADD** | v0.1.2 HF index builder |
| `scripts/run_real_model_benchmark.py` | **ADD** | v0.1.2 ad-hoc real benchmark |
| `scripts/fake_hermes.py` | **MODIFY** | Both differ |
| `scripts/export_training_data.py` | **KEEP** | GitHub-only |
| `scripts/mine_sessions.py` | **KEEP** | GitHub-only |
| `scripts/record_live_benchmark.sh` | **KEEP** | GitHub-only |
| `docs/GETTING_STARTED.md` | **ADD** | v0.1.2 onboarding |
| `docs/PROVIDERS.md` | **ADD** | v0.1.2 provider guide |
| `docs/reviews/` | **ADD** | v0.1.2 only |
| `docs/glossary.md` | **KEEP** | GitHub-only |
| `docs/adding_backends.md` | **KEEP** | GitHub-only |
| `docs/trace_format_reconciliation.md` | **KEEP** | GitHub-only |
| `AGENTS.md` | **ADD** | v0.1.2 agent guide (missing on GitHub) |
| `README.md` | **MODIFY** | Different positioning (real-run vs config harness) |
| `Makefile` | **MODIFY** | Different targets |
| `pyproject.toml` | **MODIFY** | Version, deps, entry points may differ |

---

## Tests (reference for Phase 1+)

| Path | Disposition |
|------|-------------|
| `tests/test_cli.py` | **MODIFY** |
| `tests/test_smoke.py` | **MODIFY** |
| `tests/test_preflight.py` | **ADD** |
| `tests/test_event_timeline.py` | **ADD** |
| `tests/support/` | **ADD** | fake_hermes support |
| `tests/test_config.py` | **KEEP** | GitHub-only |
| `tests/test_scoring_v2.py` | **KEEP** | GitHub-only |
| `tests/test_sft_export.py` | **KEEP** | GitHub-only |

---

## Raw diff captures

Full `diff -rq` output saved locally:

- `/tmp/hermesbench-merge/diff_hermesbench.txt`
- `/tmp/hermesbench-merge/diff_tasks.txt`

### `hermesbench/` diff summary (excluding `__pycache__`)

```
Files cli.py differ
Only in GitHub: compare.py, config.py, metrics_panel.py, record.py, render.py, report.py, serve.py, sft_export.py
Only in v0.1.2: event_timeline.py, hf_video.py, preflight.py, reporting.py, run_real.py, setup_env.py, hermesbench/tasks/
Files hermes_invocation.py, runner.py, scoring.py, __init__.py differ
backend/*.py: no differences
statsd/*.py: no differences (v0.1.2 adds statsd/presets/)
```

### `tasks/` diff summary (excluding `__pycache__`)

```
Only in GitHub: tasks/t12_real_world
(Otherwise identical task trees for t01–t11)
```

---

## Phase 0 checklist

- [x] Clone `am423/hermes-bench-tool-call` → `/home/am/projects/hermes-bench-tool-call`
- [x] Recursive diff `hermesbench/` and `tasks/`
- [x] File-level disposition matrix (this document)
- [x] Create branch `merge/v0.3-run-real-hyperframes` from `main`
- [ ] Phase 1: copy **ADD** modules and merge **MODIFY** (especially `cli.py` + `run` entrance)

---

## Biggest gaps (top 5)

1. **`run_real.py` missing on GitHub** — no first-class `run_agent.py` benchmark loop; `hermesbench run` still targets `runner.py` + optional `--real-agent`.
2. **`cli.py` diverged** — v0.1.2 unifies on real Hermes (`--use-hermes-config`, `--toolsets`, `setup`, `report --render-video`); GitHub requires `base-url` / YAML config path.
3. **Reporting / HyperFrames stack absent** — `reporting.py`, `event_timeline.py`, `hf_video.py` and related scripts not in public repo.
4. **Operational bootstrap missing** — `preflight.py`, `setup_env.py`, `AGENTS.md`, `GETTING_STARTED.md`, `bootstrap.sh` not on GitHub.
5. **`report.py` vs `reporting.py`** — two parallel report implementations; merge must wire CLI to v0.1.2 pipeline without dropping GitHub `render.py` / metrics features.