"""Q74: tests that every shipped task has a valid verifier.

Covers: verifier contract (Q35), VerifierResult type, stdlib allowlist.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from hermesbench.types import VerifierStatus

REPO = Path(__file__).resolve().parent.parent


def _discover_task_dirs() -> list[Path]:
    out: list[Path] = []
    for p in (REPO / "tasks").rglob("task.yaml"):
        if "_template" in p.parts:
            continue
        out.append(p.parent)
    return out


def test_every_task_has_a_verifier() -> None:
    """If task.yaml exists, verifier.py must exist too."""
    missing: list[Path] = []
    for td in _discover_task_dirs():
        if not (td / "verifier.py").exists():
            missing.append(td)
    assert not missing, f"task(s) missing verifier.py: {missing}"


def test_every_verifier_returns_verifierresult() -> None:
    """A verifier that returns the wrong type should fail this test."""
    import sys

    for td in _discover_task_dirs():
        vp = td / "verifier.py"
        if not vp.exists():
            continue
        # Register the module in sys.modules before exec — needed in
        # Python 3.14+ for dataclass + from __future__ import annotations
        # + dynamic import. Without this, dataclass introspection
        # fails with "'NoneType' object has no attribute '__dict__'".
        mod_name = f"hermesbench_test_{td.name.replace('/', '_').replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(mod_name, vp)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules[mod_name] = mod
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(mod)
        assert hasattr(mod, "verify"), f"{vp}: no verify() function"
        # Call with a tmp worktree to make sure it returns VerifierResult
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            from pathlib import Path

            try:
                result = mod.verify(Path(d), [])
            except Exception as e:
                pytest.fail(f"{vp}: verify() raised: {e}")
            # Each verifier defines its own VerifierResult class (Q5:
            # stdlib-only, so they don't import ours). Use duck-typing.
            assert hasattr(result, "status"), f"{vp}: result has no .status attr"
            assert hasattr(result, "score"), f"{vp}: result has no .score attr"
            assert hasattr(result, "reason"), f"{vp}: result has no .reason attr"
            assert hasattr(result, "details"), f"{vp}: result has no .details attr"
            assert 0.0 <= result.score <= 1.0, f"{vp}: score {result.score} not in [0, 1]"


def test_template_verifier_passes_contract() -> None:
    """The _template/verifier.py is the reference; must work with tmp worktree."""
    import sys

    template = REPO / "tasks" / "_template" / "verifier.py"
    mod_name = "hermesbench_test_template_verifier"
    spec = importlib.util.spec_from_file_location(mod_name, template)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[mod_name] = mod
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(mod)
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        result = mod.verify(Path(d), [])
        # The verifier defines its own VerifierResult class (Q5:
        # stdlib-only), so we check duck-typing not identity.
        assert hasattr(result, "status") and hasattr(result, "score")
        assert hasattr(result, "reason") and hasattr(result, "details")
        # The template expects a file to exist; tmp dir is empty so it FAILS.
        # That's fine — the contract is just "returns a VerifierResult-like."
        status_val = result.status.value if hasattr(result.status, "value") else result.status
        assert status_val in {s.value for s in VerifierStatus}
