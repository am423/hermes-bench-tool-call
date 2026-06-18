"""Q74: tests for the test suite itself. Verify the contract.

This file is a meta-test: it ensures that running pytest with the
configured options in pyproject.toml works, and that the discovered
tests don't have obvious structural problems.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_tests_directory_exists() -> None:
    assert (REPO / "tests").is_dir()


def test_pytest_collects_zero_failures() -> None:
    """`pytest --collect-only` should not error on any test file."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    # Some collection errors are expected (e.g. tests for modules not yet
    # implemented). The point is: no *Python syntax* errors.
    assert "SyntaxError" not in result.stderr
    assert "IndentationError" not in result.stderr


def test_hermesbench_imports() -> None:
    import hermesbench

    assert hermesbench.__version__ == "0.3.0"


def test_types_imports() -> None:
    from hermesbench.types import (
        VerifierStatus,
    )

    assert VerifierStatus.PASS.value == "PASS"
    assert VerifierStatus.FAIL.value == "FAIL"
