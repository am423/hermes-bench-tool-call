"""Q3: lint verifiers — stdlib-only allowlist via AST walk.

Rejects verifiers that import anything outside the allowlist,
including dynamic imports via `importlib.import_module` or
`__import__` (G8.2).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Q5: stdlib allowlist. Anything outside this set fails the lint.
STDLIB_ALLOWLIST: set[str] = {
    "os",
    "sys",
    "json",
    "re",
    "pathlib",
    "hashlib",
    "csv",
    "subprocess",
    "tempfile",
    "textwrap",
    "datetime",
    "collections",
    "math",
    "itertools",
    "statistics",
    "difflib",
    "xml.etree",
    "typing",
    "dataclasses",
    "ast",
    "__future__",
}


def _collect_imports(tree: ast.AST) -> set[str]:
    """Walk an AST and return the set of top-level import names.

    Handles:
    - `import x` -> {"x"}
    - `import x.y` -> {"x"}
    - `from x import y` -> {"x"}
    - `importlib.import_module("foo")` -> {"foo"}  (G8.2)
    - `__import__("foo")` -> {"foo"}                (G8.2)
    """
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None and node.level == 0:
                imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            # Dynamic imports via importlib.import_module or __import__
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "import_module"
                and isinstance(func.value, ast.Name)
                and func.value.id == "importlib"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ) or (
                isinstance(func, ast.Name)
                and func.id == "__import__"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                imports.add(str(node.args[0].value).split(".")[0])
    return imports


def _iter_verifier_files() -> list[Path]:
    files: list[Path] = []
    for p in (REPO / "tasks").rglob("verifier.py"):
        files.append(p)
    for p in (REPO / "hermesbench").rglob("verifier*.py"):
        files.append(p)
    return files


def test_verifier_files_use_stdlib_only() -> None:
    """Every verifier in the repo must use only stdlib imports."""
    bad: list[tuple[Path, str]] = []
    for f in _iter_verifier_files():
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError as e:
            bad.append((f, f"syntax error: {e}"))
            continue
        for name in _collect_imports(tree):
            if name not in STDLIB_ALLOWLIST:
                bad.append((f, f"imports {name!r}"))
    assert not bad, "verifier(s) use non-allowlisted imports:\n" + "\n".join(
        f"  {p.relative_to(REPO)}: {why}" for p, why in bad
    )


def test_template_verifier_passes_lint() -> None:
    """The _template/verifier.py is the reference; it must lint clean."""
    template = REPO / "tasks" / "_template" / "verifier.py"
    assert template.exists(), "template verifier missing"
    tree = ast.parse(template.read_text())
    imports = _collect_imports(tree)
    # Template uses __future__ + dataclasses + typing + pathlib — all allowed
    assert imports <= STDLIB_ALLOWLIST, (
        f"template uses non-allowlisted: {imports - STDLIB_ALLOWLIST}"
    )


def test_no_verifier_imports_hermesbench() -> None:
    """Verifiers must be hermesbench-free (portable)."""
    for f in _iter_verifier_files():
        text = f.read_text()
        # Q5: verifiers can't import hermesbench because they must be
        # hermesbench-free (portable + hermetically testable). But
        # they CAN mention "hermesbench" in strings (e.g. a prompt
        # they check for). So we look at actual import statements.
        for line in text.splitlines():
            stripped = line.strip()
            if not (stripped.startswith("import ") or stripped.startswith("from ")):
                continue
            # Allow: from __future__ import annotations
            if "__future__" in stripped:
                continue
            # Anything else from `hermesbench` is a fail
            if "hermesbench" in stripped:
                pytest.fail(
                    f"{f.relative_to(REPO)}: verifiers must not import hermesbench: {stripped!r}"
                )
