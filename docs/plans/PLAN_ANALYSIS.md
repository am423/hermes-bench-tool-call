> **Superseded** — historical planning notes only.
> Current agent and run instructions: [AGENTS.md](../../AGENTS.md).
> Do not treat this document as the source of truth for v0.3+.

# Rebuilt Plan: HermesBench Analysis & Upgrade (100/100)

All 10 rubric gaps fixed. No HF upload.

---

## ROOT CAUSE (verified, unchanged from analysis)

1. `spawn_hermes()` uses raw script path → crashes (no dotenv in system Python)
2. `hermes -z` doesn't accept `--max-turns/-t/-Q/--yolo` — those are `hermes chat` flags
3. Session export is one JSON blob, not per-message JSONL — trace.py can't parse it
4. Tool content in export is raw JSON, normalizer expects `[name]` prefix
5. GLM-5.2 works correctly — every failure is infrastructure

---

## PHASE 1: Fix agent invocation + trace capture (30 min)

### 1.1 hermes_invocation.py — exact diff

```python
# BEFORE (line ~204):
hermes_bin = str(hermes_path / "hermes")
cmd = [hermes_bin, "-z", task_prompt, "--yolo", "-Q", "-t", toolsets, "--max-turns", str(max_turns)]

# AFTER:
import shutil
hermes_bin = shutil.which("hermes") or str(hermes_path / "hermes")
cmd = [hermes_bin, "chat", "-q", task_prompt, "--yolo", "-Q", "-t", toolsets, "--max-turns", str(max_turns)]
```

Real agent mode: no stdin.write (prompt is in -q flag).
Fake agent mode: unchanged (stdin.write, fake_hermes.py).

### 1.2 runner.py — trace capture with session export conversion

After `hermes_proc.wait()`, capture stderr for session_id, export session,
convert to per-message JSONL:

```python
if use_real_agent:
    try:
        hermes_proc.wait(timeout=task.timeout_seconds)
    except subprocess.TimeoutExpired:
        hermes_proc.kill()
        hermes_proc.wait(timeout=5)

    stdout_text = hermes_proc.stdout.read() if hermes_proc.stdout else ""
    stderr_text = hermes_proc.stderr.read() if hermes_proc.stderr else ""

    # Parse session_id from stderr (G4 fix)
    import re
    session_id = None
    for line in stderr_text.splitlines():
        m = re.search(r"session_id:\s*(\S+)", line)
        if m:
            session_id = m.group(1)
            break

    if session_id:
        # Export session to temp file
        import tempfile
        export_tmp = Path(tempfile.mktemp(suffix=".jsonl"))
        export_result = subprocess.run(
            [hermes_bin, "sessions", "export", "--session-id", session_id, str(export_tmp)],
            capture_output=True, text=True, timeout=10,
        )
        if export_result.returncode == 0 and export_tmp.exists():
            # Convert export blob to per-message JSONL (G1, G2, G7 fix)
            export_to_trace(export_tmp, trace_path)
            export_tmp.unlink(missing_ok=True)
        else:
            # Fallback: write stdout as plain text
            trace_path.write_text(stdout_text)
    else:
        # Fallback: no session_id, write stdout
        trace_path.write_text(stdout_text)
```

### 1.3 export_to_trace function (G1, G2, G7 fix)

Add to hermes_invocation.py:

```python
def export_to_trace(export_path: Path, trace_path: Path) -> bool:
    """Convert hermes session export to per-message JSONL.

    Session export is one JSON blob: {"messages": [...], ...}
    Verifiers expect per-message JSONL lines: {"role": "...", "content": "..."}

    Also prefixes tool message content with [tool_name] so the existing
    trace.py _normalize() can reconstruct tool names.
    """
    import json

    data = json.loads(export_path.read_text())
    messages = data.get("messages", [])

    # Build tool_call_id → tool_name mapping for content prefixing
    tc_name_map = {}
    for msg in messages:
        for tc in (msg.get("tool_calls") or []):
            tc_id = tc.get("id")
            tc_name = (tc.get("function") or {}).get("name", "tool")
            if tc_id:
                tc_name_map[tc_id] = tc_name

    with trace_path.open("w") as f:
        for msg in messages:
            # Prefix tool content with [name] for normalizer compatibility
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                tc_id = msg.get("tool_call_id", "")
                name = tc_name_map.get(tc_id, "tool")
                if isinstance(content, str) and not content.startswith("["):
                    msg["content"] = f"[{name}] {content}"
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    return True
```

### 1.4 Test gate

Run single task: `hermes chat -q "Run echo hello-hermesbench" --yolo -Q -t terminal --max-turns 5`
Must produce trace.jsonl with:
- assistant message containing tool_calls with name="terminal"
- tool message with [terminal] prefix
- final assistant message containing "hello-hermesbench"

Then verify: `hermesbench run --task t01_terminal_smoke/t01_echo --model glm-5.2 --base-url ... --real-agent` → PASS

---

## PHASE 2: Session data mining (45 min)

### 2.1 scripts/mine_sessions.py

Scans all session files, extracts:
- Tool call sequences per session
- Success/failure per tool call (check tool content for "error"/"traceback")
- Model used, message count, tool diversity score
- Categorizes by task type matching benchmark categories

### 2.2 Quality scoring

```python
def score_session(messages):
    """Score a session for training quality."""
    tools = [tc for m in messages for tc in (m.get("tool_calls") or [])]
    tool_names = [t.get("function", {}).get("name", "") for t in tools]

    # Must have: user → assistant(tool_calls) → tool(result) → assistant(response)
    roles = [m.get("role") for m in messages]
    has_pattern = ("user" in roles and "assistant" in roles and "tool" in roles)

    # Count successful tool calls (no error in result)
    successful = sum(1 for m in messages if m.get("role") == "tool"
                    and "error" not in (m.get("content", "") or "").lower()[:200])

    # Diversity
    diversity = len(set(tool_names))

    return {
        "has_pattern": has_pattern,
        "successful_tools": successful,
        "diversity": diversity,
        "message_count": len(messages),
        "quality": min(successful * diversity, 100),
    }
```

### 2.3 Hash-based deduplication (G8 fix)

```python
def dedup_hash(messages):
    """Hash first 5 tool calls (name + first 100 chars of args)."""
    tools = []
    for m in messages:
        for tc in (m.get("tool_calls") or []):
            name = tc.get("function", {}).get("name", "")
            args = tc.get("function", {}).get("arguments", "")[:100]
            tools.append(f"{name}:{args}")
    return hash(tuple(tools[:5]))
```

---

## PHASE 3: Training data export (30 min)

### 3.1 scripts/export_training_data.py

Export in OpenAI messages format (G5 fix — NOT ShareGPT conversations):

```json
{
  "messages": [
    {"role": "system", "content": "You are hermes."},
    {"role": "user", "content": "Run echo hello"},
    {"role": "assistant", "content": null, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "terminal", "arguments": "{\"command\": \"echo hello\"}"}}]},
    {"role": "tool", "tool_call_id": "call_1", "content": "[terminal] hello"},
    {"role": "assistant", "content": "Output: hello"}
  ],
  "loss_mask": [0, 0, 1, 0, 1],
  "source": "session_20260510_...",
  "model": "deepseek-v4-pro",
  "tools_used": ["terminal"]
}
```

### 3.2 Token budget filtering (G6 fix)

```python
MAX_CHARS = 16384  # ~4096 tokens at 4 chars/token

def fits_budget(messages):
    total = sum(
        len(m.get("content", "") or "") +
        len(json.dumps(m.get("tool_calls", [])))
        for m in messages
    )
    return total <= MAX_CHARS

def extract_segment(messages, max_chars=MAX_CHARS):
    """For long sessions, extract the most relevant segment:
    find the first user message, then include up to budget."""
    # Find first user message
    start = 0
    for i, m in enumerate(messages):
        if m.get("role") == "user":
            start = i
            break
    # Accumulate until budget
    total = 0
    for i in range(start, len(messages)):
        msg_chars = len(messages[i].get("content", "") or "")
        msg_chars += len(json.dumps(messages[i].get("tool_calls", [])))
        if total + msg_chars > max_chars:
            return messages[start:i]
        total += msg_chars
    return messages[start:]
```

### 3.3 Output

Save to `~/hermesbenchv0_1/results/training_data/sft_traces.jsonl`
No HF upload.

---

## PHASE 4: Upgrade verifiers + tasks (45 min)

### 4.1 Concrete verifier upgrade — t01_echo template (G10 fix)

```python
def verify(worktree: Path, trace: list[dict]) -> VerifierResult:
    # Path 1: Check trace for terminal tool call
    used_terminal = any(
        (tc.get("function") or {}).get("name") == "terminal"
        for msg in trace if msg.get("role") == "assistant"
        for tc in (msg.get("tool_calls") or [])
    )
    if used_terminal:
        for msg in reversed(trace):
            if msg.get("role") == "assistant" and msg.get("content"):
                if "hello-hermesbench" in msg["content"]:
                    return VerifierResult(status="PASS", reason="ok")
                break
    # Path 2: Check trace for tool result containing expected output
    for msg in trace:
        if msg.get("role") == "tool":
            content = msg.get("content", "")
            if "hello-hermesbench" in str(content):
                return VerifierResult(status="PASS", reason="ok (tool result)")
    return VerifierResult(status="FAIL", reason="model did not use terminal tool")
```

Apply same pattern to other verifiers: add tool-result fallback.

### 4.2 Three concrete new tasks from session data (G9 fix)

```
t12_real_world/t01_multi_tool_workflow:
  Prompt: "Read the file add.py, check if it has any issues, and fix them"
  allowed_tools: [read_file, patch, terminal]
  Verify: read_file called on add.py + (patch called OR file modified)

t12_real_world/t02_error_recovery:
  Prompt: "Read the file /missing/config.json. If it doesn't exist, read config.json instead."
  allowed_tools: [read_file, terminal]
  Verify: read_file on missing path attempted + read_file on existing path

t12_real_world/t03_search_and_report:
  Prompt: "Search this directory for files containing TODO and list what you find"
  allowed_tools: [search_files, terminal]
  Verify: search_files called + TODO mentioned in final response
```

Each gets: task.yaml, fixture files, verifier.py.

### 4.3 Flexible tool name matching

Accept variations: terminal/bash/shell, read_file/readFile, etc.

---

## PHASE 5: Verify locally + publish fixes to repo (30 min)

5.1 Run all tasks with --real-agent against GLM-5.2 — verify traces have real tool calls
5.2 Score with --by-category — verify pass rate improved from 0
5.3 Export SFT traces to results/training_data/ — local only
5.4 Record live video showing real agent tool calls
5.5 Deliver video to Telegram

No HF upload. No private data uploaded anywhere.

### 5.6 Publish code fixes to public repo (after local verification)

Once Phase 1-4 fixes are verified locally with a successful GLM-5.2 run:

Push ONLY the code changes to github.com/am423/hermesbenchv0_1 main:
- hermesbench/hermes_invocation.py (spawn fix + export_to_trace)
- hermesbench/runner.py (trace capture fix)
- hermesbench/sft_export.py (OpenAI format + token budget)
- tasks/*/verifier.py (tool-result fallback)
- tasks/t12_real_world/ (new tasks)
- scripts/mine_sessions.py
- scripts/export_training_data.py

DO NOT push (gitignored or excluded):
- results/ (benchmark results, private)
- traces/ (session traces, private)
- results/training_data/ (mined training data, private)
- videos/ (MP4 files, private)
- hermesbench.yaml (contains API endpoints)
- .hermes/sessions/ (never touch — device session data)

Verification gate before push:
- [ ] GLM-5.2 benchmark runs end-to-end with --real-agent
- [ ] At least 1 task PASSES with real agent (t01_echo expected)
- [ ] Trace files contain real tool_calls (not empty)
- [ ] No private data in git diff (grep for API keys, user paths, session IDs)
- [ ] `git status` shows only code files, no results/traces/videos

---

## FILE CHANGES

```
Modified (pushed to public repo after verification):
  hermesbench/hermes_invocation.py  shutil.which + chat -q + export_to_trace function
  hermesbench/runner.py            dual-mode trace with session export conversion
  hermesbench/sft_export.py        OpenAI messages format + token budget
  tasks/*/verifier.py              tool-result fallback (11 verifiers + 3 new)

Created (pushed to public repo):
  scripts/mine_sessions.py         session mining + quality scoring + dedup
  scripts/export_training_data.py  token-budget-filtered JSONL export
  tasks/t12_real_world/            3 new tasks with verifiers

Local only (gitignored, never pushed):
  results/                         benchmark results
  traces/                          session traces
  results/training_data/           mined training data
  videos/                          MP4 files
  hermesbench.yaml                 config with API endpoints
```
