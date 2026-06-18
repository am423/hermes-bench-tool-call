"""hermesbench/compare.py — compare results across model runs."""

from __future__ import annotations

from pathlib import Path

from rich.table import Table


def compare_runs(results: dict[str, list[dict]]) -> Table:
    """Produce a rich Table comparing pass rates across runs."""
    from hermesbench.scoring import category_breakdown

    table = Table(title="Model Comparison")
    table.add_column("Metric", style="cyan", no_wrap=True)
    for run_path in results:
        label = Path(run_path).name
        table.add_column(label, justify="right")

    row = ["Overall Pass"]
    for _run_path, res in results.items():
        total = len(res)
        passed = sum(1 for r in res if r.get("status") == "PASS")
        rate = f"{passed}/{total} ({passed / total * 100:.0f}%)" if total else "N/A"
        row.append(rate)
    table.add_row(*row)

    all_cats: set[str] = set()
    cat_data: dict[str, dict[str, tuple[int, int]]] = {}
    for run_path, res in results.items():
        cats = category_breakdown(res)
        cat_data[run_path] = cats
        all_cats.update(cats.keys())

    for cat in sorted(all_cats):
        row = [cat]
        for run_path in results:
            p, t = cat_data[run_path].get(cat, (0, 0))
            row.append(f"{p}/{t}" if t else "-")
        table.add_row(*row)

    return table
