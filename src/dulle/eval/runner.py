"""Eval runner — loads tasks, runs the agent, checks results."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import yaml
from loguru import logger
from rich.console import Console
from rich.table import Table

from dulle.config import Settings
from dulle.eval.checks import CheckResult, run_check

console = Console()


@dataclass
class TaskResult:
    """Result of a single eval task."""
    name: str
    command: str
    difficulty: str
    passed: bool
    checks: list[dict] = field(default_factory=list)
    duration_s: float = 0.0
    agent_completed: bool = False
    error: str = ""


@dataclass
class EvalRun:
    """Full eval run across all tasks."""
    timestamp: str
    model: str
    tasks: list[TaskResult] = field(default_factory=list)
    total_duration_s: float = 0.0

    @property
    def pass_rate(self) -> float:
        if not self.tasks:
            return 0.0
        return sum(1 for t in self.tasks if t.passed) / len(self.tasks)

    def summary_by_difficulty(self) -> dict[str, dict]:
        buckets: dict[str, list[bool]] = {}
        for t in self.tasks:
            buckets.setdefault(t.difficulty, []).append(t.passed)
        return {
            d: {"total": len(v), "passed": sum(v), "rate": sum(v) / len(v)}
            for d, v in buckets.items()
        }


def load_tasks(path: str = "eval_tasks.yaml") -> list[dict]:
    with open(path) as f:
        return yaml.safe_load(f)


def _run_cleanup(commands: list[str]):
    for cmd in commands:
        try:
            subprocess.run(
                ["cmd", "/c", cmd],
                capture_output=True, timeout=10,
            )
        except Exception:
            pass


def run_eval(
    settings: Settings,
    task_file: str = "eval_tasks.yaml",
    task_filter: str | None = None,
    output_dir: str = "eval/results",
) -> EvalRun:
    """Run the full eval suite and return results."""
    from dulle.agent import DullEAgent

    tasks = load_tasks(task_file)
    if task_filter:
        filters = [f.strip() for f in task_filter.split(",")]
        tasks = [t for t in tasks if t["name"] in filters]

    if not tasks:
        console.print("[red]No tasks to run.[/]")
        return EvalRun(timestamp="", model=settings.executor_model)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run = EvalRun(timestamp=timestamp, model=settings.executor_model)

    console.print(f"\n[bold cyan]Running {len(tasks)} eval tasks[/]\n")
    run_start = time.time()

    for i, task in enumerate(tasks, 1):
        name = task["name"]
        command = task["command"]
        difficulty = task.get("difficulty", "unknown")
        timeout = task.get("timeout", 120)

        console.print(f"[bold]({i}/{len(tasks)}) {name}[/] — {command}")

        # Cleanup before test
        _run_cleanup(task.get("cleanup", []))
        time.sleep(1)

        # Run the agent
        task_start = time.time()
        agent_completed = False
        error = ""
        try:
            agent = DullEAgent(settings)
            result = agent.run(command)
            agent_completed = result.completed
        except KeyboardInterrupt:
            console.print("[yellow]  Interrupted — skipping remaining tasks[/]")
            break
        except Exception as exc:
            error = str(exc)
            logger.exception(f"Eval task {name} crashed")

        duration = time.time() - task_start

        # Wait a moment for any pending UI state to settle
        time.sleep(2)

        # Run checks
        check_results: list[CheckResult] = []
        for check_def in task.get("checks", []):
            cr = run_check(check_def, settings)
            check_results.append(cr)

        all_passed = all(cr.passed for cr in check_results) and not error
        status = "[green]PASS[/]" if all_passed else "[red]FAIL[/]"
        console.print(f"  {status}  ({duration:.1f}s, {len(check_results)} checks)")

        for cr in check_results:
            mark = "[green]✓[/]" if cr.passed else "[red]✗[/]"
            console.print(f"    {mark} {cr.check_type}: {cr.expected}")

        task_result = TaskResult(
            name=name,
            command=command,
            difficulty=difficulty,
            passed=all_passed,
            checks=[
                {
                    "type": cr.check_type,
                    "passed": cr.passed,
                    "expected": cr.expected,
                    "actual": cr.actual,
                    "detail": cr.detail,
                }
                for cr in check_results
            ],
            duration_s=duration,
            agent_completed=agent_completed,
            error=error,
        )
        run.tasks.append(task_result)

        # Cleanup after test
        _run_cleanup(task.get("cleanup", []))

    run.total_duration_s = time.time() - run_start

    # Save results
    out_path = Path(output_dir) / timestamp
    out_path.mkdir(parents=True, exist_ok=True)
    results_file = out_path / "results.json"

    with open(results_file, "w") as f:
        json.dump(
            {
                "timestamp": run.timestamp,
                "model": run.model,
                "pass_rate": run.pass_rate,
                "total_duration_s": run.total_duration_s,
                "summary_by_difficulty": run.summary_by_difficulty(),
                "tasks": [asdict(t) for t in run.tasks],
            },
            f,
            indent=2,
        )

    console.print(f"\n[dim]Results saved to {results_file}[/]")
    _print_summary(run)

    return run


def _print_summary(run: EvalRun):
    table = Table(title=f"Eval Results — {run.timestamp}")
    table.add_column("Task", style="bold")
    table.add_column("Difficulty")
    table.add_column("Result")
    table.add_column("Time")
    table.add_column("Checks")

    for t in run.tasks:
        passed = f"{sum(1 for c in t.checks if c['passed'])}/{len(t.checks)}"
        table.add_row(
            t.name,
            t.difficulty,
            "[green]PASS[/]" if t.passed else "[red]FAIL[/]",
            f"{t.duration_s:.1f}s",
            passed,
        )

    console.print()
    console.print(table)

    by_diff = run.summary_by_difficulty()
    parts = [f"{d}: {v['passed']}/{v['total']}" for d, v in by_diff.items()]
    console.print(f"\n[bold]Overall: {run.pass_rate:.0%}[/]  ({', '.join(parts)})")
    console.print(f"Total time: {run.total_duration_s:.0f}s\n")
