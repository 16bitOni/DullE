"""Core agent loop — the brain of DullE.

Orchestrates the plan-execute-verify cycle:
  1. Planner decomposes the user command into steps.
  2. For each step, the executor loop runs:
     a. If CLI step: run the command directly.
     b. If GUI step: multi-turn screenshot conversation with loop detection.
     c. If hybrid: try CLI first, fall back to GUI.
  3. After each step, optionally verify with a screenshot.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from dulle.config import Settings
from dulle.executor import ActionExecutor
from dulle.llm import LLMClient, parse_json_response
from dulle.models import ActionResult, ActionType, Step, StepStatus, TaskResult
from dulle.planner import plan_task
from dulle.prompts import executor_system, verifier_system
from dulle.screen import ScreenCapture
from dulle.shell import run_command

console = Console()

# ── Loop detection ───────────────────────────────────────────────

MAX_SAME_ACTION = 2   # After 2 identical actions in a row, intervene
MAX_SCREENSHOTS_ONLY = 3  # After 3 screenshots with no real action, intervene


def _action_signature(action: dict) -> str:
    """Create a hashable signature for an action to detect repeats."""
    a = action.get("action", "")
    if a in ("click", "left_click", "right_click", "double_click"):
        coord = action.get("coordinate", action.get("coords", []))
        return f"{a}:{coord}"
    if a in ("type", "type_text"):
        return f"type:{action.get('text', '')[:50]}"
    if a in ("key", "hotkey", "press"):
        return f"key:{action.get('keys', action.get('text', ''))}"
    if a == "scroll":
        return f"scroll:{action.get('direction', '')}:{action.get('amount', '')}"
    return a


def _detect_loop(history: list[dict]) -> str | None:
    """Check recent action history for loops. Returns a nudge message or None."""
    if len(history) < 2:
        return None

    # Check for same action repeated
    sigs = [_action_signature(h) for h in history]
    last = sigs[-1]
    repeat_count = 0
    for s in reversed(sigs):
        if s == last:
            repeat_count += 1
        else:
            break

    if repeat_count >= MAX_SAME_ACTION:
        return (
            f"LOOP DETECTED: You have repeated the same action '{last}' "
            f"{repeat_count} times. It is NOT working. You MUST try a completely "
            f"different approach. Consider:\n"
            f"- If you keep clicking the same spot, the cursor may already be there. "
            f"Try typing or pressing a key instead.\n"
            f"- If you keep typing but nothing appears, the text field may not have "
            f"focus. Try clicking a different area first.\n"
            f"- If a click isn't working, try using a keyboard shortcut instead.\n"
            f"- If nothing seems to work, describe what you see and respond with "
            f'{{\"action\": \"done\", \"summary\": \"Unable to complete — [reason]\"}}.'
        )

    # Check for screenshot-only loop (observing but never acting)
    recent = history[-MAX_SCREENSHOTS_ONLY:]
    if len(recent) >= MAX_SCREENSHOTS_ONLY and all(
        h.get("action") == "screenshot" for h in recent
    ):
        return (
            "LOOP DETECTED: You have taken multiple screenshots without performing "
            "any action. Stop observing and ACT. Based on what you see, click a "
            "button, type some text, or press a key. If the task is already done, "
            'respond with {"action": "done"}.'
        )

    return None


# ── Image pruning (keep context window manageable) ───────────────

MAX_IMAGES_IN_HISTORY = 6  # Keep only the last N screenshots in conversation


def _prune_old_images(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove old image blocks from conversation to save tokens.

    Keeps the last MAX_IMAGES_IN_HISTORY images. Older images are replaced
    with a text description so the model knows something was there.
    """
    # Find all user messages with images (count from the end)
    image_positions = []
    for i, msg in enumerate(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "image_url":
                    image_positions.append(i)
                    break

    if len(image_positions) <= MAX_IMAGES_IN_HISTORY:
        return messages  # Nothing to prune

    # Positions to strip (everything except the last N)
    to_strip = set(image_positions[:-MAX_IMAGES_IN_HISTORY])

    pruned = []
    for i, msg in enumerate(messages):
        if i in to_strip:
            # Replace image with a text placeholder
            content = msg.get("content", [])
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block["text"])
            pruned.append({
                "role": "user",
                "content": "[Earlier screenshot removed to save context. "
                           "The text that accompanied it:]\n" + "\n".join(text_parts),
            })
        else:
            pruned.append(msg)

    return pruned


# ── Agent ────────────────────────────────────────────────────────

class DullEAgent:
    """The main agent that ties everything together."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.screen = ScreenCapture(self.settings)
        self.llm = LLMClient(self.settings)
        self.executor = ActionExecutor(self.screen, self.settings)

    def run(self, user_command: str) -> TaskResult:
        """Execute a full user command end-to-end."""
        task = TaskResult(command=user_command)
        console.print(Panel(
            f"[bold cyan]{user_command}[/]",
            title="DullE Task", border_style="cyan",
        ))

        # ── Phase 1: Plan ────────────────────────────────────────
        console.print("\n[bold yellow]Phase 1:[/] Planning steps...\n")
        try:
            steps = plan_task(
                user_command, self.llm,
                self.screen.info, self.settings,
            )
        except Exception as exc:
            console.print(f"[red]Planning failed:[/] {exc}")
            task.completed = False
            task.ended_at = datetime.now()
            return task

        task.steps = steps
        self._print_plan(steps)

        # ── Phase 2: Execute each step ───────────────────────────
        console.print("\n[bold yellow]Phase 2:[/] Executing steps...\n")
        for step in steps:
            console.rule(f"Step {step.index}: {step.description}")
            step.started_at = datetime.now()
            step.status = StepStatus.RUNNING

            success = self._execute_step(step)

            step.ended_at = datetime.now()
            step.status = StepStatus.SUCCESS if success else StepStatus.FAILED

            status_icon = "[green]OK[/]" if success else "[red]FAIL[/]"
            console.print(f"  Result: {status_icon} — {step.result or step.error}\n")

            if not success:
                # Try once more
                console.print("  [yellow]Retrying...[/]")
                step.retries += 1
                success = self._execute_step(step)
                step.status = StepStatus.SUCCESS if success else StepStatus.FAILED
                if not success:
                    console.print(f"  [red]Step failed after retry.[/] Stopping.\n")
                    break

        # ── Phase 3: Summary ─────────────────────────────────────
        task.completed = all(s.status == StepStatus.SUCCESS for s in steps)
        task.ended_at = datetime.now()
        self._print_summary(task)
        return task

    # ── Step execution ───────────────────────────────────────────

    def _execute_step(self, step: Step) -> bool:
        """Execute a single step. Returns True if succeeded."""
        mode = step.action_type

        if mode == ActionType.CLI and step.cli_command:
            return self._execute_cli_step(step)
        elif mode == ActionType.GUI:
            return self._execute_gui_step(step)
        elif mode == ActionType.VERIFY:
            return self._execute_verify_step(step)
        elif mode == ActionType.WAIT:
            time.sleep(2)
            step.result = "Waited."
            return True
        else:
            # Hybrid: try CLI first if there's a hint, then GUI
            if step.cli_command:
                ok = self._execute_cli_step(step)
                if ok:
                    return True
                console.print("  [yellow]CLI didn't work, trying GUI...[/]")
            return self._execute_gui_step(step)

    def _execute_cli_step(self, step: Step) -> bool:
        """Run a CLI command directly."""
        cmd = step.cli_command
        if not cmd:
            step.error = "No CLI command."
            return False

        console.print(f"  [dim]$ {cmd}[/]")
        result = run_command(
            cmd, self.settings,
            skip_confirmation=False,
            confirm_callback=self._confirm,
        )

        if result.success:
            step.result = result.output[:200]
            # Give app a moment to start if it's a launch command
            if cmd.strip().lower().startswith("start"):
                time.sleep(1.5)
            return True
        else:
            step.error = result.stderr[:200]
            return False

    def _execute_gui_step(self, step: Step) -> bool:
        """Run the vision-based agentic loop for a GUI step.

        This maintains a multi-turn conversation so the model can see
        its own previous actions and results. It also detects loops
        and injects correction messages.
        """
        sys_prompt = executor_system(self.screen.info)

        # Take initial screenshot
        screenshot_b64 = self.screen.capture()

        # Build the first user message with screenshot
        conversation: list[dict[str, Any]] = [
            _make_user_msg(
                f"TASK: {step.description}\n\n"
                f"Here is the current screen. Assess what you see and decide "
                f"what action to take. Remember: look at the state carefully "
                f"before acting.",
                screenshot_b64,
                self.settings.screenshot_format,
            )
        ]

        # Track actions for loop detection
        action_history: list[dict] = []

        for iteration in range(self.settings.max_iterations):
            # ── Check for loops and inject correction ────────────
            loop_nudge = _detect_loop(action_history)
            if loop_nudge:
                console.print(f"  [red bold]Loop detected![/] Injecting correction...")
                conversation.append({
                    "role": "user",
                    "content": loop_nudge,
                })

            # ── Prune old images to keep context manageable ──────
            pruned_convo = _prune_old_images(conversation)

            # ── Call the vision model with full history ───────────
            try:
                raw = self.llm.vision_chat_multi(
                    system=sys_prompt,
                    messages=pruned_convo,
                    temperature=0.2,
                    json_mode=True,
                )
            except Exception as exc:
                logger.error(f"LLM call failed: {exc}")
                step.error = f"LLM error: {exc}"
                return False

            action_dict = parse_json_response(raw)

            if "error" in action_dict and "raw" in action_dict:
                logger.warning(f"Failed to parse: {action_dict['raw'][:100]}")
                # Tell the model its response was bad and try again
                conversation.append({"role": "assistant", "content": raw})
                conversation.append({
                    "role": "user",
                    "content": "Your response was not valid JSON. Respond with "
                               "a single JSON object like: "
                               '{"thought": "...", "action": "type", "text": "..."}',
                })
                continue

            thought = action_dict.get("thought", "")
            action_type = action_dict.get("action", "")
            if thought:
                console.print(f"  [dim italic]Think: {thought[:150]}[/]")
            console.print(f"  [blue]Action:[/] {action_type} {_action_summary(action_dict)}")

            # Append assistant response to conversation
            conversation.append({"role": "assistant", "content": raw})

            # Track for loop detection
            action_history.append(action_dict)

            # ── Check if done ────────────────────────────────────
            if action_type in ("done", "complete", "finished"):
                step.result = action_dict.get("summary", "Step completed.")
                return True

            # ── Execute the action ───────────────────────────────
            result = self.executor.execute(action_dict, confirm_callback=self._confirm)

            # ── Build feedback message for the model ─────────────
            if result.screenshot_b64:
                # Action returned a screenshot (screenshot/zoom actions)
                feedback_text = f"Action '{action_type}' executed. Here is the result."
                conversation.append(
                    _make_user_msg(feedback_text, result.screenshot_b64,
                                   self.settings.screenshot_format)
                )
            elif not result.success:
                # Action failed — tell the model what went wrong
                console.print(f"  [red]Error:[/] {result.error}")
                conversation.append({
                    "role": "user",
                    "content": f"Action '{action_type}' FAILED: {result.error}\n"
                               f"Try a different approach.",
                })
            else:
                # Action succeeded — take a new screenshot so the model
                # can see what changed
                time.sleep(0.4)  # Brief pause for UI to update
                new_screenshot = self.screen.capture()
                if action_type in ("type", "type_text"):
                    typed_text = action_dict.get("text", "")
                    feedback_text = (
                        f"Action '{action_type}' executed: {result.output}\n"
                        f"VERIFY: Check the screenshot — does the text "
                        f"\"{typed_text[:60]}\" actually appear on screen? "
                        f"If the wrong text appeared or nothing changed, the "
                        f"typing may have failed — try clicking the text field "
                        f"first, then type again."
                    )
                else:
                    feedback_text = (
                        f"Action '{action_type}' succeeded: {result.output}\n"
                        f"Here is the screen AFTER the action. "
                        f"Assess what changed and decide the next step. "
                        f"If the task is complete, respond with "
                        f"{{\"action\": \"done\"}}."
                    )
                conversation.append(
                    _make_user_msg(feedback_text, new_screenshot,
                                   self.settings.screenshot_format)
                )

        step.error = f"Hit iteration limit ({self.settings.max_iterations})."
        return False

    def _execute_verify_step(self, step: Step) -> bool:
        """Take a screenshot and ask the verifier if the state is correct."""
        screenshot_b64 = self.screen.capture()
        sys_prompt = verifier_system()

        try:
            raw = self.llm.vision_chat(
                system=sys_prompt,
                user_text=f"Expected state: {step.description}",
                image_b64=screenshot_b64,
                temperature=0.1,
                json_mode=True,
                role="verifier",
            )
        except Exception as exc:
            step.error = f"Verification LLM error: {exc}"
            return False

        result = parse_json_response(raw)
        success = result.get("success", False)
        step.result = result.get("observation", "")
        if not success:
            step.error = result.get("issue", "Verification failed.")
        return success

    # ── Helpers ──────────────────────────────────────────────────

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
        console.print()
        total = len(task.steps)
        ok = sum(1 for s in task.steps if s.status == StepStatus.SUCCESS)
        failed = sum(1 for s in task.steps if s.status == StepStatus.FAILED)

        panel_style = "green" if task.completed else "red"
        status = "COMPLETED" if task.completed else "INCOMPLETE"

        lines = [
            f"Status:    [bold]{status}[/]",
            f"Steps:     {ok}/{total} succeeded, {failed} failed",
            f"Duration:  {task.duration_s:.1f}s",
        ]
        console.print(Panel(
            "\n".join(lines),
            title="Task Summary",
            border_style=panel_style,
        ))


# ── Helpers ──────────────────────────────────────────────────────

def _make_user_msg(text: str, image_b64: str, fmt: str = "png") -> dict:
    """Build a user message with text + image for the conversation."""
    media = "image/png" if fmt == "png" else "image/jpeg"
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {
                "url": f"data:{media};base64,{image_b64}",
            }},
        ],
    }


def _action_summary(action: dict) -> str:
    """Short one-line summary of an action for display."""
    a = action.get("action", "")
    if a in ("cli", "command"):
        return f'→ `{action.get("command", "")[:60]}`'
    if a == "launch_app":
        return f'→ {action.get("app", "")}'
    if a in ("click", "left_click", "right_click", "double_click"):
        coord = action.get("coordinate", action.get("coords", "?"))
        return f"→ {coord}"
    if a == "type":
        text = action.get("text", "")
        return f'→ "{text[:40]}{"..." if len(text) > 40 else ""}"'
    if a in ("key", "hotkey"):
        return f'→ {action.get("keys", action.get("text", ""))}'
    if a == "scroll":
        return f'→ {action.get("direction", "")} x{action.get("amount", 3)}'
    if a == "check_file":
        return f'→ {action.get("path", "")[:50]}'
    return ""
