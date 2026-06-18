"""hermesbench.statsd: 5 Hz system statistics collector.

Q15, Q17, Q41, Q44, Q62, Q63. See project.md §3.1b.

Spawned as a separate subprocess by the runner; auto-niced,
ionice-IDLE, and pinned to a quiet CPU core so the model's
runtime isn't perturbed. Writes a `.stats.jsonl` file with
one line per sample.
"""

from __future__ import annotations
