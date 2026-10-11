"""Safe shell execution layer for Windows CMD / PowerShell.

This is the CLI backbone of DullE's hybrid approach. Instead of clicking
the Start menu to open Word, we run `start winword`. Instead of navigating
File Explorer, we run `dir` and `copy`.

Safety is enforced at three levels:
  1. Blocklist — patterns that are NEVER allowed (format, del /s, reg delete, …)
  2. Allowlist — known-safe read-only commands that run without confirmation
  3. Confirmation gate — everything else asks the user before running
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass

from dulle.config import Settings


# ── Blocklist: commands that are NEVER executed ─────────────────

BLOCKED_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\bformat\s+[a-zA-Z]:",           # Format a drive
        r"\bdel\s+/[sS]",                   # Recursive delete
        r"\brmdir\s+/[sS]",                 # Recursive directory delete
        r"\brd\s+/[sS]",                    # Recursive directory delete (alias)
        r"\brm\s+-r",                        # Unix-style recursive delete
        r"\breg\s+(delete|add)",             # Registry modifications
        r"\bnet\s+user\b.*/(delete|add)",    # User account changes
        r"\bnet\s+stop\b",                   # Stop services
        r"\bshutdown\b",                     # System shutdown/restart
        r"\brestart-computer\b",             # PowerShell restart
        r"\bstop-computer\b",               # PowerShell shutdown
        r"\bbcdedit\b",                      # Boot config editing
        r"\bdiskpart\b",                     # Disk partitioning
        r"\bsfc\b",                          # System file checker
        r"\bdism\b",                         # Deployment image servicing
        r"\btakeown\b",                      # Take file ownership
        r"\bicacls\b.*/(grant|remove|deny)", # Permission changes
        r"\bpowershell\b.*-enc",             # Encoded powershell (obfuscation)
        r"\bcertutil\b.*-urlcache",          # Download via certutil
        r"\bbitsadmin\b.*transfer",          # Stealthy downloads
        r"\bwmic\b.*delete",                 # WMI deletion
        r"\btaskkill\s+/f\s+/im\s+(explorer|csrss|lsass|svchost|winlogon)", # Kill critical processes
    ]
]

# ── Allowlist: read-only commands that run without confirmation ──

ALLOWED_COMMANDS: set[str] = {
    # File inspection (read-only)
    "dir", "type", "find", "findstr", "where", "tree",
    "more", "sort", "fc",
    # System info (read-only)
    "echo", "set", "ver", "hostname", "whoami", "systeminfo",
    "date", "time", "path", "cls",
    # Process inspection
    "tasklist", "wmic process list",
    # Network inspection
    "ipconfig", "ping", "nslookup", "netstat",
    # App launching (safe — opens a window, doesn't modify files)
    "start",
    # PowerShell read-only
    "get-process", "get-childitem", "get-content", "get-date",
    "get-location", "test-path", "get-item", "get-itemproperty",
    "measure-object", "select-string",
}

# ── Write commands that need confirmation ────────────────────────

WRITE_COMMANDS: set[str] = {
    "copy", "xcopy", "robocopy", "move", "ren", "rename",
    "mkdir", "md", "del", "erase", "rd", "rmdir",
    "attrib", "mklink",
    # PowerShell write
    "new-item", "copy-item", "move-item", "remove-item",
    "rename-item", "set-content", "add-content", "out-file",
}


@dataclass
class ShellResult:
    """Result of running a shell command."""
    command: str
    exit_code: int
    stdout: str
    stderr: str
    blocked: bool = False
    blocked_reason: str = ""
    confirmed: bool = True
    duration_s: float = 0.0

    @property
    def success(self) -> bool:
        return not self.blocked and self.exit_code == 0

    @property
    def output(self) -> str:
        """Combined stdout + stderr, truncated."""
        parts = []
        if self.stdout.strip():
            parts.append(self.stdout.strip())
        if self.stderr.strip():
            parts.append(f"[stderr] {self.stderr.strip()}")
        return "\n".join(parts) or "(no output)"


def _get_first_token(cmd: str) -> str:
    """Extract the first command word (lowercased)."""
    stripped = cmd.strip()
    # Handle things like: cmd /c "..."
    if stripped.lower().startswith("cmd /c"):
        stripped = stripped[6:].strip().strip('"')
    if stripped.lower().startswith("powershell -command"):
        stripped = stripped[19:].strip().strip('"')
    # Get first word
    token = stripped.split()[0] if stripped.split() else ""
    return token.lower().strip('"').strip("'")


def check_blocked(command: str) -> str | None:
    """Return a reason string if the command is blocked, else None."""
    for pattern in BLOCKED_PATTERNS:
        if pattern.search(command):
            return f"Blocked by safety rule: {pattern.pattern}"
    return None


def check_needs_confirmation(command: str) -> bool:
    """Return True if the command modifies state and needs user OK."""
    first = _get_first_token(command)
    # Allowed commands run freely
    if first in ALLOWED_COMMANDS:
        return False
    # Write commands always need confirmation
    if first in WRITE_COMMANDS:
        return True
    # Unknown commands need confirmation too
    return True


def run_command(
    command: str,
    settings: Settings,
    skip_confirmation: bool = False,
    confirm_callback=None,
) -> ShellResult:
    """Execute a shell command with full safety checks.

    Args:
        command: The command string to run.
        settings: DullE settings.
        skip_confirmation: Skip the confirmation gate (for allowlisted cmds).
        confirm_callback: A callable(command, reason) -> bool that asks the user.
                         If None and confirmation is needed, the command is blocked.
    """
    # ── Step 1: Blocklist check ──────────────────────────────────
    if settings.enable_shell_blocklist:
        reason = check_blocked(command)
        if reason:
            return ShellResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr=reason,
                blocked=True,
                blocked_reason=reason,
            )

    # ── Step 2: Confirmation gate ────────────────────────────────
    needs_confirm = (
        settings.require_shell_confirmation
        and not skip_confirmation
        and check_needs_confirmation(command)
    )

    if needs_confirm:
        if confirm_callback is None:
            return ShellResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr="Command needs confirmation but no callback provided.",
                confirmed=False,
            )
        if not confirm_callback(command, "This command modifies the system."):
            return ShellResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr="User declined to run this command.",
                confirmed=False,
            )

    # ── Step 3: Execute ──────────────────────────────────────────
    shell_exe = "cmd" if settings.shell == "cmd" else "powershell"
    shell_flag = "/c" if settings.shell == "cmd" else "-Command"

    start = time.time()
    try:
        result = subprocess.run(
            [shell_exe, shell_flag, command],
            capture_output=True,
            text=True,
            timeout=settings.shell_timeout_s,
            cwd=None,  # Uses current working directory
        )
        duration = time.time() - start

        stdout = result.stdout
        stderr = result.stderr

        # Truncate long output
        if len(stdout) > settings.max_output_chars:
            stdout = stdout[: settings.max_output_chars] + "\n... (truncated)"
        if len(stderr) > settings.max_output_chars:
            stderr = stderr[: settings.max_output_chars] + "\n... (truncated)"

        return ShellResult(
            command=command,
            exit_code=result.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_s=duration,
        )

    except subprocess.TimeoutExpired:
        duration = time.time() - start
        return ShellResult(
            command=command,
            exit_code=-1,
            stdout="",
            stderr=f"Command timed out after {settings.shell_timeout_s}s",
            duration_s=duration,
        )

    except Exception as exc:
        duration = time.time() - start
        return ShellResult(
            command=command,
            exit_code=-1,
            stdout="",
            stderr=f"Execution error: {exc}",
            duration_s=duration,
        )


# ── Convenience helpers ──────────────────────────────────────────

def launch_app(app_command: str, settings: Settings) -> ShellResult:
    """Launch an application via `start`. Always allowed, no confirmation."""
    cmd = f'start "" {app_command}'
    return run_command(cmd, settings, skip_confirmation=True)


def check_file_exists(filepath: str, settings: Settings) -> bool:
    """Check if a file exists (read-only, no confirmation)."""
    result = run_command(f'if exist "{filepath}" (echo EXISTS) else (echo MISSING)', settings, skip_confirmation=True)
    return "EXISTS" in result.stdout


def list_directory(path: str, settings: Settings) -> ShellResult:
    """List files in a directory (read-only)."""
    return run_command(f'dir /b "{path}"', settings, skip_confirmation=True)


def get_running_apps(settings: Settings) -> ShellResult:
    """Get list of running window titles."""
    cmd = 'powershell -Command "Get-Process | Where-Object {$_.MainWindowTitle} | Select-Object -Property MainWindowTitle | Format-Table -HideTableHeaders"'
    return run_command(cmd, settings, skip_confirmation=True)


# ── App launch shortcuts ─────────────────────────────────────────

APP_COMMANDS: dict[str, str] = {
    # Microsoft Office
    "word":        "winword",
    "excel":       "excel",
    "powerpoint":  "powerpnt",
    "outlook":     "outlook",
    "onenote":     "onenote",
    # Browsers
    "chrome":      "chrome",
    "firefox":     "firefox",
    "edge":        "msedge",
    # Communication
    "whatsapp":    'shell:AppsFolder\\5319275A.WhatsAppDesktop_cv1g1gnamwfma!App',
    "telegram":    'shell:AppsFolder\\TelegramMessenger.TelegramDesktop_t4vj0pshhgkwm!App',
    "discord":     "discord",
    "teams":       'shell:AppsFolder\\MSTeams_8wekyb3d8bbwe!MSTeams',
    # Utilities
    "notepad":     "notepad",
    "calculator":  "calc",
    "paint":       "mspaint",
    "explorer":    "explorer",
    "cmd":         "cmd",
    "powershell":  "powershell",
    "terminal":    "wt",
    "settings":    "ms-settings:",
    "snipping":    "SnippingTool",
}


def launch_known_app(app_name: str, settings: Settings) -> ShellResult | None:
    """Launch an app by friendly name. Returns None if not recognized."""
    key = app_name.lower().strip()
    cmd = APP_COMMANDS.get(key)
    if cmd is None:
        # Try fuzzy match
        for name, command in APP_COMMANDS.items():
            if name in key or key in name:
                cmd = command
                break
    if cmd is None:
        return None
    return launch_app(cmd, settings)
