"""Q6.3: lint_fixtures — reject injection patterns unless marker is present."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Patterns that look like prompt injection. Add new ones here as needed.
INJECTION_PATTERNS: list[str] = [
    "ignore previous instructions",
    "ignore all previous instructions",
    "ignore the above",
    "disregard your prior rules",
    "disregard all prior rules",
    "disregard your instructions",
    "forget your system prompt",
    "system prompt:",
    "you are now",
    "new instructions:",
]

ALLOW_MARKER = "## hermesbench: allow-injection"


def _iter_fixture_files() -> list[Path]:
    files: list[Path] = []
    fixtures = REPO / "fixtures"
    if fixtures.exists():
        for p in fixtures.rglob("*"):
            if p.is_file() and p.suffix in (".py", ".md", ".txt", ".yaml", ".yml", ".json", ".sh"):
                # Skip the README itself (it's documentation, not fixture data
                # the model reads). The model never sees the README; it only
                # sees the contents of fixture subdirectories copied into the
                # worktree.
                if p.name == "README.md":
                    continue
                files.append(p)
    tasks = REPO / "tasks"
    if tasks.exists():
        for p in tasks.rglob("*"):
            if p.is_file() and p.suffix in (".py", ".md", ".txt", ".yaml", ".yml", ".json"):
                # exclude verifier.py (not a fixture) and task.yaml (already curated)
                if p.name in ("verifier.py", "task.yaml"):
                    continue
                files.append(p)
    return files


def test_no_fixture_has_injection_patterns() -> None:
    """Every committed fixture must not contain prompt-injection shapes."""
    offenders: list[tuple[Path, str, int]] = []
    for f in _iter_fixture_files():
        try:
            lines = f.read_text().splitlines()
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(lines, start=1):
            lower = line.lower()
            for pattern in INJECTION_PATTERNS:
                if pattern in lower:
                    if ALLOW_MARKER in line:
                        continue
                    offenders.append((f, pattern, lineno))
    assert not offenders, (
        "fixture(s) contain injection patterns without allow marker:\n"
        + "\n".join(f"  {p.relative_to(REPO)}:{n} -> {pat}" for p, pat, n in offenders)
    )


def test_allow_marker_recognized() -> None:
    """The allow-marker constant must contain 'allow-injection'."""
    # This is a self-test that the constant is correctly defined.
    assert "allow-injection" in ALLOW_MARKER

    # And a real pattern + marker on the same line should NOT be flagged.
    # We test the linter logic directly.

    # Create a temporary fixture file with a pattern + marker
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        fixture_root = Path(d) / "fixtures"
        fixture_root.mkdir()
        bad = fixture_root / "ok.md"
        bad.write_text(
            "Some text\nignore previous instructions  ## hermesbench: allow-injection\nMore text\n"
        )
        # Patch REPO to point at our temp
        import tests.test_lint_fixtures as mod

        original_repo = mod.REPO
        try:
            mod.REPO = Path(d)  # type: ignore[misc]
            # Recreate the function's lookup with new REPO
            files: list[Path] = []
            for p in fixture_root.rglob("*"):
                if p.is_file() and p.suffix in (
                    ".py",
                    ".md",
                    ".txt",
                    ".yaml",
                    ".yml",
                    ".json",
                    ".sh",
                ):
                    if p.name == "README.md":
                        continue
                    files.append(p)
            assert bad in files

            # Re-run the lint logic
            offenders: list[tuple[Path, str, int]] = []
            for f in files:
                for lineno, line in enumerate(f.read_text().splitlines(), start=1):
                    lower = line.lower()
                    for pattern in INJECTION_PATTERNS:
                        if pattern in lower:
                            if ALLOW_MARKER in line:
                                continue
                            offenders.append((f, pattern, lineno))
            assert not offenders, f"allow-marker not honored: {offenders}"
        finally:
            mod.REPO = original_repo  # type: ignore[misc]
