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

import pyautogui
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from dulle.audit import AuditTrail
from dulle.config import Settings
from dulle.executor import ActionExecutor
from dulle.knowledge import KnowledgeBase
from dulle.llm import LLMClient, parse_json_response
from dulle.models import ActionResult, ActionType, Step, StepStatus, TaskResult
from dulle.planner import describe_screen, plan_task
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

        # Retrieve relevant knowledge for this task
        self._knowledge_text = ""
        relevant_knowledge = self.knowledge.retrieve(user_command)
        if relevant_knowledge:
            self._knowledge_text = self.knowledge.format_for_prompt(relevant_knowledge)
            console.print(f"  [dim]Knowledge: {len(relevant_knowledge)} relevant entries loaded[/]")

        # Give the planner context about what's already on screen
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
                knowledge_text=self._knowledge_text,
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
            step.started_at = datetime.now()
            step.status = StepStatus.RUNNING

            success = self._execute_step(step, audit)

            step.ended_at = datetime.now()
            step.status = StepStatus.SUCCESS if success else StepStatus.FAILED

            status_icon = "[green]OK[/]" if success else "[red]FAIL[/]"
            console.print(f"  Result: {status_icon} — {step.result or step.error}\n")

            if not success:
                # Try once more — escalate to heavy model if available
                step.retries += 1
                escalated = self.llm.escalate_executor()
                if escalated:
                    console.print(
                        f"  [yellow]Retrying with stronger model "
                        f"({self.settings.executor_model_heavy})...[/]"
                    )
                else:
                    console.print("  [yellow]Retrying...[/]")
                success = self._execute_step(step, audit)
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

    # ── Step execution ───────────────────────────────────────────

    def _execute_step(self, step: Step, audit: AuditTrail) -> bool:
        """Execute a single step. Returns True if succeeded.

        CLI-first: always try CLI when a command hint exists, regardless of
        action_type. Only fall back to GUI if CLI fails or isn't available.
        """
        mode = step.action_type

        if mode == ActionType.VERIFY:
            return self._execute_verify_step(step, audit)
        if mode == ActionType.WAIT:
            wait_s = 3 if "load" in step.description.lower() else 2
            time.sleep(wait_s)
            step.result = f"Waited {wait_s}s."
            return True

        # CLI-first: try CLI whenever a command hint exists
        if step.cli_command:
            ok = self._execute_cli_step(step, audit)
            if ok:
                return True
            if mode == ActionType.CLI:
                return False
            console.print("  [yellow]CLI didn't work, falling back to GUI...[/]")

        if mode == ActionType.CLI:
            step.error = "No CLI command provided."
            return False

        # GUI fallback for gui/hybrid steps
        return self._execute_gui_step(step, audit)

    def _execute_cli_step(self, step: Step, audit: AuditTrail) -> bool:
        """Run a CLI command directly."""
        cmd = step.cli_command
        if not cmd:
            step.error = "No CLI command."
            return False

        console.print(f"  [bold blue]Running:[/] [cyan]$ {cmd}[/]")
        result = run_command(
            cmd, self.settings,
            skip_confirmation=False,
            confirm_callback=self._confirm,
        )

        audit.save_action(step.index, 0, {"action": "cli", "command": cmd},
                          {"success": result.success, "output": result.output[:200]})

        if result.success:
            step.result = result.output[:200]
            # Give app time to start — browsers with URLs need longer
            lower = cmd.strip().lower()
            if lower.startswith("start"):
                has_url = "http" in lower or ".com" in lower or ".org" in lower
                has_browser = any(b in lower for b in ("chrome", "msedge", "firefox", "brave"))
                if has_url or has_browser:
                    time.sleep(4)
                else:
                    time.sleep(2)
            return True
        else:
            step.error = result.stderr[:200]
            return False

    def _execute_gui_step(self, step: Step, audit: AuditTrail) -> bool:
        """Run the vision-based agentic loop for a GUI step.

        This maintains a multi-turn conversation so the model can see
        its own previous actions and results. It also detects loops
        and injects correction messages.
        """
        console.print(f"  [bold blue]GUI mode:[/] Starting vision-based execution...")
        sys_prompt = executor_system(self.screen.info)
        if self._knowledge_text:
            sys_prompt += "\n\n" + self._knowledge_text
        step_deadline = time.monotonic() + self.settings.step_timeout_s

        # Take initial screenshot
        console.print(f"  [dim]Capturing screen...[/]")
        screenshot_b64 = self.screen.capture()
        audit.save_screenshot(screenshot_b64, step.index, 0,
                              fmt=self.settings.screenshot_format)

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
        consecutive_llm_failures = 0
        MAX_CONSECUTIVE_LLM_FAILURES = 2

        for iteration in range(self.settings.max_iterations):
            # ── Check step timeout ───────────────────────────────
            remaining = step_deadline - time.monotonic()
            if remaining <= 0:
                step.error = f"Step timed out after {self.settings.step_timeout_s:.0f}s."
                console.print(f"  [red]Timeout![/] {step.error}")
                return False

            console.print(
                f"  [bold cyan]Iteration {iteration + 1}/{self.settings.max_iterations}[/] "
                f"[dim]({remaining:.0f}s remaining)[/]"
            )

            # ── Check for loops and inject correction ────────────
            loop_nudge = _detect_loop(action_history)
            if loop_nudge:
                console.print(f"  [red bold]Loop detected![/] Injecting correction...")
                conversation.append({
                    "role": "user",
                    "content": loop_nudge,
                })
                # Escalate to heavy model after loop detection
                if not self.llm._executor_escalated:
                    if self.llm.escalate_executor():
                        console.print(
                            f"  [yellow]Escalating to "
                            f"{self.settings.executor_model_heavy}[/]"
                        )

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
                consecutive_llm_failures = 0
            except Exception as exc:
                consecutive_llm_failures += 1
                logger.error(f"LLM call failed: {exc}")
                console.print(
                    f"  [red bold]LLM call failed "
                    f"({consecutive_llm_failures}/{MAX_CONSECUTIVE_LLM_FAILURES}):[/] {exc}"
                )
                if consecutive_llm_failures >= MAX_CONSECUTIVE_LLM_FAILURES:
                    step.error = (
                        f"Aborting — LLM failed {consecutive_llm_failures} times in a row: {exc}"
                    )
                    console.print(
                        f"  [red bold]Aborting step:[/] Model is not responding. "
                        f"Check your API endpoint and model name."
                    )
                    return False
                console.print(f"  [yellow]Will retry on next iteration...[/]")
                continue

            action_dict = parse_json_response(raw)

            if "error" in action_dict and "raw" in action_dict:
                logger.warning(f"Failed to parse: {action_dict['raw'][:100]}")
                conversation.append({"role": "assistant", "content": raw})
                conversation.append({
                    "role": "user",
                    "content": "Your response was not valid JSON. Respond with "
                               "a single JSON object like: "
                               '{"thought": "...", "action": "type", "text": "..."} '
                               'or a batch: {"thought": "...", "actions": [{...}, {...}]}',
                })
                continue

            thought = action_dict.get("thought", "")
            if thought:
                console.print(f"  [dim italic]Think: {thought[:150]}[/]")

            # Append assistant response to conversation
            conversation.append({"role": "assistant", "content": raw})

            # ── Detect batch vs single action ────────────────────
            actions_list = action_dict.get("actions")
            if isinstance(actions_list, list) and actions_list:
                # BATCH MODE: execute all actions, screenshot once at end
                done_result = self._execute_action_batch(
                    actions_list, step, iteration, audit,
                    action_history, conversation,
                )
                if done_result is not None:
                    return done_result
            else:
                # SINGLE ACTION MODE
                done_result = self._execute_single_action(
                    action_dict, step, iteration, audit,
                    action_history, conversation,
                )
                if done_result is not None:
                    return done_result

        step.error = f"Hit iteration limit ({self.settings.max_iterations})."
        return False

    def _execute_verify_step(self, step: Step, audit: AuditTrail,
                             max_attempts: int = 3) -> bool:
        """Take a screenshot and ask the verifier if the state is correct.

        Retries with increasing delays — pages and apps often need a few
        seconds to finish rendering.
        """
        console.print(f"  [bold blue]Verifying:[/] Checking screen state...")
        sys_prompt = verifier_system()
        delays = [0, 3, 5]  # seconds to wait before each attempt

        for attempt in range(max_attempts):
            if delays[attempt] > 0:
                console.print(f"  [dim]Waiting {delays[attempt]}s for content to load...[/]")
                time.sleep(delays[attempt])

            screenshot_b64 = self.screen.capture()
            audit.save_screenshot(screenshot_b64, step.index, attempt,
                                  label="verify", fmt=self.settings.screenshot_format)

            try:
                raw = self.llm.vision_chat(
                    system=sys_prompt,
                    user_text=(
                        f"Expected state: {step.description}\n\n"
                        f"NOTE: If the screen is mostly dark or shows a loading "
                        f"indicator, consider whether the page/app might still "
                        f"be loading. Only fail if the content is clearly wrong, "
                        f"not just slow."
                    ),
                    image_b64=screenshot_b64,
                    temperature=0.1,
                    json_mode=True,
                    role="verifier",
                )
            except Exception as exc:
                console.print(f"  [red]Verification LLM error:[/] {exc}")
                step.error = f"Verification LLM error: {exc}"
                return False

            result = parse_json_response(raw)
            success = result.get("success", False)
            step.result = result.get("observation", "")

            if success:
                return True

            confidence = result.get("confidence", 0.5)
            issue = result.get("issue", "Verification failed.")

            # If confidence is low or it mentions loading, retry
            if attempt < max_attempts - 1 and (
                confidence < 0.7
                or "load" in issue.lower()
                or "black" in issue.lower()
                or "dark" in issue.lower()
                or "blank" in issue.lower()
            ):
                console.print(f"  [yellow]Attempt {attempt + 1}: {issue} — retrying...[/]")
                continue

            step.error = issue
            return False

        step.error = result.get("issue", "Verification failed after retries.")
        return False

    # ── Action execution helpers (single + batch) ─────────────────

    def _execute_single_action(
        self, action_dict: dict, step: Step, iteration: int,
        audit: AuditTrail, action_history: list[dict],
        conversation: list[dict],
    ) -> bool | None:
        """Execute one action. Returns True/False to stop, or None to continue."""
        action_type = action_dict.get("action", "")
        console.print(f"  [blue]Action:[/] {action_type} {_action_summary(action_dict)}")

        action_history.append(action_dict)
        audit.save_action(step.index, iteration, action_dict,
                          {"thought": action_dict.get("thought", "")})

        if action_type in ("done", "complete", "finished"):
            step.result = action_dict.get("summary", "Step completed.")
            return True

        result = self.executor.execute(action_dict, confirm_callback=self._confirm)

        if result.screenshot_b64:
            feedback_text = f"Action '{action_type}' executed. Here is the result."
            audit.save_screenshot(result.screenshot_b64, step.index, iteration,
                                  label="result", fmt=self.settings.screenshot_format)
            conversation.append(
                _make_user_msg(feedback_text, result.screenshot_b64,
                               self.settings.screenshot_format)
            )
        elif not result.success:
            console.print(f"  [red]Error:[/] {result.error}")
            conversation.append({
                "role": "user",
                "content": f"Action '{action_type}' FAILED: {result.error}\n"
                           f"Try a different approach.",
            })
        else:
            time.sleep(0.4)
            new_screenshot = self.screen.capture()
            audit.save_screenshot(new_screenshot, step.index, iteration,
                                  label="after", fmt=self.settings.screenshot_format)
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
        return None

    def _execute_action_batch(
        self, actions: list[dict], step: Step, iteration: int,
        audit: AuditTrail, action_history: list[dict],
        conversation: list[dict],
    ) -> bool | None:
        """Execute a batch of actions, screenshot once at end.

        Returns True/False to stop, or None to continue the loop.
        """
        console.print(f"  [bold magenta]Batch:[/] {len(actions)} actions")
        batch_outputs = []

        for i, sub_action in enumerate(actions):
            action_type = sub_action.get("action", "")
            console.print(
                f"    [blue]({i+1}/{len(actions)})[/] {action_type} "
                f"{_action_summary(sub_action)}"
            )

            action_history.append(sub_action)
            audit.save_action(step.index, iteration, sub_action,
                              {"batch_index": i, "batch_size": len(actions)})

            if action_type in ("done", "complete", "finished"):
                step.result = sub_action.get("summary", "Step completed.")
                return True

            result = self.executor.execute(
                sub_action, confirm_callback=self._confirm
            )
            batch_outputs.append(f"  {i+1}. {action_type}: {result.output[:80]}")

            if not result.success:
                console.print(f"    [red]Error:[/] {result.error}")
                # Batch failed mid-way — take screenshot and tell model
                time.sleep(0.3)
                new_screenshot = self.screen.capture()
                audit.save_screenshot(new_screenshot, step.index, iteration,
                                      label="batch_fail", fmt=self.settings.screenshot_format)
                conversation.append(
                    _make_user_msg(
                        f"Batch action {i+1}/{len(actions)} FAILED "
                        f"('{action_type}'): {result.error}\n"
                        f"Actions completed before failure:\n"
                        + "\n".join(batch_outputs[:-1])
                        + "\nHere is the screen now. Try a different approach.",
                        new_screenshot,
                        self.settings.screenshot_format,
                    )
                )
                return None

            time.sleep(0.15)

        # All actions succeeded — take one screenshot
        time.sleep(0.4)
        new_screenshot = self.screen.capture()
        audit.save_screenshot(new_screenshot, step.index, iteration,
                              label="batch_done", fmt=self.settings.screenshot_format)
        conversation.append(
            _make_user_msg(
                f"All {len(actions)} batch actions succeeded:\n"
                + "\n".join(batch_outputs)
                + "\n\nHere is the screen AFTER the batch. "
                f"Assess what changed. If the task is complete, respond with "
                f"{{\"action\": \"done\"}}.",
                new_screenshot,
                self.settings.screenshot_format,
            )
        )
        return None

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

        usage = task.token_usage
        token_line = ""
        if usage and usage.get("total_tokens", 0) > 0:
            token_line = (
                f"\nTokens:    {usage['total_tokens']:,} "
                f"({usage['prompt_tokens']:,} in / "
                f"{usage['completion_tokens']:,} out) "
                f"across {usage['call_count']} calls"
            )

        lines = [
            f"Status:    [bold]{status}[/]",
            f"Steps:     {ok}/{total} succeeded, {failed} failed",
            f"Duration:  {task.duration_s:.1f}s{token_line}",
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
