"""Conversation context management for the GUI executor loop.

Handles image pruning (to keep the context window manageable) and
message construction helpers.
"""

from __future__ import annotations

from typing import Any

MAX_IMAGES_IN_HISTORY = 6  # Keep only the last N screenshots in conversation


def prune_old_images(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def make_user_msg(text: str, image_b64: str, fmt: str = "png") -> dict:
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


def action_summary(action: dict) -> str:
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
