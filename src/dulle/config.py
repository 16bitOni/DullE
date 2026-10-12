"""Configuration for DullE agent — single OpenAI-compatible endpoint.

All values come from the .env file (prefix: DULLE_).
Defaults here are empty or safe fallbacks — nothing is hardcoded.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Loaded from .env file and environment variables (prefix: DULLE_)."""

    # ── API connection ───────────────────────────────────────────
    api_key: str = ""
    base_url: str = ""

    # ── Model routing ────────────────────────────────────────────
    planner_model: str = ""
    executor_model: str = ""
    executor_model_heavy: str = ""
    verifier_model: str = ""

    # ── Agent behavior ───────────────────────────────────────────
    max_iterations: int = 40
    max_steps: int = 20
    max_tokens: int = 4096
    step_timeout_s: float = 120.0

    # ── Execution mode ───────────────────────────────────────────
    execution_mode: str = "hybrid"

    # ── Shell safety ─────────────────────────────────────────────
    shell: str = "cmd"
    shell_timeout_s: float = 30.0
    require_shell_confirmation: bool = True
    enable_shell_blocklist: bool = True
    max_output_chars: int = 5000

    # ── Screenshot ───────────────────────────────────────────────
    max_long_edge: int = 1568
    max_total_pixels: int = 1_150_000
    screenshot_format: str = "png"
    jpeg_quality: int = 80

    # ── Safety ───────────────────────────────────────────────────
    require_confirmation: bool = True
    enable_blocklist: bool = True
    enable_audit_trail: bool = True
    audit_trail_dir: str = "audit_trail"
    max_cost_per_task_usd: float = 3.0

    # ── Knowledge base ───────────────────────────────────────────
    knowledge_file: str = "knowledge.yaml"

    # ── Logging ──────────────────────────────────────────────────
    log_level: str = "INFO"
    log_file: str = "dulle.log"
    verbose: bool = False

    model_config = {"env_file": ".env", "env_prefix": "DULLE_"}
