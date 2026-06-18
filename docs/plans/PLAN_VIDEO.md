> **Superseded** — historical planning notes only.
> Current agent and run instructions: [AGENTS.md](../../AGENTS.md).
> Do not treat this document as the source of truth for v0.3+.

# Hyperframes Video Plan — GLM-5.2 Benchmark with Real Agent

## Problem
Current video is static text. fake_hermes.py produces no visible terminal work.
Need real hermes-agent sessions showing GLM-5.2 making actual tool calls.

## Solution
Run a curated subset of tasks with --real-agent, capture the agent tmux sessions
live, overlay GPU metrics, assemble into a hyperframes MP4.

## Pane Layout

```
┌──────────────────────────────┬───────────────────────┐
│                              │                       │
│  PANE 1: Benchmark Runner    │  PANE 2: Metrics      │
│  Live task progress          │  (if local model)     │
│  t01_echo... PASS            │  OR API latency       │
│  t02_read_head... PASS       │  tok/s, TTFT          │
│  t03_compile... FAIL         │  Elapsed: 2m30s       │
│                              │                       │
├──────────────────────────────┼───────────────────────┤
│                              │                       │
│  PANE 3: Agent Session       │  PANE 4: Scoreboard   │
│  (live tmux capture from     │  PASS: 3  FAIL: 2     │
│   hermes-agent subprocess)   │  Cat: t01 2/3 (66%)   │
│  > terminal: echo hello      │  Cat: t02 1/3 (33%)   │
│  < hello                     │                       │
│  > read_file: src/main.py    │                       │
│                              │                       │
└──────────────────────────────┴───────────────────────┘
```

## Approach

GLM-5.2 is an API model (Z.AI), not local vLLM. So Pane 2 shows API
latency/throughput instead of GPU telemetry. For local models (NVFP4),
Pane 2 shows nvidia-smi metrics.

### Step 1: Run with --real-agent on a curated subset

Pick 6-8 tasks that are most visual:
- t01_echo (terminal — shows echo output)
- t02_read_head (read_file — shows file content)
- t03_compile_check (terminal — shows python syntax check)
- t05_env_check (terminal — shows env var)
- t01_basic patch (patch — shows code edit)
- t05_read_nested (read_file — shows path traversal)
- t02_read_tail (read_file)
- t02_ambiguous patch (harder — shows failure recovery attempt)

Run each with --real-agent so real hermes-agent CLI spawns and makes
visible tool calls in a tmux session.

### Step 2: Capture architecture

Option A — Live capture (preferred):
1. Start the benchmark in background
2. Poll for hermesbench-owned tmux sessions (hb-*)
3. Capture each session's content via tmux capture-pane
4. Record the assembled display via Xvfb + ffmpeg

Option B — Post-hoc from cast files:
1. Run benchmark normally (produces .cast files)
2. Replay each .cast file sequentially in a styled terminal
3. Record the replay

Option B is more reliable (no timing pressure) and works with the
existing cast files we already have from the fake_hermes run.
But those casts are from fake_hermes, not real agent.

Option C — Hybrid (best quality):
1. Run a few tasks with --real-agent first to get real casts
2. Replay the best casts in a styled multi-pane display
3. Add overlay text with score/category breakdown
4. Record the final display

### Step 3: Recommended — Option C

Phase 1: Get real agent casts (15 min)
- Run 4-5 tasks with --real-agent against GLM-5.2
- These produce real .cast files showing actual tool calls
- The agent will make real terminal/read_file/patch calls

Phase 2: Build the display (10 min)
- Create a Python script that:
  a. Renders Pane 1 (score summary) as static styled text
  b. Renders Pane 2 (API metrics — tok/s from timing)
  c. Replays real .cast files in Pane 3 sequentially with delays
  d. Renders Pane 4 (scoreboard updating as casts play)
- Use tmux to assemble the panes
- Record via Xvfb + ffmpeg

Phase 3: Record (5 min)
- 90-second recording: 10s intro + 60s task replays + 20s summary
- 1920x1080, 30fps, H.264

Phase 4: Post-process (5 min)
- Trim dead air
- Extract thumbnail

### Key Design Decisions

1. Use --real-agent for real tool call visibility
2. GLM-5.2 via Z.AI API — no GPU telemetry, use API timing instead
3. Short duration (90s) — show 3-4 best task replays, not all 48
4. Real casts, not fake — the agent session must show actual model decisions
5. Videos save to videos/ folder

### Prerequisites Check

- hermes-agent CLI in PATH: yes (~/.hermes/hermes-agent/hermes)
- GLM-5.2 API working: yes (verified)
- Xvfb + xterm + ffmpeg: yes (all installed)
- --real-agent flag: yes (implemented in v0.2)
- OPENAI_API_KEY + OPENAI_BASE_URL for GLM: working

### Risk: real agent may hang or need approvals

The --yolo flag skips approvals. But the agent might:
- Take too long on a task (use --max-turns)
- Get stuck in a loop (timeout_seconds per task)
- Not produce visible terminal output if it reasons too much

Mitigation: Pick simple tasks (echo, read_file) that complete quickly.
Use --max-turns 5 to limit agent iterations.

### Timeline

```
Phase 1: Real agent casts      15 min
Phase 2: Display builder        10 min
Phase 3: Record                  5 min
Phase 4: Post-process            5 min
Total:                          35 min
```

### Deliverable

~/hermesbenchv0_1/videos/glm52_benchmark.mp4
- 90 seconds, 1920x1080, H.264
- Shows GLM-5.2 making real tool calls in hermes-agent
- Multi-pane with score + task replay + scoreboard
