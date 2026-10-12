"""Shim — shell utilities have moved to dulle.execution.shell."""

from dulle.execution.shell import (
    ALLOWED_COMMANDS,
    BLOCKED_PATTERNS,
    WRITE_COMMANDS,
    ShellResult,
    check_blocked,
    check_file_exists,
    check_needs_confirmation,
    get_running_apps,
    launch_app,
    list_directory,
    run_command,
)

__all__ = [
    "ALLOWED_COMMANDS", "BLOCKED_PATTERNS", "WRITE_COMMANDS",
    "ShellResult", "check_blocked", "check_file_exists", "check_needs_confirmation",
    "get_running_apps", "launch_app", "list_directory", "run_command",
]
