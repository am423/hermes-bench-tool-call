"""Hermes-agent invocation: find the checkout, spawn the subprocess.

Q22: resolution order is $HERMES_AGENT_PATH > ./hermes-agent/ >
~/.hermes/hermes-agent/ > `import hermes_agent`.
Q50: record the hermes git SHA in meta.json.
Q57: smoke-test the model endpoint before kicking off the suite.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
FAKE_HERMES_TEST_PATH = (
    Path(__file__).resolve().parent.parent / "tests" / "support" / "fake_hermes.py"
)

TOOLSET_MAP = {
    "terminal": "terminal",
    "read_file": "file",
    "patch": "file",
    "search_files": "search",
    "write_file": "file",
    "process": "terminal",
    "todo": "todo",
    "execute_code": "code_execution",
    "web_search": "web",
    "web_extract": "web",
    "memory": "memory",
}


def allowed_tools_to_toolsets(allowed_tools: list[str]) -> str:
    """Map task.yaml allowed_tools to hermes --toolsets value."""
    toolsets: set[str] = set()
    for tool in allowed_tools:
        mapped = TOOLSET_MAP.get(tool)
        if mapped:
            toolsets.add(mapped)
    return ",".join(sorted(toolsets)) if toolsets else "terminal"


def find_hermes_agent() -> Path:
    """Resolve the hermes-agent checkout per Q22."""
    env = os.environ.get("HERMES_AGENT_PATH")
    if env:
        p = Path(env).expanduser().resolve()
        if p.exists():
            return p
    cwd = Path.cwd()
    candidates = [
        cwd / "hermes-agent",
        Path.home() / ".hermes" / "hermes-agent",
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()
    # Fall back: try `import hermes_agent`
    try:
        import hermes_agent  # type: ignore[import-not-found]

        return Path(hermes_agent.__file__).parent.resolve()
    except ImportError:
        pass
    raise FileNotFoundError(
        "Could not find hermes-agent. Set $HERMES_AGENT_PATH or install hermes_agent."
    )


def hermes_python(hermes_path: Path) -> str:
    """Prefer Hermes Agent checkout venv for run_agent.py (fire, dotenv, etc.)."""
    venv_py = hermes_path / ".venv" / "bin" / "python"
    if venv_py.is_file():
        return str(venv_py)
    return sys.executable


def get_hermes_sha(hermes_path: Path) -> str:
    """Return the current git SHA of the hermes-agent checkout."""
    try:
        r = subprocess.run(
            ["git", "-C", str(hermes_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        out = r.stdout.strip()
        return out if out else "unknown"
    except Exception:
        return "unknown"


def get_hermes_version(hermes_path: Path) -> str:
    """Return the hermes-agent package version."""
    try:
        import hermes_agent  # type: ignore[import-not-found]

        return getattr(hermes_agent, "__version__", "unknown")
    except ImportError:
        return "unknown"


def smoke_test_endpoint(base_url: str, model: str, expected: dict) -> tuple[bool, str]:
    """Q57: send a 1-token request to verify the endpoint contract.

    Returns (ok, message). ok=False if the response shape is wrong.
    """
    try:
        import urllib.request

        api_key = os.environ.get("OPENAI_API_KEY", "")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/chat/completions",
            data=json.dumps(
                {
                    "model": model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1,
                    "stream": False,
                }
            ).encode(),
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
        # Check required fields
        for field in expected.get("required_fields", []):
            if field == "tools" and "tools" not in resp:
                # The response may not include tools; send a second request with tools
                req2 = urllib.request.Request(
                    f"{base_url.rstrip('/')}/chat/completions",
                    data=json.dumps(
                        {
                            "model": model,
                            "messages": [{"role": "user", "content": "hi"}],
                            "max_tokens": 1,
                            "tools": [
                                {
                                    "type": "function",
                                    "function": {
                                        "name": "noop",
                                        "description": "noop",
                                        "parameters": {},
                                    },
                                }
                            ],
                        }
                    ).encode(),
                    headers=headers,
                )
                with urllib.request.urlopen(req2, timeout=10) as r2:
                    resp2 = json.loads(r2.read())
                if "choices" not in resp2:
                    return False, "endpoint did not return choices for tool call"
                return True, "ok"
        if "choices" not in resp:
            return False, f"endpoint response missing 'choices': keys={list(resp.keys())}"
        return True, "ok"
    except Exception as e:
        return False, f"endpoint smoke test failed: {type(e).__name__}: {e}"


def spawn_hermes(
    *,
    hermes_path: Path,
    task_prompt: str,
    worktree: Path,
    isolated_home: Path,
    cast_path: Path,
    model: str,
    base_url: str,
    env_overrides: dict[str, str],
    timeout_seconds: int = 180,
    allowed_tools: list[str] | None = None,
    use_real_agent: bool = False,
    max_turns: int = 10,
) -> subprocess.Popen:
    """Spawn hermes-agent (real or fake) as a subprocess.

    Real mode: `hermes -z <prompt> --yolo -Q -t <toolsets> --max-turns N`
    Model/endpoint set via OPENAI_BASE_URL + OPENAI_MODEL env vars.
    Trace captured via HERMES_TRAJECTORY_PATH env var.

    Fake mode: tests/support/fake_hermes.py when HERMESBENCH_ALLOW_FAKE_RUNNER=1.
    """
    env = {
        **os.environ,
        "TERMINAL_ENV": "tmux_isolated",
        "HERMES_TMUX_SESSION": f"hb-{worktree.name}",
        "HERMES_TMUX_WORKTREE": str(worktree),
        "HERMES_TMUX_HOME": str(isolated_home),
        "HERMES_TMUX_CAST_PATH": str(cast_path),
        "OPENAI_BASE_URL": base_url,
        "OPENAI_MODEL": model,
        "HERMES_QUIET": "1",
        "HERMES_SAVE_TRAJECTORY": "1",
        "HERMES_TRAJECTORY_PATH": str(worktree / "trace.jsonl"),
        "PYTHONUNBUFFERED": "1",
        **env_overrides,
    }

    if use_real_agent:
        toolsets = allowed_tools_to_toolsets(allowed_tools or ["terminal"])
        hermes_bin = shutil.which("hermes") or str(hermes_path / "hermes")
        cmd = [
            hermes_bin,
            "chat",
            "-q",
            task_prompt,
            "--yolo",
            "-Q",
            "-t",
            toolsets,
            "--max-turns",
            str(max_turns),
        ]
        proc = subprocess.Popen(
            cmd,
            cwd=str(worktree),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=0,
        )
        return proc

    if os.environ.get("HERMESBENCH_ALLOW_FAKE_RUNNER") != "1":
        raise RuntimeError(
            "Legacy fake_hermes runner is disabled. Use: hermesbench run "
            "(real Hermes Agent). For tests, set HERMESBENCH_ALLOW_FAKE_RUNNER=1."
        )
    fake_script = FAKE_HERMES_TEST_PATH
    if not fake_script.is_file():
        legacy_fake = SCRIPTS / "fake_hermes.py"
        if legacy_fake.is_file():
            fake_script = legacy_fake
        else:
            raise FileNotFoundError(f"missing test fake agent: {FAKE_HERMES_TEST_PATH}")
    cmd = [
        sys.executable,
        "-u",
        str(fake_script),
        "--print-mode",
        "jsonl",
        "--no-tui",
        "--line-buffered",
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=hermes_path,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=0,
    )
    assert proc.stdin is not None
    proc.stdin.write(task_prompt + "\n")
    proc.stdin.flush()
    return proc


def export_session_trace(
    hermes_path: Path,
    session_id: str | None,
    output_path: Path,
    timeout: int = 10,
) -> bool:
    """Export a hermes-agent session to JSONL for trace analysis."""
    if not session_id:
        return False
    try:
        result = subprocess.run(
            [str(hermes_path / "hermes"), "sessions", "export", session_id],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(hermes_path),
        )
        if result.returncode == 0 and result.stdout.strip():
            output_path.write_text(result.stdout)
            return True
    except Exception:
        pass
    return False


def export_to_trace(export_path: Path, trace_path: Path) -> bool:
    """Convert hermes session export to per-message JSONL.

    Session export is one JSON blob: {"messages": [...], ...}
    Verifiers expect per-message JSONL lines.

    Also prefixes tool message content with [tool_name] so the existing
    trace.py _normalize() can reconstruct tool names.
    """
    import json

    data = json.loads(export_path.read_text())
    messages = data.get("messages", [])

    # Build tool_call_id to tool_name mapping
    tc_name_map: dict[str, str] = {}
    for msg in messages:
        for tc in msg.get("tool_calls") or []:
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
