# HermesBench — AGENTS.md

This file is for **coding agents** (Hermes, Cursor, Claude Code, etc.) working in this repository. Follow it for install, benchmark runs, and safe edits.

## What this repo is

**HermesBench v0.3.0** (canonical repo: **https://github.com/am423/hermes-bench-tool-call**) benchmarks **models inside real [Hermes Agent](https://github.com/NousResearch/hermes-agent)** — tool use (terminal, patch, search, execute_code, web, memory, …), not chat-only QA.

- **51 tasks** under `tasks/**/task.yaml` (48 core categories + 3 `t12_real_world`, difficulties 1–3)
- Each task: isolated git worktree, prompt, verifier under `tasks/.../verifier.py`
- **Official benchmark command:** `hermesbench run` → spawns `run_agent.py` from the Hermes Agent checkout

There is **no** fake-agent benchmark path in the CLI anymore. `tests/support/fake_hermes.py` exists only for optional pipeline tests.

## Repository layout (agent-relevant)

```
hermesbench/
  cli.py              # CLI entry (run, validate, doctor, setup, report, …)
  run_real.py         # Benchmark engine (run_agent.py per task)
  preflight.py        # doctor checks + pip --install
  hermes_invocation.py # find_hermes_agent(), hermes_python()
  runner.py           # Legacy tmux/fake pipeline — not used by `hermesbench run`
tasks/                # Task definitions + verifiers
results/<run_id>/     # summary.json + per-task JSON
traces/<run_id>/      # logs, trace.jsonl, worktrees
scripts/bootstrap.sh  # Clone-and-run venv setup
docs/GETTING_STARTED.md
docs/PROVIDERS.md
docs/RUN_LAYOUT.md
presets/               # Rerun presets (see presets/README.md)
```

## Prerequisites (check before benchmarking)

| Requirement | Why |
|-------------|-----|
| Python **3.11+** | Package + tests |
| **Hermes Agent** checkout | `run_agent.py`, toolsets, providers |
| Hermes **`.venv`** with `pip install -e .` | `fire`, `python-dotenv`, agent deps |
| **`~/.hermes/config.yaml`** (or `OPENAI_*`) | Model provider / API |
| **tmux**, **bash** | Hermes terminal backend in benchmarks |
| **git** | Worktrees per task |

Optional: **ffmpeg**, **agg** (casts), **Node 18+** (HyperFrames video via `hermesbench report --render-video`).

## Install (clone → runnable)

Run from repo root:

```bash
./scripts/bootstrap.sh
source .venv/bin/activate
hermesbench doctor --install
hermesbench setup --hermes --check-only
hermesbench validate
```

If Hermes Agent is missing:

```bash
git clone https://github.com/NousResearch/hermes-agent ~/.hermes/hermes-agent
cd ~/.hermes/hermes-agent && python3 -m venv .venv && .venv/bin/pip install -e .
```

Set provider in `~/.hermes/config.yaml`. For xAI OAuth / config-driven models, always use **`--use-hermes-config`** on runs (see below).

Override checkout path: `export HERMES_AGENT_PATH=/path/to/hermes-agent`

## Benchmark commands (only entrance: `hermesbench run`)

### Smoke (one task)

```bash
hermesbench run --use-hermes-config \
  --model YOUR_MODEL_ID \
  --task t01_terminal_smoke/t01_echo \
  --toolsets all
```

### Full suite (51 tasks)

```bash
hermesbench run --use-hermes-config \
  --model YOUR_MODEL_ID \
  --all \
  --toolsets all \
  --run-id my_run_$(date +%Y%m%d)
```

### Resume a partial real run

Skips tasks already **PASS** or **FAIL** in `results/<run_id>/summary.json`; merges new results into the same summary.

```bash
hermesbench run --resume my_run_20260618 --all --use-hermes-config --model YOUR_MODEL_ID

hermesbench run --run-id my_run_20260618 --resume-skipped --category t03_patch_edit \
  --use-hermes-config --model YOUR_MODEL_ID
```

See `docs/RUN_LAYOUT.md` for layout and legacy vs real resume behavior.

### Legacy engine

```bash
hermesbench run --engine legacy --task t01_terminal_smoke/t01_echo \
  --model local-model --base-url http://127.0.0.1:8080/v1
```

### Category

```bash
hermesbench run --use-hermes-config --model YOUR_MODEL_ID \
  --category t03_patch_edit --toolsets all
```

### OpenAI-compatible env (no Hermes config file)

Omit `--use-hermes-config` and set:

```bash
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=http://127.0.0.1:8080/v1   # optional override
hermesbench run --model local-model --all --base-url "$OPENAI_BASE_URL"
```

For local no-auth servers, `OPENAI_API_KEY` may be unset; HermesBench injects a `dummy` key into `run_agent.py` so the run stays on the supplied `--base-url`. If logs show a cloud/OAuth endpoint instead of the local URL, mark that run invalid and rerun with the current endpoint-routing fix.

### Dry-run (task selection only)

```bash
hermesbench run --dry-run --all --model x
```

Prints selected tasks; does not call the API or Hermes.

### After a run

```bash
hermesbench report --run-id <run_id>
# optional video:
hermesbench report --run-id <run_id> --render-video
```

Artifacts:

- `results/<run_id>/summary.json` — pass/fail, pass_rate, per-task reasons
- `results/<run_id>/REPORT.md` — human summary (via `report`)
- `traces/<run_id>/<task_id>/` — `run_agent.log`, `trace.jsonl`, `verifier_result.json`

## CLI reference (agents)

| Command | Purpose |
|---------|---------|
| `hermesbench setup` | `.venv` + editable install |
| `hermesbench doctor [--install] [--profile run]` | Environment + pip fixes |
| `hermesbench validate` | Lint all `task.yaml` + verifiers |
| `hermesbench list` | List tasks |
| **`hermesbench run`** | **Real benchmark** (Hermes `run_agent.py`, default `--engine real`) |
| `hermesbench run --engine legacy` | Legacy tmux runner + statsd |
| `hermesbench run-real` | Deprecated alias for `run` |
| `hermesbench report --run-id ID` | REPORT + timeline + HF index |
| `hermesbench score --path …` | Re-score `results/<run_id>/` or `traces/<run_id>/<task>/` |

## Critical flags for `run`

- **`--use-hermes-config`** — Use `~/.hermes/config.yaml` provider (xai-oauth, etc.). **Required** for OAuth models; avoids wrong `OPENAI_BASE_URL` overrides.
- **`--engine real|legacy`** — Default `real` uses `run_real.py`; `legacy` uses `runner.py`.
- **`--resume <run_id>`** — (real) Continue that run id; skip completed PASS/FAIL tasks.
- **`--resume-skipped`** — (real) With `--run-id`, same skip behavior without changing run id source.
- **`--toolsets all`** — Full tool surface (matches published 51-task runs). Narrow only for debugging.
- **`--enabled_toolsets`** is passed internally as a single Fire arg: `--enabled_toolsets=all`.
- **`--hermes-agent-path`** — Override Hermes checkout.
- **`--timeout-overhead`** — Seconds added to each task’s `timeout_seconds` (default 30).

Hermes is executed with **`hermes_python(hermes_path)`** — prefer `hermes-agent/.venv/bin/python`, not system `python3`.

## Adding or changing tasks

1. Copy `tasks/_template/` pattern: `task.yaml`, `verifier.py`, optional `fixture/`.
2. `task.yaml` must define: `id`, `prompt`, `timeout_seconds`, `max_turns`, `difficulty`, `verifier`, `hermes_plugins` (if any).
3. Verifier returns `VerifierResult` with `PASS` / `FAIL` / etc. — see `hermesbench/types.py`.
4. Run `hermesbench validate` before committing.
5. Lint tests: `pytest tests/test_lint_verifiers.py tests/test_lint_fixtures.py -v`

Do **not** weaken verifiers to make a model pass; fix the model or document task difficulty.

## Testing (agents modifying code)

```bash
pip install -e ".[dev]"
pytest tests/ -m "not integration" -v
ruff check hermesbench tests
```

Exit codes: **4** = user error (bad task id, missing args). Benchmark partial fail → exit **1** if any task failed.

## Common failures (troubleshooting)

| Symptom | Fix |
|---------|-----|
| `No module named 'fire'` / `dotenv` | Use Hermes `.venv`: `hermesbench doctor --profile run` |
| OAuth / wrong provider | Add `--use-hermes-config` |
| Local `--base-url` run routes to cloud/OAuth and returns 401/403 | Do **not** use `--use-hermes-config`; update HermesBench so `--api_key dummy` is passed with `--base_url` |
| `Could not find hermes-agent` | Clone + `HERMES_AGENT_PATH` |
| All tasks FAIL, empty trajectory | Model name wrong or API errors — check `traces/.../run_agent.log` |
| `Specify --task or --all` | CLI requires explicit scope |

## What agents should NOT do

- Do not reintroduce `fake_hermes` as the default benchmark path.
- Do not commit API keys, `config.yaml` secrets, or user `~/.hermes` contents.
- Do not compare to other models in user deliverables unless asked (standalone runs).
- Do not run full `--all` in CI without credentials (use `validate` + unit tests).

## Maintainer notes

- Never name CLI callbacks `run` or `list` — they shadow Click/builtins (`Group.run`, `list()`). Use `@main.command("list")` + `list_tasks_cmd`, etc.

## Version

Package version: `hermesbench/__init__.py` → `__version__`. Bump on CLI-breaking changes.

## Links

- Human onboarding: `docs/GETTING_STARTED.md`
- Run layout & resume: `docs/RUN_LAYOUT.md`
- Providers: `docs/PROVIDERS.md`
- Hermes Agent docs: https://hermes-agent.nousresearch.com/docs