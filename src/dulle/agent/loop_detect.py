"""Loop detection for the GUI executor loop.

Catches two patterns:
  1. Same action repeated N times (clicking the same spot, etc.)
  2. Taking screenshots without ever acting on them
"""

from __future__ import annotations

MAX_SAME_ACTION = 2   # After 2 identical actions in a row, intervene
MAX_SCREENSHOTS_ONLY = 3  # After 3 screenshots with no real action, intervene


def action_signature(action: dict) -> str:
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


def detect_loop(history: list[dict]) -> str | None:
    """Check recent action history for loops. Returns a nudge message or None."""
    if len(history) < 2:
        return None

    # Check for same action repeated
    sigs = [action_signature(h) for h in history]
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
            f'{{"action": "done", "summary": "Unable to complete — [reason]"}}.'
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
