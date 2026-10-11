"""Data models shared across DullE."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ActionType(str, Enum):
    """How a step should be executed."""
    CLI = "cli"          # Run a shell command
    GUI = "gui"          # Screenshot-driven interaction
    HYBRID = "hybrid"    # CLI to set up, GUI to finish
    VERIFY = "verify"    # Take screenshot and verify state
    WAIT = "wait"        # Just wait for something to load


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    NEEDS_INPUT = "needs_input"


@dataclass
class Step:
    """One step in a task chain."""
    index: int
    description: str
    action_type: ActionType = ActionType.HYBRID
    cli_command: str | None = None        # Pre-planned CLI command if any
    status: StepStatus = StepStatus.PENDING
    result: str = ""
    error: str = ""
    retries: int = 0
    started_at: datetime | None = None
    ended_at: datetime | None = None


@dataclass
class ActionResult:
    """Result of executing a single action (CLI or GUI)."""
    success: bool
    output: str = ""
    error: str = ""
    screenshot_b64: str | None = None     # Attached screenshot if taken
    action_type: str = ""                 # What was done
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskResult:
    """Result of a complete multi-step task."""
    command: str
    steps: list[Step] = field(default_factory=list)
    completed: bool = False
    total_cost_usd: float = 0.0
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: datetime | None = None

    @property
    def success_rate(self) -> float:
        done = [s for s in self.steps if s.status != StepStatus.PENDING]
        if not done:
            return 0.0
        ok = sum(1 for s in done if s.status == StepStatus.SUCCESS)
        return ok / len(done)

    @property
    def duration_s(self) -> float:
        end = self.ended_at or datetime.now()
        return (end - self.started_at).total_seconds()
