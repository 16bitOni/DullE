"""DullEAgent — orchestrates the plan-execute-verify cycle.

Phase 1: Planner decomposes the command into steps.
Phase 2: Each step runs via execute_step (CLI-first, GUI fallback).
Phase 3: Summary printed and audit manifest saved.
"""

from __future__ import annotations

from datetime import datetime

from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from dulle.agent.steps import execute_step
from dulle.agent.audit import AuditTrail
from dulle.config import Settings
from dulle.execution.actions import ActionExecutor
from dulle.execution.screen import ScreenCapture
from dulle.llm.client import LLMClient
from dulle.models import Step, StepStatus, TaskResult
from dulle.planning.knowledge import KnowledgeBase
from dulle.planning.planner import describe_screen, plan_task

console = Console()


class DullEAgent:
    """Main agent: wires together planning, execution, and verification."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.screen = ScreenCapture(self.settings)
        self.llm = LLMClient(self.settings)
        self.executor = ActionExecutor(self.screen, self.settings)
        self.knowledge = KnowledgeBase(self.settings.knowledge_file)

    def run(self, user_command: str) -> TaskResult:
        """Execute a full user command end-to-end."""
        task = TaskResult(command=user_command)
        audit = AuditTrail(
            self.settings.audit_trail_dir, user_command,
            enabled=self.settings.enable_audit_trail,
        )

        console.print(Panel(
            f"[bold cyan]{user_command}[/]",
            title="DullE Task", border_style="cyan",
        ))
        console.print("[dim]Press Ctrl+C at any time to abort the task.[/]\n")

        # ── Phase 1: Plan ────────────────────────────────────────
        console.print("\n[bold yellow]Phase 1:[/] Planning steps...\n")

        knowledge_text = ""
        relevant_knowledge = self.knowledge.retrieve(user_command)
        if relevant_knowledge:
            knowledge_text = self.knowledge.format_for_prompt(relevant_knowledge)
            console.print(f"  [dim]Knowledge: {len(relevant_knowledge)} relevant entries loaded[/]")

        screen_desc = None
        try:
            console.print("  [dim]Scanning current screen...[/]")
            initial_screenshot = self.screen.capture()
            audit.save_screenshot(initial_screenshot, step=0, iteration=0,
                                  label="pre_plan", fmt=self.settings.screenshot_format)
            screen_desc = describe_screen(self.llm, initial_screenshot)
            if screen_desc:
                console.print(f"  [dim]Screen: {screen_desc[:120]}[/]")
        except Exception as exc:
            console.print(f"  [yellow]Screen scan failed (non-fatal):[/] {exc}")
            logger.warning(f"Screen description failed (non-fatal): {exc}")

        try:
            console.print("  [dim]Generating plan...[/]")
            steps = plan_task(
                user_command, self.llm,
                self.screen.info, self.settings,
                screen_description=screen_desc,
                knowledge_text=knowledge_text,
            )
        except Exception as exc:
            console.print(f"[red]Planning failed:[/] {exc}")
            task.completed = False
            task.ended_at = datetime.now()
            return task

        task.steps = steps
        self._print_plan(steps)
        audit.save_plan([
            {"step": s.index, "description": s.description,
             "action_type": s.action_type.value, "cli_command": s.cli_command}
            for s in steps
        ])

        # ── Phase 2: Execute each step ───────────────────────────
        console.print("\n[bold yellow]Phase 2:[/] Executing steps...\n")
        for step in steps:
            console.rule(f"Step {step.index}: {step.description}")

            # Ask user before executing if the planner flagged ambiguity
            if step.needs_input:
                answer = Prompt.ask(
                    f"\n  [bold yellow]Question before step {step.index}:[/] {step.needs_input}"
                )
                step.description = f"{step.description} [User provided: {answer}]"
                console.print(f"  [dim]Got: {answer}[/]\n")

            step.started_at = datetime.now()
            step.status = StepStatus.RUNNING

            success = execute_step(step, audit, self.llm, self.screen, self.executor,
                                   self.settings, knowledge_text, self._confirm)

            step.ended_at = datetime.now()
            step.status = StepStatus.SUCCESS if success else StepStatus.FAILED

            status_icon = "[green]OK[/]" if success else "[red]FAIL[/]"
            console.print(f"  Result: {status_icon} — {step.result or step.error}\n")

            if not success:
                step.retries += 1
                escalated = self.llm.escalate_executor()
                if escalated:
                    console.print(
                        f"  [yellow]Retrying with stronger model "
                        f"({self.settings.executor_model_heavy})...[/]"
                    )
                else:
                    console.print("  [yellow]Retrying...[/]")
                success = execute_step(step, audit, self.llm, self.screen, self.executor,
                                       self.settings, knowledge_text, self._confirm)
                self.llm.reset_executor()
                step.status = StepStatus.SUCCESS if success else StepStatus.FAILED
                if not success:
                    console.print(f"  [red]Step failed after retry.[/] Stopping.\n")
                    break

        # ── Phase 3: Summary ─────────────────────────────────────
        task.completed = all(s.status == StepStatus.SUCCESS for s in steps)
        task.ended_at = datetime.now()
        task.token_usage = self.llm.usage.summary()
        self._print_summary(task)

        audit.save_manifest({
            "command": task.command,
            "completed": task.completed,
            "duration_s": task.duration_s,
            "token_usage": task.token_usage,
            "steps": [
                {"index": s.index, "description": s.description,
                 "status": s.status.value, "result": s.result, "error": s.error}
                for s in task.steps
            ],
        })
        return task

    def _confirm(self, command: str, reason: str) -> bool:
        """Ask the user for confirmation before a write operation."""
        console.print(f"\n  [yellow bold]Confirmation needed:[/]")
        console.print(f"  Command: [cyan]{command}[/]")
        console.print(f"  Reason:  {reason}")
        answer = console.input("  Allow? [y/N] ").strip().lower()
        return answer in ("y", "yes")

    def _print_plan(self, steps: list[Step]):
        table = Table(title="Execution Plan", show_lines=True)
        table.add_column("#", style="bold", width=3)
        table.add_column("Step", min_width=40)
        table.add_column("Type", width=8)
        table.add_column("CLI Hint", style="dim")
        for s in steps:
            table.add_row(
                str(s.index),
                s.description,
                s.action_type.value,
                s.cli_command or "—",
            )
        console.print(table)

    def _print_summary(self, task: TaskResult):
        total = len(task.steps)
        ok = sum(1 for s in task.steps if s.status == StepStatus.SUCCESS)
        failed = sum(1 for s in task.steps if s.status == StepStatus.FAILED)

        panel_style = "green" if task.completed else "red"
        status = "COMPLETED" if task.completed else "INCOMPLETE"

        usage = task.token_usage
        token_line = ""
        if usage and usage.get("total_tokens", 0) > 0:
            token_line = (
                f"\nTokens:    {usage['total_tokens']:,} "
                f"({usage['prompt_tokens']:,} in / "
                f"{usage['completion_tokens']:,} out) "
                f"across {usage['call_count']} calls"
            )

        console.print()
        console.print(Panel(
            "\n".join([
                f"Status:    [bold]{status}[/]",
                f"Steps:     {ok}/{total} succeeded, {failed} failed",
                f"Duration:  {task.duration_s:.1f}s{token_line}",
            ]),
            title="Task Summary",
            border_style=panel_style,
        ))
