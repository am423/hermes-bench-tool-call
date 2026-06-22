# Getting started with HermesBench

HermesBench measures how well a model **uses Hermes Agent tools** (terminal, patch, search, execute_code, etc.), not chat-only QA.

**Coding agents:** read [AGENTS.md](../AGENTS.md) in the repo root first.

## Requirements

- **Python 3.11+**
- **Linux** recommended (tmux backend for packaged `hermesbench run`)
- **Real-model benchmarks** (`hermesbench run`): [Hermes Agent](https://github.com/NousResearch/hermes-agent) checkout with its own `.venv`
- **Provider**: `~/.hermes/config.yaml` (xai-oauth, OpenRouter, etc.) or `OPENAI_*` env vars — see [PROVIDERS.md](./PROVIDERS.md)

Optional:

- `tmux`, `ffmpeg`, `agg` — for full tmux traces and cast rendering
- **Node 18+** — only for HyperFrames results video (`hermesbench report --render-video`)

## Clone and install (recommended)

```bash
git clone https://github.com/am423/hermesbenchv0_1.git
cd hermesbenchv0_1
./scripts/bootstrap.sh
source .venv/bin/activate
hermesbench doctor --install
hermesbench setup --hermes --check-only
```

`bootstrap.sh` creates `.venv`, installs `hermesbench` editable, and runs `doctor --install` for Python deps.

## Hermes Agent (one-time)

If `hermesbench doctor` reports missing Hermes Agent:

```bash
git clone https://github.com/NousResearch/hermes-agent ~/.hermes/hermes-agent
cd ~/.hermes/hermes-agent
python3 -m venv .venv
.venv/bin/pip install -e .
```

Configure your provider (see PROVIDERS.md), then:

```bash
hermesbench validate
hermesbench run --use-hermes-config --model YOUR_MODEL \
  --task t01_terminal_smoke/t01_echo --toolsets all
```

## Full benchmark (61 tasks)

```bash
hermesbench run --use-hermes-config --model YOUR_MODEL --all --toolsets all
```

Results: `results/<run_id>/summary.json`, traces under `traces/<run_id>/`.

## Report and video

```bash
hermesbench report --run-id <run_id>
# optional (needs Node):
hermesbench report --run-id <run_id> --render-video
```

## Local model server path (no cloud)

Use `hermesbench run` with an OpenAI-compatible server (llama.cpp, vLLM, etc.):

```bash
hermesbench run --task t01_terminal_smoke/t01_echo \
  --model your-gguf-name --base-url http://127.0.0.1:8080/v1
```

Do **not** add `--use-hermes-config` for local no-auth servers. HermesBench passes the local `--base-url` and a placeholder API key to Hermes Agent so the request stays on the OpenAI-compatible endpoint instead of falling back to the user's configured provider.

Note: **`hermesbench run`** is the only benchmark entry point (real Hermes Agent). `tests/support/fake_hermes.py` is for optional pipeline tests only.
