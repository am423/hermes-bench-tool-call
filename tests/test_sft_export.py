"""Tests for SFT export with loss masks."""

import json
import tempfile
from pathlib import Path

from hermesbench.sft_export import export_sft


def test_export_with_loss_masks():
    with tempfile.TemporaryDirectory() as tmp:
        trace_dir = Path(tmp) / "run_001" / "t01_terminal_smoke" / "t01_echo"
        trace_dir.mkdir(parents=True)
        trace_file = trace_dir / "trace.jsonl"
        messages = [
            {"role": "system", "content": "You are a helpful agent."},
            {"role": "user", "content": "Run echo hello"},
            {"role": "assistant", "content": "I'll run that for you."},
            {"role": "tool", "content": "hello"},
            {"role": "assistant", "content": "The output is: hello"},
        ]
        with open(trace_file, "w") as f:
            for m in messages:
                f.write(json.dumps(m) + "\n")

        out_file = str(Path(tmp) / "output.jsonl")
        count = export_sft([str(Path(tmp) / "run_001")], out_file)
        assert count == 1
        with open(out_file) as f:
            data = json.loads(f.readline())
        assert len(data["messages"]) == 5
        assert data["loss_mask"] == [0, 0, 1, 0, 1]
