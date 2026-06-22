# Providers for `hermesbench run`

`hermesbench run` invokes Hermes Agent `run_agent.py`. Credentials come from **Hermes config**, not from this repo.

## Recommended: `~/.hermes/config.yaml`

Install and configure Hermes Agent, then set the default provider in config (examples — adjust to your setup):

- **xAI OAuth** — model ids like `grok-composer-2.5-fast`; use `--use-hermes-config` so the benchmark does not override base URL.
- **OpenRouter / custom gateway** — set provider in config or use env below.

Run with:

```bash
hermesbench run --use-hermes-config --model <model-id> --all
```

## Environment variables

Alternatively (OpenAI-compatible):

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL` (e.g. `http://127.0.0.1:8080/v1` for local servers)
- `OPENAI_MODEL`

Without `--use-hermes-config`, `hermesbench run` passes `--base_url` / `--api_key` and sets `OPENAI_*` in the subprocess environment. If `OPENAI_API_KEY` is not set, HermesBench supplies a harmless `dummy` key. This is intentional: many local servers do not check auth, but Hermes Agent still needs an explicit key to stay on the OpenAI-compatible endpoint path instead of falling back to the user's configured Hermes provider.

### Local vLLM / llama.cpp no-auth servers

For a local OpenAI-compatible endpoint, omit `--use-hermes-config`:

```bash
hermesbench run \
  --model qwen36-27b-nvfp4 \
  --base-url http://127.0.0.1:8999/v1 \
  --task t01_terminal_smoke/t01_echo \
  --toolsets all
```

If a run's `run_agent.log` mentions a cloud/OAuth endpoint instead of the specified `--base-url`, treat the run as invalid and rerun after updating HermesBench. This failure mode previously appeared as a fast 0/N run with `HTTP 403` from the wrong provider.

## Security

- Never commit API keys or OAuth tokens.
- Copy `.env.example` to `.env` locally if you use dotenv; keep `.env` gitignored.

## Smoke test

```bash
hermesbench run --use-hermes-config --model YOUR_MODEL \
  --task t01_terminal_smoke/t01_echo --toolsets all
```

Expect `PASS` in under a minute if provider and Hermes venv are healthy.