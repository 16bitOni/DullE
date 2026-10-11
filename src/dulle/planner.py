"""Task planner — decomposes user commands into executable steps.

Uses the cheap text model (DeepSeek by default) to break a natural-language
command into a sequence of CLI and GUI steps.
"""

from __future__ import annotations

import json

from dulle.config import Settings
from dulle.llm import LLMClient, parse_json_response
from dulle.models import ActionType, Step
from dulle.prompts import planner_system


def plan_task(
    user_command: str,
    llm: LLMClient,
    screen_info: dict,
    settings: Settings,
) -> list[Step]:
    """Break a user command into execution steps.

    Returns a list of Step objects ready for the agent loop.
    """
    system = planner_system(screen_info)

    raw = llm.text_chat(
        role="planner",
        system=system,
        user_message=user_command,
        temperature=0.3,
    )

    # Parse the JSON array of steps
    steps = _parse_plan(raw)

    # Cap at max steps
    if len(steps) > settings.max_steps:
        steps = steps[: settings.max_steps]

    return steps


def _parse_plan(raw_text: str) -> list[Step]:
    """Parse the planner's JSON output into Step objects."""
    # Try to parse as JSON array
    text = raw_text.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find a JSON array
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end])
            except json.JSONDecodeError:
                # Fallback: split by numbered lines
                return _parse_numbered_lines(raw_text)
        else:
            return _parse_numbered_lines(raw_text)

    if not isinstance(data, list):
        return _parse_numbered_lines(raw_text)

    steps = []
    for i, item in enumerate(data):
        if isinstance(item, str):
            steps.append(Step(index=i + 1, description=item))
        elif isinstance(item, dict):
            action_type_str = item.get("action_type", "hybrid")
            try:
                action_type = ActionType(action_type_str)
            except ValueError:
                action_type = ActionType.HYBRID

            step = Step(
                index=item.get("step", i + 1),
                description=item.get("description", str(item)),
                action_type=action_type,
                cli_command=item.get("cli_hint") or item.get("cli_command"),
            )
            steps.append(step)

    return steps


def _parse_numbered_lines(text: str) -> list[Step]:
    """Fallback parser: extract numbered lines from plain text."""
    steps = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Match patterns like "1. ...", "1) ...", "- ..."
        if line[0].isdigit():
            # Remove number prefix
            for sep in [".", ")", ":"]:
                if sep in line:
                    desc = line.split(sep, 1)[1].strip()
                    break
            else:
                desc = line
            steps.append(Step(index=len(steps) + 1, description=desc))
        elif line.startswith("- "):
            steps.append(Step(index=len(steps) + 1, description=line[2:]))

    return steps
