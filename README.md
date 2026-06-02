# hermesbenchv0.1

A simple, reproducible benchmark for local models running inside the
**Hermes Agent** harness. Captures full conversation traces (every tool
call + tool result) so the dataset doubles as supervised fine-tuning (SFT)
training data.

> See `project.md` for the full plan, task taxonomy, and scoring methodology.

## TL;DR

- **40 deterministic tasks** covering the top-6 most-used tools (terminal,
  read_file, patch, search_files, write_file, process) plus todo, execute_code,
  web (mocked), memory.
- **Two harness modes:** Mode A uses the real `AIAgent` from
  `~/.hermes/hermes-agent/`; Mode B is a 200-line slim fallback for CI.
- **Full traces** written as jsonl in the exact wire format the harness
  produces — no reformatting needed for SFT.
- **Deterministic verifiers**, no LLM-as-judge.

## Quick start (after Phase 1 lands)

```bash
git clone git@github.com:am423/hermesbenchv0_1.git
cd hermesbenchv0_1
pip install -e .

# Run a single task against a local llama.cpp server
python -m hermesbench run \
    --model qwen2.5-coder-7b-instruct-q4_k_m \
    --task t03_patch_edit/t02_patch_ambiguous \
    --base-url http://127.0.0.1:8080/v1
```

## Status

**v0.1 — planning phase.** Repo + plan only. See `project.md` § 7 for the
implementation roadmap.

## Repo

- GitHub: `github.com/am423/hermesbenchv0_1` (private until v0.1 release)
- License: TBD (likely MIT)
