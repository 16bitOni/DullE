"""Step execution functions — CLI, GUI, verify, and routing.

Each function takes all its dependencies explicitly rather than via self,
keeping them independently testable and readable.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from loguru import logger
from rich.console import Console
from rich.prompt import Prompt

from dulle.agent.batch import execute_action_batch, execute_single_action
from dulle.agent.context import make_user_msg, prune_old_images
from dulle.agent.loop_detect import detect_loop
from dulle.agent.audit import AuditTrail
from dulle.llm.client import LLMClient, parse_json_response
from dulle.llm.prompts import executor_system, verifier_system
from dulle.models import ActionType, Step

if TYPE_CHECKING:
    from dulle.config import Settings
    from dulle.execution.actions import ActionExecutor
    from dulle.execution.screen import ScreenCapture
    from dulle.execution.shell import run_command as _run_command

console = Console()


def execute_step(
    step: Step,
    audit: AuditTrail,
    llm: LLMClient,
    screen: "ScreenCapture",
    executor: "ActionExecutor",
    settings: "Settings",
    knowledge_text: str,
    confirm_callback,
) -> bool:
    """Route a step to the right executor. CLI-first: always tries CLI when available."""
    from dulle.execution.shell import run_command

    mode = step.action_type

    if mode == ActionType.VERIFY:
        return execute_verify_step(step, audit, llm, screen, settings)
    if mode == ActionType.WAIT:
        wait_s = 3 if "load" in step.description.lower() else 2
        time.sleep(wait_s)
        step.result = f"Waited {wait_s}s."
        return True

    # CLI-first: try CLI whenever a command hint exists
    if step.cli_command:
        ok = execute_cli_step(step, audit, settings, confirm_callback)
        if ok:
            return True
        # CLI failed — always fall back to GUI regardless of action_type.
        # The planner may have been wrong about CLI being sufficient.
        console.print("  [yellow]CLI didn't work, falling back to GUI...[/]")
        return execute_gui_step(step, audit, llm, screen, executor, settings,
                                knowledge_text, confirm_callback)

    if mode == ActionType.CLI:
        # CLI typed but no command hint — let GUI handle it
        console.print("  [yellow]No CLI command, using GUI...[/]")

    return execute_gui_step(step, audit, llm, screen, executor, settings,
                            knowledge_text, confirm_callback)


def execute_cli_step(
    step: Step,
    audit: AuditTrail,
    settings: "Settings",
    confirm_callback,
) -> bool:
    """Run a pre-planned CLI command directly."""
    from dulle.execution.shell import run_command

    cmd = step.cli_command
    if not cmd:
        step.error = "No CLI command."
        return False

    console.print(f"  [bold blue]Running:[/] [cyan]$ {cmd}[/]")
    result = run_command(cmd, settings, skip_confirmation=False,
                         confirm_callback=confirm_callback)

    audit.save_action(step.index, 0, {"action": "cli", "command": cmd},
                      {"success": result.success, "output": result.output[:200]})

    if result.success:
        step.result = result.output[:200]
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


def execute_gui_step(
    step: Step,
    audit: AuditTrail,
    llm: LLMClient,
    screen: "ScreenCapture",
    executor: "ActionExecutor",
    settings: "Settings",
    knowledge_text: str,
    confirm_callback,
) -> bool:
    """Run the vision-based agentic loop for a GUI step.

    Maintains a multi-turn conversation so the model sees its own previous
    actions. Detects loops and injects correction messages.
    """
    console.print(f"  [bold blue]GUI mode:[/] Starting vision-based execution...")
    sys_prompt = executor_system(screen.info)
    if knowledge_text:
        sys_prompt += "\n\n" + knowledge_text
    step_deadline = time.monotonic() + settings.step_timeout_s

    console.print(f"  [dim]Capturing screen...[/]")
    screenshot_b64 = screen.capture()
    audit.save_screenshot(screenshot_b64, step.index, 0, fmt=settings.screenshot_format)

    conversation: list[dict[str, Any]] = [
        make_user_msg(
            f"TASK: {step.description}\n\n"
            f"Here is the current screen. Assess what you see and decide "
            f"what action to take. Remember: look at the state carefully "
            f"before acting.",
            screenshot_b64,
            settings.screenshot_format,
        )
    ]

    action_history: list[dict] = []
    consecutive_llm_failures = 0
    MAX_CONSECUTIVE_LLM_FAILURES = 2

    for iteration in range(settings.max_iterations):
        remaining = step_deadline - time.monotonic()
        if remaining <= 0:
            step.error = f"Step timed out after {settings.step_timeout_s:.0f}s."
            console.print(f"  [red]Timeout![/] {step.error}")
            return False

        console.print(
            f"  [bold cyan]Iteration {iteration + 1}/{settings.max_iterations}[/] "
            f"[dim]({remaining:.0f}s remaining)[/]"
        )

        loop_nudge = detect_loop(action_history)
        if loop_nudge:
            console.print(f"  [red bold]Loop detected![/] Injecting correction...")
            conversation.append({"role": "user", "content": loop_nudge})
            if not llm._executor_escalated:
                if llm.escalate_executor():
                    console.print(
                        f"  [yellow]Escalating to {settings.executor_model_heavy}[/]"
                    )

        pruned_convo = prune_old_images(conversation)

        try:
            raw = llm.vision_chat_multi(
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

        conversation.append({"role": "assistant", "content": raw})

        # ── Ask user if agent hit genuine ambiguity ──────────────
        if action_dict.get("action") == "ask_user":
            question = action_dict.get("question", "I need clarification to continue.")
            options = action_dict.get("options", [])

            console.print(f"\n  [bold yellow]Agent needs input:[/] {question}")
            if options:
                for i, opt in enumerate(options, 1):
                    console.print(f"    {i}. {opt}")

            answer = Prompt.ask("  [bold cyan]Your answer[/]")
            console.print()

            conversation.append({
                "role": "user",
                "content": (
                    f"User answered: {answer}\n\n"
                    f"Continue the task using this information."
                ),
            })
            continue

        actions_list = action_dict.get("actions")
        if isinstance(actions_list, list) and actions_list:
            done_result = execute_action_batch(
                actions_list, step, iteration, audit, action_history, conversation,
                executor, screen, settings, confirm_callback,
            )
        else:
            done_result = execute_single_action(
                action_dict, step, iteration, audit, action_history, conversation,
                executor, screen, settings, confirm_callback,
            )

        if done_result is not None:
            return done_result

    step.error = f"Hit iteration limit ({settings.max_iterations})."
    return False


def execute_verify_step(
    step: Step,
    audit: AuditTrail,
    llm: LLMClient,
    screen: "ScreenCapture",
    settings: "Settings",
    max_attempts: int = 3,
) -> bool:
    """Take a screenshot and ask the verifier if the expected state is present.

    Retries with increasing delays — pages and apps often need time to render.
    """
    console.print(f"  [bold blue]Verifying:[/] Checking screen state...")
    sys_prompt = verifier_system()
    delays = [0, 3, 5]

    for attempt in range(max_attempts):
        if delays[attempt] > 0:
            console.print(f"  [dim]Waiting {delays[attempt]}s for content to load...[/]")
            time.sleep(delays[attempt])

        screenshot_b64 = screen.capture()
        audit.save_screenshot(screenshot_b64, step.index, attempt,
                              label="verify", fmt=settings.screenshot_format)

        try:
            raw = llm.vision_chat(
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
