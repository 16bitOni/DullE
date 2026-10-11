"""DullE — Windows Computer Use Agent.

Entry point for the CLI. Run with:
    python -m dulle "open word and write a letter"
    python -m dulle              # interactive mode
"""

from __future__ import annotations

import sys

from loguru import logger
from rich.console import Console
from rich.panel import Panel

from dulle.config import Settings
from dulle.screen import enable_dpi_awareness

console = Console()

BANNER = r"""
 ____        _ _ _____
|  _ \ _   _| | | ____|
| | | | | | | | |  _|
| |_| | |_| | | | |___
|____/ \__,_|_|_|_____|  v0.1.0

  Hybrid CLI + Vision Windows Agent
"""


def main():
    """Main entry point."""
    # DPI awareness must be set before any screen capture
    enable_dpi_awareness()

    console.print(BANNER, style="bold cyan")

    # Load settings
    try:
        settings = Settings()
    except Exception as exc:
        console.print(f"[red]Config error:[/] {exc}")
        console.print("Copy .env.example to .env and fill in your API key.")
        sys.exit(1)

    # Validate API key
    if not settings.api_key:
        console.print("[red]No API key configured.[/]")
        console.print("Set your key in .env:")
        console.print("  DULLE_API_KEY=sk-...")
        console.print("  DULLE_BASE_URL=https://your-endpoint.com/v1")
        sys.exit(1)

    # Set up logging
    logger.remove()
    logger.add(
        settings.log_file,
        level=settings.log_level,
        rotation="10 MB",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {message}",
    )
    if settings.verbose:
        logger.add(sys.stderr, level="DEBUG")

    # Print config summary
    _print_config(settings)

    # Import agent here (after DPI awareness is set)
    from dulle.agent import DullEAgent
    agent = DullEAgent(settings)

    # Check for command-line argument
    if len(sys.argv) > 1:
        command = " ".join(sys.argv[1:])
        agent.run(command)
        return

    # Interactive mode
    console.print("[bold green]Interactive mode.[/] Type a command, or 'quit' to exit.\n")

    while True:
        try:
            command = console.input("[bold yellow]DullE>[/] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\nBye!")
            break

        if not command:
            continue
        if command.lower() in ("quit", "exit", "q"):
            console.print("Bye!")
            break

        try:
            result = agent.run(command)
            logger.info(
                f"Task completed={result.completed} "
                f"steps={len(result.steps)} "
                f"duration={result.duration_s:.1f}s"
            )
        except KeyboardInterrupt:
            console.print("\n[yellow]Task interrupted.[/]")
        except Exception as exc:
            console.print(f"\n[red]Error:[/] {exc}")
            logger.exception("Task failed")


def _print_config(settings: Settings):
    lines = [
        f"Endpoint:  {settings.base_url}",
        f"Planner:   {settings.planner_model}",
        f"Executor:  {settings.executor_model}",
        f"Verifier:  {settings.verifier_model}",
        f"Mode:      {settings.execution_mode}",
        f"Shell:     {settings.shell}",
        f"Safety:    confirm={settings.require_confirmation}  blocklist={settings.enable_blocklist}",
    ]
    console.print(Panel(
        "\n".join(lines),
        title="Configuration",
        border_style="blue",
    ))
    console.print()


if __name__ == "__main__":
    main()
