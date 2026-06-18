"""Q3: lint_fixture_sizes — every fixture <= 100 KB raw."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MAX_FIXTURE_BYTES = 100 * 1024  # 100 KB


def _iter_fixture_files() -> list[Path]:
    files: list[Path] = []
    for sub in (REPO / "fixtures", REPO / "tasks"):
        if not sub.exists():
            continue
        for p in sub.rglob("*"):
            if p.is_file() and p.suffix not in (".pyc",):
                # exclude test files and task.yaml/verifier.py (not fixtures)
                if p.name in ("verifier.py", "task.yaml"):
                    continue
                if ".venv" in p.parts or "node_modules" in p.parts:
                    continue
                files.append(p)
    return files


def test_all_fixtures_under_size_cap() -> None:
    offenders: list[tuple[Path, int]] = []
    for f in _iter_fixture_files():
        try:
            size = f.stat().st_size
        except OSError:
            continue
        if size > MAX_FIXTURE_BYTES:
            offenders.append((f, size))
    assert not offenders, "fixture(s) exceed 100 KB:\n" + "\n".join(
        f"  {p.relative_to(REPO)}: {s} bytes" for p, s in offenders
    )
