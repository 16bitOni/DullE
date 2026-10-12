"""Audit trail — saves screenshots, actions, and results to disk.

Every task run gets a timestamped directory under audit_trail/:
  audit_trail/
    20261012_143052_open_notepad/
      manifest.json          ← full task record
      step1_iter00_screen.png
      step1_iter01_action.json
      step1_iter01_screen.png
      ...

This lets you replay exactly what the agent saw and did.
"""

from __future__ import annotations

import base64
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger


class AuditTrail:
    """Manages on-disk audit trail for a single task run."""

    def __init__(self, base_dir: str, command: str, enabled: bool = True):
        self.enabled = enabled
        if not enabled:
            self.run_dir = Path(".")
            return

        slug = _slugify(command)[:50]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_dir = Path(base_dir) / f"{ts}_{slug}"
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self._entries: list[dict[str, Any]] = []
        logger.info(f"Audit trail: {self.run_dir}")

    def save_screenshot(
        self, b64_data: str, step: int, iteration: int, label: str = "screen",
        fmt: str = "png",
    ) -> str | None:
        """Save a screenshot to disk. Returns the filename."""
        if not self.enabled:
            return None
        ext = "jpg" if fmt == "jpeg" else "png"
        filename = f"step{step:02d}_iter{iteration:02d}_{label}.{ext}"
        filepath = self.run_dir / filename
        try:
            filepath.write_bytes(base64.b64decode(b64_data))
        except Exception as exc:
            logger.warning(f"Failed to save screenshot: {exc}")
            return None
        return filename

    def save_action(
        self, step: int, iteration: int, action: dict, result: dict | None = None,
    ):
        """Record an action and its result."""
        if not self.enabled:
            return
        entry = {
            "timestamp": datetime.now().isoformat(),
            "step": step,
            "iteration": iteration,
            "action": action,
        }
        if result is not None:
            entry["result"] = result
        self._entries.append(entry)

        filename = f"step{step:02d}_iter{iteration:02d}_action.json"
        filepath = self.run_dir / filename
        try:
            filepath.write_text(json.dumps(entry, indent=2, default=str))
        except Exception as exc:
            logger.warning(f"Failed to save action: {exc}")

    def save_plan(self, steps: list[dict]):
        """Save the planned steps."""
        if not self.enabled:
            return
        filepath = self.run_dir / "plan.json"
        try:
            filepath.write_text(json.dumps(steps, indent=2, default=str))
        except Exception as exc:
            logger.warning(f"Failed to save plan: {exc}")

    def save_manifest(self, task_result: dict):
        """Save the final task manifest with all metadata."""
        if not self.enabled:
            return
        manifest = {
            "completed_at": datetime.now().isoformat(),
            "task": task_result,
            "actions": self._entries,
        }
        filepath = self.run_dir / "manifest.json"
        try:
            filepath.write_text(json.dumps(manifest, indent=2, default=str))
        except Exception as exc:
            logger.warning(f"Failed to save manifest: {exc}")


def _slugify(text: str) -> str:
    """Convert text to a safe directory name."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '_', text)
    return text.strip('_')
