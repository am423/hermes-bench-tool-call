"""Q-test: pinning finds a quiet core and lowers priority."""

from __future__ import annotations

from hermesbench.statsd import pinning


def test_lower_priority_doesnt_crash() -> None:
    # Just run it; we're already IDLE because pytest doesn't bump us
    pinning.lower_priority()


def test_find_quiet_core_returns_int_or_none() -> None:
    core = pinning.find_quiet_core()
    import os

    if os.name == "posix":
        # On Linux/macOS we should get either an int or None
        assert core is None or isinstance(core, int)
    else:
        assert core is None
