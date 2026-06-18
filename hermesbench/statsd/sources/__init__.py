"""System statistics source modules.

Each module reads a single class of telemetry (CPU, GPU, RAM, NVMe,
host power, process tree) and returns a dict.
"""

from __future__ import annotations
