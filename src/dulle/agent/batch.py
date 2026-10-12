"""Single-action and batch-action execution for the GUI loop.

Both functions return:
  True  — step is done (success)
  False — step is done (failure)
  None  — keep iterating
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from loguru import logger
from rich.console import Console

from dulle.agent.context import action_summary, make_user_msg
from dulle.agent.audit import AuditTrail
from dulle.models import Step

if TYPE_CHECKING:
    from dulle.execution.actions import ActionExecutor
    from dulle.execution.screen import ScreenCapture
    from dulle.config import Settings

console = Console()


def execute_single_action(
    action_dict: dict,
    step: Step,
    iteration: int,
    audit: AuditTrail,
    action_history: list[dict],
    conversation: list[dict],
    executor: "ActionExecutor",
    screen: "ScreenCapture",
    settings: "Settings",
    confirm_callback,
) -> bool | None:
    """Execute one action. Returns True/False to stop, or None to continue."""
    action_type = action_dict.get("action", "")
    console.print(f"  [blue]Action:[/] {action_type} {action_summary(action_dict)}")

    action_history.append(action_dict)
    audit.save_action(step.index, iteration, action_dict,
                      {"thought": action_dict.get("thought", "")})

    if action_type in ("done", "complete", "finished"):
        step.result = action_dict.get("summary", "Step completed.")
        return True

    result = executor.execute(action_dict, confirm_callback=confirm_callback)

    if result.screenshot_b64:
        feedback_text = f"Action '{action_type}' executed. Here is the result."
        audit.save_screenshot(result.screenshot_b64, step.index, iteration,
                              label="result", fmt=settings.screenshot_format)
        conversation.append(
            make_user_msg(feedback_text, result.screenshot_b64, settings.screenshot_format)
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
        new_screenshot = screen.capture()
        audit.save_screenshot(new_screenshot, step.index, iteration,
                              label="after", fmt=settings.screenshot_format)
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
            make_user_msg(feedback_text, new_screenshot, settings.screenshot_format)
        )
    return None


def execute_action_batch(
    actions: list[dict],
    step: Step,
    iteration: int,
    audit: AuditTrail,
    action_history: list[dict],
    conversation: list[dict],
    executor: "ActionExecutor",
    screen: "ScreenCapture",
    settings: "Settings",
    confirm_callback,
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
            f"{action_summary(sub_action)}"
        )

        action_history.append(sub_action)
        audit.save_action(step.index, iteration, sub_action,
                          {"batch_index": i, "batch_size": len(actions)})

        if action_type in ("done", "complete", "finished"):
            step.result = sub_action.get("summary", "Step completed.")
            return True

        result = executor.execute(sub_action, confirm_callback=confirm_callback)
        batch_outputs.append(f"  {i+1}. {action_type}: {result.output[:80]}")

        if not result.success:
            console.print(f"    [red]Error:[/] {result.error}")
            time.sleep(0.3)
            new_screenshot = screen.capture()
            audit.save_screenshot(new_screenshot, step.index, iteration,
                                  label="batch_fail", fmt=settings.screenshot_format)
            conversation.append(
                make_user_msg(
                    f"Batch action {i+1}/{len(actions)} FAILED "
                    f"('{action_type}'): {result.error}\n"
                    f"Actions completed before failure:\n"
                    + "\n".join(batch_outputs[:-1])
                    + "\nHere is the screen now. Try a different approach.",
                    new_screenshot,
                    settings.screenshot_format,
                )
            )
            return None

        time.sleep(0.15)

    # All actions succeeded — one screenshot
    time.sleep(0.4)
    new_screenshot = screen.capture()
    audit.save_screenshot(new_screenshot, step.index, iteration,
                          label="batch_done", fmt=settings.screenshot_format)
    conversation.append(
        make_user_msg(
            f"All {len(actions)} batch actions succeeded:\n"
            + "\n".join(batch_outputs)
            + "\n\nHere is the screen AFTER the batch. "
            f"Assess what changed. If the task is complete, respond with "
            f"{{\"action\": \"done\"}}.",
            new_screenshot,
            settings.screenshot_format,
        )
    )
    return None
