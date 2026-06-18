"""Core type definitions shared across hermesbench."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

# ----------------------------------------------------------------------------
# Q35: VerifierResult contract
# ----------------------------------------------------------------------------


class VerifierStatus(StrEnum):
    """All possible verifier outcomes."""

    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    VERIFIER_ERROR = "VERIFIER_ERROR"


@dataclass
class VerifierResult:
    """The contract every verifier must return.

    See Q35 / G8.2 of project.md.
    """

    status: VerifierStatus
    score: float = 1.0  # 1.0 PASS, 0.0 FAIL, fractional for partial credit
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------------
# Q20: TaskSpec — full schema of task.yaml
# ----------------------------------------------------------------------------


@dataclass
class SamplingConfig:
    temperature: float = 0.0
    top_p: float = 1.0
    top_k: int = -1
    seed: int = 42


@dataclass
class ResourceLimits:
    max_memory_mb: int = 4096
    max_processes: int = 256
    max_file_size_mb: int = 1024
    max_worktree_mb: int = 2048


@dataclass
class LatencyInjection:
    terminal: int = 0
    read_file: int = 0
    write_file: int = 0
    patch: int = 0
    search_files: int = 0
    execute_code: int = 0
    process: int = 0
    todo: int = 0


@dataclass
class ModelEndpoint:
    type: str = "openai_chat_completions"
    required_fields: list[str] = field(default_factory=lambda: ["tools", "tool_choice"])
    forbidden_fields: list[str] = field(default_factory=lambda: ["logprobs"])


@dataclass
class FixtureSpec:
    source: str = "small_repo"
    globs: list[str] = field(default_factory=lambda: ["**/*"])


@dataclass
class VerifierSpec:
    module: str = "verifier"
    fn: str = "verify"
    timeout_seconds: int = 30


@dataclass
class TaskSpec:
    """The full task.yaml schema. See Q20 of project.md."""

    id: str
    name: str
    version: int
    prompt: str
    difficulty: Literal[1, 2, 3]
    tags: list[str]
    allowed_tools: list[str]
    forbidden_tools: list[str]
    max_turns: int
    max_tokens: int
    timeout_seconds: int
    isolated_network: bool
    fixture: FixtureSpec
    sampling: SamplingConfig
    resource_limits: ResourceLimits
    hermes_plugins: list[str]
    latency_injection_ms: LatencyInjection
    model_endpoint: ModelEndpoint
    verifier: VerifierSpec
    worktree: Path | None = None  # resolved by the runner, not from yaml

    @classmethod
    def from_yaml(cls, path: Path) -> TaskSpec:
        import yaml

        with path.open() as f:
            data = yaml.safe_load(f)

        # Use dict.get with defaults — schema version 1.
        return cls(
            id=data["id"],
            name=data["name"],
            version=data.get("version", 1),
            prompt=data["prompt"].strip(),
            difficulty=data.get("difficulty", 2),
            tags=data.get("tags", []),
            allowed_tools=data.get("allowed_tools", []),
            forbidden_tools=data.get("forbidden_tools", []),
            max_turns=data.get("max_turns", 30),
            max_tokens=data.get("max_tokens", 8192),
            timeout_seconds=data.get("timeout_seconds", 180),
            isolated_network=data.get("isolated_network", False),
            fixture=FixtureSpec(**data.get("fixture", {})),
            sampling=SamplingConfig(**data.get("sampling", {})),
            resource_limits=ResourceLimits(**data.get("resource_limits", {})),
            hermes_plugins=data.get("hermes_plugins", []),
            latency_injection_ms=LatencyInjection(**data.get("latency_injection_ms", {})),
            model_endpoint=ModelEndpoint(**data.get("model_endpoint", {})),
            verifier=VerifierSpec(**data.get("verifier", {})),
        )


# ----------------------------------------------------------------------------
# Q21 / Q24: RunId, TaskResult, RunMeta
# ----------------------------------------------------------------------------


@dataclass
class RunId:
    """The canonical run_id format (Q21).

    <model_slug>_<YYYYMMDD-HHMMSS>_<8char-uuid>
    """

    model_slug: str
    timestamp: datetime
    nonce: str  # 8 chars

    def __str__(self) -> str:
        return f"{self.model_slug}_{self.timestamp.strftime('%Y%m%d-%H%M%S')}_{self.nonce}"


@dataclass
class RunMeta:
    """What gets written to results/<run_id>/meta.json.

    See Q50 (hermes SHA pin), Q55 (worktree path), Q62 (warnings).
    """

    run_id: str
    model: str
    model_slug: str
    hermes_sha: str
    hermes_path: str
    hermes_agent_version: str
    hermesbench_version: str
    started_at: float
    finished_at: float | None
    status: Literal["running", "completed", "crashed", "timeout", "resumed"]
    exit_code: int
    python_version: str
    platform: str
    hostname: str
    warnings: list[str] = field(default_factory=list)
    env_overrides: dict[str, str] = field(default_factory=dict)
    worktree_root: str = ""
    worktree_strategy: str = "persistent"  # vs ephemeral
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0


@dataclass
class TaskResult:
    """A single task's outcome."""

    task_id: str
    run_id: str
    worktree: Path
    trace_path: Path
    cast_path: Path
    stats_path: Path
    meta_path: Path
    verifier_result: VerifierResult
    started_at: float
    finished_at: float
    token_count_input: int = 0
    token_count_output: int = 0
    tool_call_count: int = 0
    n_turns: int = 0
    parallel_tool_call_rate: float = 0.0
    recovery_attempts: int = 0
    recovery_succeeded: int = 0
    error: str | None = None


# ----------------------------------------------------------------------------
# Q44 / Q5x: Hardware metrics
# ----------------------------------------------------------------------------


@dataclass
class HardwareMetrics:
    """Per-task hardware summary (Q44, Q51, Q63)."""

    mean_gpu_power_w: float | None = None
    peak_gpu_power_w: float | None = None
    mean_gpu_temp_c: float | None = None
    peak_gpu_temp_c: float | None = None
    mean_cpu_power_w: float | None = None
    mean_cpu_temp_c: float | None = None
    mean_host_power_w: float | None = None
    throttled_seconds: float = 0.0
    temp_auc_above_85c_seconds: float = 0.0
    gen_joules_per_output_token: float | None = None
    wall_joules_per_output_token: float | None = None
    tok_per_watt: float | None = None
    mean_model_cpu_cores: float = 0.0
    nvme_temp_c: float | None = None
    ram_used_mib: float | None = None

    def thermal_warning(self) -> str | None:
        """Q19: thermal warning heuristic. Advisory only (Q19)."""
        if self.peak_gpu_temp_c is not None and self.peak_gpu_temp_c > 90.0:
            return f"peak_gpu_temp_c={self.peak_gpu_temp_c:.1f} > 90°C"
        if self.throttled_seconds > 5.0:
            return f"throttled_seconds={self.throttled_seconds:.1f} > 5s"
        return None
