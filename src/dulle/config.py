"""Configuration for DullE agent — single OpenAI-compatible endpoint."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Loaded from .env file and environment variables (prefix: DULLE_)."""

    # ── API connection (one key, one base URL, multiple models) ──
    api_key: str = ""
    base_url: str = "https://api.example.com/v1"

    # ── Model routing (just change the model name per role) ──────
    planner_model: str = "deepseek-chat"       # Text-only, decomposes tasks
    executor_model: str = "qwen-vl-max"        # Vision model, drives the screen
    verifier_model: str = "claude-sonnet-4-6"  # Confirms critical steps

    # ── Agent behavior ───────────────────────────────────────────
    max_iterations: int = 40         # Max agentic loop iterations per step
    max_steps: int = 20              # Max steps in a chained task
    max_tokens: int = 4096
    step_timeout_s: float = 120.0    # Timeout per step in seconds

    # ── Execution mode ───────────────────────────────────────────
    # "hybrid" = CLI first, vision fallback
    # "vision" = screenshot-only (classic computer use)
    # "cli"    = command-line only (no screenshots)
    execution_mode: str = "hybrid"

    # ── Shell safety ─────────────────────────────────────────────
    shell: str = "cmd"                           # cmd | powershell
    shell_timeout_s: float = 30.0                # Max time per command
    require_shell_confirmation: bool = True       # Ask before write ops
    enable_shell_blocklist: bool = True
    max_output_chars: int = 5000                  # Truncate long output

    # ── Screenshot ───────────────────────────────────────────────
    max_long_edge: int = 1568
    max_total_pixels: int = 1_150_000
    screenshot_format: str = "png"               # png | jpeg
    jpeg_quality: int = 80

    # ── Safety ───────────────────────────────────────────────────
    require_confirmation: bool = True
    enable_blocklist: bool = True
    enable_audit_trail: bool = True
    audit_trail_dir: str = "audit_trail"
    max_cost_per_task_usd: float = 3.0

    # ── Logging ──────────────────────────────────────────────────
    log_level: str = "INFO"
    log_file: str = "dulle.log"
    verbose: bool = False

    model_config = {"env_file": ".env", "env_prefix": "DULLE_"}
