"""Compare two eval runs and generate a regression report."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()


def load_run(path: str) -> dict:
    """Load a results.json file."""
    p = Path(path)
    if p.is_dir():
        p = p / "results.json"
    with open(p) as f:
        return json.load(f)


def compare(baseline_path: str, current_path: str):
    """Compare two eval runs side by side."""
    baseline = load_run(baseline_path)
    current = load_run(current_path)

    b_tasks = {t["name"]: t for t in baseline["tasks"]}
    c_tasks = {t["name"]: t for t in current["tasks"]}

    all_names = list(dict.fromkeys(
        [t["name"] for t in baseline["tasks"]]
        + [t["name"] for t in current["tasks"]]
    ))

    table = Table(title="Eval Comparison")
    table.add_column("Task", style="bold")
    table.add_column("Baseline")
    table.add_column("Current")
    table.add_column("Delta")

    regressions = []
    improvements = []

    for name in all_names:
        b = b_tasks.get(name)
        c = c_tasks.get(name)

        if b and c:
            b_status = "[green]PASS[/]" if b["passed"] else "[red]FAIL[/]"
            c_status = "[green]PASS[/]" if c["passed"] else "[red]FAIL[/]"

            if b["passed"] and not c["passed"]:
                delta = "[red]REGRESSION[/]"
                regressions.append(name)
            elif not b["passed"] and c["passed"]:
                delta = "[green]FIXED[/]"
                improvements.append(name)
            else:
                delta = "—"

            table.add_row(name, b_status, c_status, delta)
        elif b and not c:
            b_status = "[green]PASS[/]" if b["passed"] else "[red]FAIL[/]"
            table.add_row(name, b_status, "[dim]skipped[/]", "—")
        elif c and not b:
            c_status = "[green]PASS[/]" if c["passed"] else "[red]FAIL[/]"
            table.add_row(name, "[dim]new[/]", c_status, "[cyan]NEW[/]")

    console.print()
    console.print(table)

    # Summary
    b_rate = baseline.get("pass_rate", 0)
    c_rate = current.get("pass_rate", 0)
    delta_rate = c_rate - b_rate

    console.print(f"\n[bold]Pass rate:[/] {b_rate:.0%} → {c_rate:.0%}  ({delta_rate:+.0%})")
    console.print(f"[bold]Model:[/] {baseline.get('model', '?')} → {current.get('model', '?')}")

    b_time = baseline.get("total_duration_s", 0)
    c_time = current.get("total_duration_s", 0)
    console.print(f"[bold]Time:[/] {b_time:.0f}s → {c_time:.0f}s")

    if regressions:
        console.print(f"\n[red bold]Regressions ({len(regressions)}):[/]")
        for r in regressions:
            console.print(f"  [red]✗[/] {r}")

    if improvements:
        console.print(f"\n[green bold]Improvements ({len(improvements)}):[/]")
        for r in improvements:
            console.print(f"  [green]✓[/] {r}")

    if not regressions and delta_rate >= 0:
        console.print("\n[green bold]No regressions detected.[/]")

    console.print()
