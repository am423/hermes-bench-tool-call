# hermesbenchv0.1 — Plan

A simple, reproducible benchmark for evaluating local models running inside the
**Hermes Agent** harness. Captures full traces (every tool call + tool result)
so the same dataset doubles as supervised fine-tuning (SFT) training data.

> Repo: `github.com/am423/hermesbenchv0_1` (private)
> Folder: `~/projects/hermesbenchv0_1/`
> v0.1 = first usable release. v0.2+ will add multi-modal, longer-horizon, and
> adversarial tool-failure scenarios.

---

## 1. Why this exists

Generic agent benchmarks (SWE-bench, AgentBench, ToolBench, τ-bench) test
broad reasoning, but **none of them are calibrated against the actual tool
surface, argument shapes, and failure envelopes a model sees inside
`run_agent.AIAgent`**. We want:

1. A score that predicts how a model will perform **in our harness, on our
   tool set, with our JSON error envelopes** — not on someone else's.
2. A captured trace for every run, in the exact message format the harness
   produces (`role: system|user|assistant|tool`, `tool_calls` JSON, `tool_call_id`
   pairing, `success: bool` results), suitable for SFT without reformatting.
3. Tasks that fit on a single local box (no Docker orchestration, no live
   internet required, no API keys) so they run on the same Arc B70 / RTX 3090
   hardware we already benchmark LLMs on.

### Data grounding

Pulled from `~/.hermes/state.db` (327 sessions, 18,541 messages, 9,224
assistant-issued tool invocations). Tool distribution:

| Tool | Count | Share | Why it's in the benchmark |
|---|---:|---:|---|
| `terminal` | 4,763 | 51.6% | Core: build, run, test, inspect |
| `read_file` | 1,167 | 12.6% | Paginated source-code reading |
| `patch` | 932 | 10.1% | Surgical code edits w/ fuzzy match |
| `search_files` | 515 | 5.6% | `rg`-backed content & file search |
| `write_file` | 446 | 4.8% | New file creation |
| `process` | 294 | 3.2% | Long-running bg process mgmt |
| `todo` | 268 | 2.9% | Multi-step planning |
| `skill_view` | 263 | 2.9% | Skill lookup |
| `execute_code` | 184 | 2.0% | Python REPL via kernel |
| `web_search` | 125 | 1.4% | Grounded lookups |
| `web_extract` | 72 | 0.8% | URL → markdown |
| `vision_analyze` | 36 | 0.4% | Image Q&A |
| `delegate_task` | 36 | 0.4% | Subagent fan-out |
| `memory` | 22 | 0.2% | Persistent facts |
| `clarify` | 20 | 0.2% | Asking the user |
| `browser_*` | 38 | 0.4% | Browser automation |
| _other_ | 89 | 1.0% | `skills_list`, `cronjob`, etc. |

**Top 6 = 88% of traffic.** Top 10 = 96%. v0.1 covers the top 6 + 4
"common but different" tools (todo, execute_code, web_search, memory) for a
10-tool surface. v0.2+ layers in browser/vision/delegate/skill_view.

Median session = 34 tool-call turns. p90 = 186. v0.1 tasks are sized 5-30
turns so they finish in 2-15 min on a 7B model.

---

## 2. Design principles

| Principle | Decision |
|---|---|
| **Simple** | Single Python entry point, no Docker, no orchestrator. Stdlib + `pyyaml` only. |
| **Reproducible** | Tasks ship a deterministic input fixture (committed to repo). Same input → same expected output. No live network. |
| **Hermes-shaped** | Tasks are run via the actual `AIAgent` (or a slim `HermesBenchHarness` that reuses `model_tools.py` + `tools/registry.py`). Models see real tool schemas, real error envelopes. |
| **Trace-capturing** | Every run writes `traces/<model>_<task>_<timestamp>.jsonl` with one line per message in the exact format the harness produces. |
| **SFT-ready** | Each trace is a complete conversation (`system → user → assistant(tool_calls) → tool → ... → assistant(content)`). We can slice it into `(prompt, completion)` pairs directly. |
| **Scored** | Each task has a deterministic verifier. No LLM-as-judge in v0.1. |
| **Fast feedback** | Per-task wall-clock + token count printed. Per-model summary table. |

### Non-goals (v0.1)

- Multi-modal tasks (vision/browser) → v0.2
- Adversarial prompt injection → v0.3
- Long-horizon planning (100+ turns) → v0.2
- Live network calls → v0.2 (with a `network: required` flag per task)
- LLM-as-judge for free-form answers → never, by design

---

## 3. Architecture

```
hermesbenchv0_1/
├── project.md                  # this file
├── README.md                   # quick-start
├── pyproject.toml              # hermesbench package
├── hermesbench/
│   ├── __init__.py
│   ├── __main__.py             # `python -m hermesbench ...`
│   ├── cli.py                  # CLI: run / score / export / list
│   ├── harness.py              # wraps AIAgent OR a slim in-process loop
│   ├── scoring.py              # deterministic verifiers
│   ├── trace.py                # trace recorder (jsonl writer)
│   └── tasks/
│       ├── __init__.py         # task registry
│       ├── _schema.py          # TaskSpec dataclass + validator
│       ├── t01_terminal_smoke/ # 5 tasks
│       ├── t02_file_read/      # 5 tasks
│       ├── t03_patch_edit/     # 5 tasks
│       ├── t04_search_grep/    # 5 tasks
│       ├── t05_write_new/      # 5 tasks
│       ├── t06_process_mgmt/   # 3 tasks
│       ├── t07_todo_plan/      # 3 tasks
│       ├── t08_execute_code/   # 3 tasks
│       ├── t09_web_lookup/     # 3 tasks (offline-mock fixture)
│       └── t10_memory_facts/   # 3 tasks
├── fixtures/                   # committed task input data
│   ├── small_repo/            # ~50 file Python project
│   ├── broken_code/           # 10 small broken snippets to fix
│   ├── data_files/            # CSV/JSON for search tasks
│   └── web_corpus/            # 50 mock pages for web_extract (no live net)
├── traces/                     # gitignored: per-run output
│   └── .gitkeep
├── results/                    # gitignored: aggregated scores
│   └── .gitkeep
└── .gitignore
```

### Two execution modes

**Mode A — `AIAgent` wrapper (default).** Import `AIAgent` from
`~/.hermes/hermes-agent/run_agent.py`. Run via the existing OpenAI-compatible
`client.chat.completions.create(messages=..., tools=...)` interface. Capture
every message into a jsonl trace. **This is the canonical mode** — it scores
the model exactly as a user would experience it.

**Mode B — `HermesBenchHarness` (fallback / CI).** A 200-line slim harness
that loads tool schemas from `tools/registry.py` but makes raw
`chat.completions.create` calls itself. Used when the full `AIAgent` can't be
imported (e.g., CI without all hermes-agent deps) or when we want byte-perfect
control over which messages get sent. **Same tool schemas, same error
envelopes, same trace format** as Mode A.

Mode selection is automatic: try A, fall back to B on ImportError.

### Trace format (one jsonl line per harness message)

```json
{"role": "system", "content": "...", "ts": 1700000000.0}
{"role": "user", "content": "Fix the off-by-one in src/calc.py", "ts": ...}
{"role": "assistant", "content": null, "tool_calls": [
  {"id": "call_1", "type": "function",
   "function": {"name": "read_file",
                "arguments": "{\"path\": \"src/calc.py\"}"}}], "ts": ...}
{"role": "tool", "tool_call_id": "call_1",
 "name": "read_file",
 "content": "{\"success\": true, \"content\": \"...\"}", "ts": ...}
{"role": "assistant", "content": "Done. The bug was...", "ts": ...}
```

This is the **exact wire format** `AIAgent.run_conversation()` produces, so
traces are SFT-ready with zero transformation.

---

## 4. Task taxonomy (40 tasks in v0.1)

Each task is a directory with:
- `task.yaml` — name, prompt, allowed_tools, max_turns, expected_artifacts
- `verifier.py` — deterministic Python function returning `(passed: bool, details: dict)`
- `fixture/` — committed input data (gitignored size caps apply)

### Category 1: `terminal` (5 tasks)

| ID | Task | Tests |
|---|---|---|
| `t01_terminal_smoke` | Run a build, capture exit code | `terminal` JSON args, non-zero exit handling |
| `t02_terminal_compile` | Compile a C file with intentional warnings | Long output truncation, error extraction |
| `t03_terminal_pipeline` | Pipe `cat \| grep \| wc` | Multi-command chaining |
| `t04_terminal_env` | Check an env var that does/doesn't exist | Reading error messages |
| `t05_terminal_long` | Start a 5-second sleep, observe via `process` list, kill it | `terminal` + `process` handoff |

### Category 2: `read_file` (5 tasks)

| ID | Task | Tests |
|---|---|---|
| `t01_read_head` | Read first 50 lines | offset/limit args |
| `t02_read_tail` | Read last 20 lines | Offset calculation |
| `t03_read_paginated` | Read 500-line file in 3 chunks | Multi-call pagination |
| `t04_read_missing` | Read non-existent file | Error envelope recovery |
| `t05_read_nested` | Read deeply-nested path | Path quoting |

### Category 3: `patch` (5 tasks) — *the hardest, most failure-prone tool*

| ID | Task | Tests |
|---|---|---|
| `t01_patch_unique` | Replace a unique function | Successful patch |
| `t02_patch_ambiguous` | Match appears twice, must disambiguate via context | Reading "Did you mean" hints |
| `t03_patch_unicode` | Replace string with non-ASCII | Encoding handling |
| `t04_patch_multiline` | 30-line block replace | Large old_string |
| `t05_patch_v4a` | Use `mode=patch` with V4A format | Knowing the V4A syntax |

### Category 4: `search_files` (5 tasks)

| ID | Task | Tests |
|---|---|---|
| `t01_search_basic` | Find all files containing "TODO" | `pattern` + `path` |
| `t02_search_with_glob` | Search only `*.py` | `file_glob` arg |
| `t03_search_output` | Switch `output_mode: files_only \| content \| count` | Mode selection |
| `t04_search_regex` | Use a regex pattern | Regex escaping |
| `t05_search_no_match` | Handle empty result | No false positives |

### Category 5: `write_file` (5 tasks)

| ID | Task | Tests |
|---|---|---|
| `t01_write_new` | Create a new file | Basic write |
| `t02_write_overwrite` | Overwrite existing file | No diff-merge failure |
| `t03_write_large` | Write a 10K-line file | Token-efficient content |
| `t04_write_with_unicode` | Write file with non-ASCII content | Encoding |
| `t05_write_path_create` | Write to a path whose parent dirs don't exist | Error recovery |

### Category 6: `process` (3 tasks)

| ID | Task | Tests |
|---|---|---|
| `t01_process_list` | List bg processes | `process(action="list")` |
| `t02_process_kill` | Kill a leaked process | `process(action="kill")` |
| `t03_process_poll` | Poll a running process for output | `process(action="poll")` |

### Category 7: `todo` (3 tasks)

| ID | Task | Tests |
|---|---|---|
| `t01_todo_plan` | Decompose a 4-step task into todos | Multi-item todos array |
| `t02_todo_update` | Mark item in_progress, then completed | Status transitions |
| `t03_todo_replan` | Insert a new todo mid-flight | `merge: true` semantics |

### Category 8: `execute_code` (3 tasks)

| ID | Task | Tests |
|---|---|---|
| `t01_repl_math` | Compute a non-trivial result in Python | REPL state persistence |
| `t02_repl_pandas` | Load a CSV, aggregate, return answer | Pandas correctness |
| `t03_repl_debug` | Find a bug by running code incrementally | Multi-step REPL |

### Category 9: `web_search` / `web_extract` (3 tasks — **offline-mocked**)

| ID | Task | Tests |
|---|---|---|
| `t01_web_search` | Search for a fact | Query formulation |
| `t02_web_extract` | Extract content from a known URL | URL list construction |
| `t03_web_no_result` | Handle empty search | No hallucination |

These use a local mock server (`fixtures/web_corpus/`) — no live internet.

### Category 10: `memory` (3 tasks)

| ID | Task | Tests |
|---|---|---|
| `t01_memory_save` | Save a fact | `memory(action="add")` |
| `t02_memory_recall` | Recall across turns | Persistence check |
| `t03_memory_avoid_dup` | Don't re-save a known fact | Dedup judgement |

---

## 5. Scoring

Per-task score = `verifier.py` returns `passed: bool`. Aggregate:

- **Pass rate** = tasks passed / tasks attempted (primary metric)
- **Tool-use efficiency** = median tool calls per task (lower = better, with floor)
- **Token efficiency** = input+output tokens / task
- **Wall-clock** = seconds / task
- **Recovery rate** = % of `success: false` tool results followed by a correct
  next move within 2 turns (measures error-recovery skill)
- **Format compliance** = % of tool calls with valid JSON `arguments` matching
  the schema (no extra/missing keys, right types)

A single model produces a results row like:

```
model: qwen2.5-coder-7b-instruct-q4_k_m
pass_rate:        28/40 (70.0%)
tool_efficiency:  median 6.1 calls/task
token_efficiency:  14,200 tok/task avg
wall_clock:       38.4 s/task avg
recovery_rate:    81.2%
format_compliance: 99.4%
```

### Verifier pattern

```python
# hermesbench/tasks/t03_patch_edit/t02_patch_ambiguous/verifier.py
def verify(workdir: Path, trace: list[dict]) -> tuple[bool, dict]:
    target = workdir / "src" / "config.py"
    if not target.exists():
        return False, {"reason": "file missing"}
    content = target.read_text()
    # Expect: only ONE block of `TIMEOUT = 30` (the duplicated one was fixed)
    count = content.count("TIMEOUT = 30")
    if count != 1:
        return False, {"reason": f"expected 1 'TIMEOUT=30', got {count}"}
    return True, {"checks": {"timeout_count": count}}
```

---

## 6. CLI

```bash
# List tasks
python -m hermesbench list
python -m hermesbench list --category patch

# Run a single task against a model
python -m hermesbench run \
    --model qwen2.5-coder-7b-instruct-q4_k_m \
    --task t03_patch_edit/t02_patch_ambiguous \
    --base-url http://127.0.0.1:8080/v1

# Run a full category
python -m hermesbench run --model ... --category patch

# Run the full 40-task suite
python -m hermesbench run --model ... --all

# Re-score from existing traces (no re-run)
python -m hermesbench score traces/qwen*.jsonl

# Export traces as SFT jsonl (one completion per line)
python -m hermesbench export-sft \
    --in traces/ \
    --out sft_dataset.jsonl \
    --format openai
```

---

## 7. Implementation phases

### Phase 1 — Skeleton + Mode A harness (Day 1-2)
- [ ] `pyproject.toml` + `hermesbench/` package skeleton
- [ ] `harness.py` with `AIAgent` wrapper that streams messages into the trace recorder
- [ ] `trace.py` jsonl writer
- [ ] 1 task per category as smoke tests (10 tasks)
- [ ] Verify a known-good model (e.g. Hermes 4 70B via OpenRouter) passes them

### Phase 2 — Author 40 tasks (Day 3-7)
- [ ] Categories 1-6 (29 tasks): file/terminal/process — the 88% bulk
- [ ] Categories 7-10 (11 tasks): todo/exec_code/web/memory
- [ ] Each task gets: `task.yaml`, `verifier.py`, fixture data
- [ ] Commit fixtures to repo (size cap: 100 KB per fixture, gzip if larger)

### Phase 3 — Mode B fallback harness (Day 8)
- [ ] `HermesBenchHarness` 200-line implementation
- [ ] Auto-fallback test: kill `AIAgent` import path, confirm Mode B runs

### Phase 4 — Scoring + reporting (Day 9)
- [ ] `scoring.py` computes all 6 metrics
- [ ] `results/<model>_<date>.json` per-run aggregate
- [ ] Pretty-print summary table

### Phase 5 — Export to SFT format (Day 10)
- [ ] `export-sft` command: traces → OpenAI / ShareGPT / Hermes message formats
- [ ] Sanity check: load exported SFT jsonl, count completions, inspect a sample

### Phase 6 — Initial baseline runs (Day 11-12)
- [ ] Run against 3 representative local models: a small (3-4B), a medium (7-8B), a large (32-70B)
- [ ] Publish `results/baseline_<date>.md` in the repo
- [ ] Commit traces (or a sample of them) so others can reproduce

### Phase 7 — v0.1 release tag (Day 13)
- [ ] README with quick-start, results table, "how to add a task" guide
- [ ] `git tag v0.1`
- [ ] Internal dogfood: run the suite in our own dev loop for 1 week, fix anything that breaks

---

## 8. v0.2+ roadmap (out of scope for v0.1, listed for context)

- **v0.2 — Multi-modal + longer horizon:** vision tasks (image Q&A), browser tasks (offline mock DOM), 60-100 turn projects
- **v0.3 — Adversarial:** prompt-injection resistance, ambiguous user prompts, broken-tool recovery
- **v0.4 — Live net:** opt-in `network: required` flag, real `web_search`/`web_extract`
- **v0.5 — Cross-session:** tasks that span multiple `AIAgent` sessions with persistent memory
- **v0.6 — Skill usage:** force-load a skill, test if model invokes `skill_view` to read it
- **v1.0 — Public leaderboard:** website hosting results, model submission PR workflow

---

## 9. Success criteria for v0.1

- [ ] All 40 tasks have a passing implementation
- [ ] `python -m hermesbench run --all` works on a fresh checkout in <30 min on a 7B model
- [ ] Three baseline models run cleanly, results published
- [ ] At least 100 trace jsonl files committed (dogfooding)
- [ ] `export-sft` produces a valid jsonl that fine-tunes a model to ≥+5% pass-rate on a held-out task
- [ ] README lets a new user run their first task in <5 min

---

## 10. Open questions

1. **Mode A vs Mode B in CI?** Mode A drags in all of hermes-agent's deps. If we want a slim CI image, Mode B is the path. **Decision: ship both, default to A.**
2. **What fixture size cap?** 100 KB / task keeps the repo under 5 MB. **Decision: 100 KB; document the cap in `tasks/_schema.py`.**
3. **Token-budget per task?** Unbounded makes 70B models OOM. **Decision: 8K context hard cap per task, configurable up to 32K. Refused if exceeded.**
4. **Should verifiers be allowed to import hermes-agent?** No — verifiers must be stdlib-only so they're portable. **Decision: enforce via lint.**
5. **Live web tasks in v0.1?** No — adds flakiness. **Decision: mock corpus for v0.1, opt-in live in v0.4.**

---

## 11. References

- Hermes Agent harness: `~/.hermes/hermes-agent/run_agent.py` (AIAgent)
- Tool schemas: `~/.hermes/hermes-agent/tools/registry.py` + `toolsets.py`
- Session data source: `~/.hermes/state.db` (SQLite, FTS5-indexed)
- AIAgent loop contract: see `AGENTS.md` § "Agent Loop"
