"""Automated verification checks for eval tasks.

Each check inspects the system state after the agent finishes
and returns pass/fail with a reason.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from loguru import logger


@dataclass
class CheckResult:
    """Result of a single verification check."""
    check_type: str
    passed: bool
    expected: str
    actual: str
    detail: str = ""


def run_check(check: dict, settings=None) -> CheckResult:
    """Dispatch a check definition to the right verifier."""
    ctype = check.get("type", "")
    try:
        match ctype:
            case "process_running":
                return _check_process_running(check)
            case "process_not_running":
                return _check_process_not_running(check)
            case "file_exists":
                return _check_file_exists(check)
            case "file_not_exists":
                return _check_file_not_exists(check)
            case "window_title":
                return _check_window_title(check)
            case "screen_text":
                return _check_screen_text(check)
            case "cli_output":
                return _check_cli_output(check)
            case _:
                return CheckResult(
                    check_type=ctype, passed=False,
                    expected="valid check type",
                    actual=f"unknown: {ctype}",
                )
    except Exception as exc:
        return CheckResult(
            check_type=ctype, passed=False,
            expected=str(check),
            actual=f"check raised exception: {exc}",
        )


def _run_cmd(cmd: str, timeout: float = 10) -> str:
    """Run a shell command and return stdout."""
    try:
        result = subprocess.run(
            cmd, shell=True,
            capture_output=True, text=True, timeout=timeout,
        )
        return (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return "[timeout]"
    except Exception as exc:
        return f"[error: {exc}]"


def _run_powershell(cmd: str, timeout: float = 10) -> str:
    """Run a PowerShell command directly (avoids cmd.exe quote mangling)."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        return (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return "[timeout]"
    except Exception as exc:
        return f"[error: {exc}]"


# ── Check implementations ────────────────────────────────────

def _check_process_running(check: dict) -> CheckResult:
    process = check["process"]
    output = _run_cmd(f'tasklist /fi "imagename eq {process}" /nh')
    found = process.lower() in output.lower()
    return CheckResult(
        check_type="process_running",
        passed=found,
        expected=f"{process} is running",
        actual=f"{'found' if found else 'not found'} in tasklist",
        detail=output[:200],
    )


def _check_process_not_running(check: dict) -> CheckResult:
    process = check["process"]
    output = _run_cmd(f'tasklist /fi "imagename eq {process}" /nh')
    found = process.lower() in output.lower()
    return CheckResult(
        check_type="process_not_running",
        passed=not found,
        expected=f"{process} is NOT running",
        actual=f"{'found' if found else 'not found'} in tasklist",
    )


def _check_file_exists(check: dict) -> CheckResult:
    path = check["path"]
    exists = Path(path).exists()
    return CheckResult(
        check_type="file_exists",
        passed=exists,
        expected=f"file exists: {path}",
        actual=f"{'exists' if exists else 'not found'}",
    )


def _check_file_not_exists(check: dict) -> CheckResult:
    path = check["path"]
    exists = Path(path).exists()
    return CheckResult(
        check_type="file_not_exists",
        passed=not exists,
        expected=f"file does NOT exist: {path}",
        actual=f"{'exists' if exists else 'not found'}",
    )


def _check_window_title(check: dict) -> CheckResult:
    text = check["text"].lower()
    output = _run_powershell(
        "Get-Process | Where-Object {$_.MainWindowTitle} "
        "| Select-Object -ExpandProperty MainWindowTitle"
    )
    titles = output.lower()
    found = text in titles
    return CheckResult(
        check_type="window_title",
        passed=found,
        expected=f"window title contains: {check['text']}",
        actual=f"{'found' if found else 'not found'}",
        detail=output[:300],
    )


def _check_screen_text(check: dict) -> CheckResult:
    """OCR the screen and look for text.

    Uses Windows built-in PowerShell + .NET for basic OCR,
    or falls back to checking window titles if OCR isn't available.
    """
    text = check["text"].lower()

    # Try to use the clipboard trick: Ctrl+A, Ctrl+C on the active window
    # to grab text content. This works for text editors, browsers, etc.
    import pyperclip
    import pyautogui
    import time

    old_clip = ""
    try:
        old_clip = pyperclip.paste()
    except Exception:
        pass

    try:
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "c")
        time.sleep(0.3)
        content = pyperclip.paste().lower()
    except Exception:
        content = ""
    finally:
        try:
            pyperclip.copy(old_clip)
        except Exception:
            pass
        # Deselect
        try:
            pyautogui.click()
        except Exception:
            pass

    if text in content:
        return CheckResult(
            check_type="screen_text",
            passed=True,
            expected=f"screen contains: {check['text']}",
            actual="found via clipboard",
            detail=content[:200],
        )

    # Fallback: check window titles
    title_output = _run_powershell(
        "Get-Process | Where-Object {$_.MainWindowTitle} "
        "| Select-Object -ExpandProperty MainWindowTitle"
    )
    if text in title_output.lower():
        return CheckResult(
            check_type="screen_text",
            passed=True,
            expected=f"screen contains: {check['text']}",
            actual="found in window titles",
            detail=title_output[:200],
        )

    return CheckResult(
        check_type="screen_text",
        passed=False,
        expected=f"screen contains: {check['text']}",
        actual="not found via clipboard or window titles",
        detail=content[:200] if content else title_output[:200],
    )


def _check_cli_output(check: dict) -> CheckResult:
    command = check["command"]
    contains = check["contains"].lower()
    output = _run_cmd(command)
    found = contains in output.lower()
    return CheckResult(
        check_type="cli_output",
        passed=found,
        expected=f"output contains: {check['contains']}",
        actual=f"{'found' if found else 'not found'}",
        detail=output[:300],
    )
