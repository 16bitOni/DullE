"""Hybrid action executor — CLI commands + GUI automation.

The executor receives an action dict from the LLM and carries it out.
Actions can be CLI commands, GUI interactions, or compound hybrids.
"""

from __future__ import annotations

import time
import pyautogui
import pyperclip

from dulle.config import Settings
from dulle.models import ActionResult
from dulle.execution.screen import ScreenCapture
from dulle.execution.shell import ShellResult, launch_app, run_command, check_file_exists


# pyautogui safety: move mouse to top-left corner to abort
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05


class ActionExecutor:
    """Executes actions on the Windows desktop.

    Handles both CLI commands and GUI interactions.
    The LLM sends JSON like:
        {"action": "cli", "command": "start winword"}
        {"action": "click", "coordinate": [342, 198]}
        {"action": "type", "text": "Hello World"}
        {"action": "key", "keys": "ctrl+s"}
        {"action": "screenshot"}
        {"action": "launch_app", "app": "word"}
        {"action": "wait", "seconds": 2}
        {"action": "scroll", "direction": "down", "amount": 3}
    """

    def __init__(self, screen: ScreenCapture, settings: Settings):
        self.screen = screen
        self.settings = settings

    def execute(self, action: dict, confirm_callback=None) -> ActionResult:
        """Execute a single action, return the result."""
        action_type = action.get("action", "").lower()

        try:
            match action_type:
                # ── CLI actions ─────────────────────────────────
                case "cli" | "command" | "shell" | "cmd":
                    return self._do_cli(action, confirm_callback)

                case "launch_app" | "open_app" | "launch" | "open":
                    return self._do_launch_app(action)

                case "check_file" | "file_exists":
                    return self._do_check_file(action)

                # ── Visual actions ──────────────────────────────
                case "screenshot" | "observe" | "look":
                    return self._do_screenshot()

                case "zoom":
                    return self._do_zoom(action)

                # ── Mouse actions ───────────────────────────────
                case "click" | "left_click":
                    return self._do_click(action, button="left")

                case "right_click":
                    return self._do_click(action, button="right")

                case "double_click":
                    return self._do_double_click(action)

                case "triple_click":
                    return self._do_triple_click(action)

                case "drag":
                    return self._do_drag(action)

                case "mouse_move" | "move":
                    return self._do_mouse_move(action)

                case "scroll":
                    return self._do_scroll(action)

                # ── Keyboard actions ────────────────────────────
                case "type" | "type_text":
                    return self._do_type(action)

                case "key" | "hotkey" | "press":
                    return self._do_key(action)

                # ── Timing ──────────────────────────────────────
                case "wait" | "sleep":
                    return self._do_wait(action)

                # ── Compound ────────────────────────────────────
                case "done" | "complete" | "finished":
                    return ActionResult(
                        success=True, output="Task marked as complete.",
                        action_type="done",
                    )

                case _:
                    return ActionResult(
                        success=False,
                        error=f"Unknown action type: {action_type}",
                        action_type=action_type,
                    )

        except pyautogui.FailSafeException:
            return ActionResult(
                success=False,
                error="FAILSAFE triggered — mouse moved to corner. Aborting.",
                action_type=action_type,
            )
        except Exception as exc:
            return ActionResult(
                success=False,
                error=f"Action '{action_type}' failed: {exc}",
                action_type=action_type,
            )

    # ── CLI action handlers ──────────────────────────────────────

    def _do_cli(self, action: dict, confirm_callback) -> ActionResult:
        command = action.get("command", "")
        if not command:
            return ActionResult(success=False, error="No command provided.", action_type="cli")

        result: ShellResult = run_command(
            command, self.settings,
            confirm_callback=confirm_callback,
        )
        return ActionResult(
            success=result.success,
            output=result.output,
            error=result.stderr if not result.success else "",
            action_type="cli",
            details={"command": command, "exit_code": result.exit_code,
                     "duration_s": result.duration_s},
        )

    def _do_launch_app(self, action: dict) -> ActionResult:
        """Launch any app — passes whatever the model provides directly to start."""
        app_name = action.get("app", action.get("name", ""))
        if not app_name:
            return ActionResult(success=False, error="No app name.", action_type="launch_app")

        result = launch_app(app_name, self.settings)
        time.sleep(1.0)
        return ActionResult(
            success=result.success,
            output=f"Launched {app_name}" if result.success else result.stderr,
            error="" if result.success else result.stderr,
            action_type="launch_app",
            details={"app": app_name, "command": result.command},
        )

    def _do_check_file(self, action: dict) -> ActionResult:
        path = action.get("path", "")
        exists = check_file_exists(path, self.settings)
        return ActionResult(
            success=True,
            output=f"File {'EXISTS' if exists else 'NOT FOUND'}: {path}",
            action_type="check_file",
            details={"path": path, "exists": exists},
        )

    # ── Visual action handlers ───────────────────────────────────

    def _do_screenshot(self) -> ActionResult:
        b64 = self.screen.capture()
        return ActionResult(
            success=True,
            output="Screenshot captured.",
            screenshot_b64=b64,
            action_type="screenshot",
        )

    def _do_zoom(self, action: dict) -> ActionResult:
        region = action.get("region", [])
        if len(region) != 4:
            return ActionResult(success=False, error="Zoom needs [x0, y0, x1, y1].", action_type="zoom")
        b64 = self.screen.capture_region(*region)
        return ActionResult(
            success=True, output="Zoomed region captured.",
            screenshot_b64=b64, action_type="zoom",
        )

    # ── Mouse action handlers ────────────────────────────────────

    def _do_click(self, action: dict, button: str = "left") -> ActionResult:
        coord = action.get("coordinate") or action.get("coords")
        if coord and len(coord) == 2:
            x, y = self.screen.to_screen(coord[0], coord[1])
            pyautogui.click(x, y, button=button)
            return ActionResult(success=True, output=f"Clicked ({x}, {y}).", action_type=f"{button}_click")
        else:
            pyautogui.click(button=button)
            return ActionResult(success=True, output="Clicked at cursor.", action_type=f"{button}_click")

    def _do_double_click(self, action: dict) -> ActionResult:
        coord = action.get("coordinate") or action.get("coords")
        if coord and len(coord) == 2:
            x, y = self.screen.to_screen(coord[0], coord[1])
            pyautogui.doubleClick(x, y)
        else:
            pyautogui.doubleClick()
        return ActionResult(success=True, output="Double-clicked.", action_type="double_click")

    def _do_triple_click(self, action: dict) -> ActionResult:
        coord = action.get("coordinate") or action.get("coords")
        if coord and len(coord) == 2:
            x, y = self.screen.to_screen(coord[0], coord[1])
            pyautogui.click(x, y, clicks=3)
        else:
            pyautogui.click(clicks=3)
        return ActionResult(success=True, output="Triple-clicked.", action_type="triple_click")

    def _do_drag(self, action: dict) -> ActionResult:
        start = action.get("start", action.get("from"))
        end = action.get("coordinate", action.get("to"))
        if not start or not end:
            return ActionResult(success=False, error="Drag needs 'start' and 'coordinate'.", action_type="drag")
        sx, sy = self.screen.to_screen(start[0], start[1])
        ex, ey = self.screen.to_screen(end[0], end[1])
        pyautogui.moveTo(sx, sy)
        pyautogui.drag(ex - sx, ey - sy, duration=0.4)
        return ActionResult(success=True, output=f"Dragged ({sx},{sy}) → ({ex},{ey}).", action_type="drag")

    def _do_mouse_move(self, action: dict) -> ActionResult:
        coord = action.get("coordinate") or action.get("coords")
        if not coord:
            return ActionResult(success=False, error="mouse_move needs 'coordinate'.", action_type="mouse_move")
        x, y = self.screen.to_screen(coord[0], coord[1])
        pyautogui.moveTo(x, y)
        return ActionResult(success=True, output=f"Moved to ({x}, {y}).", action_type="mouse_move")

    def _do_scroll(self, action: dict) -> ActionResult:
        direction = action.get("direction", "down")
        amount = action.get("amount", 3)
        coord = action.get("coordinate")
        if coord:
            x, y = self.screen.to_screen(coord[0], coord[1])
            pyautogui.moveTo(x, y)
        scroll_val = amount if direction == "up" else -amount
        if direction in ("up", "down"):
            pyautogui.scroll(scroll_val)
        else:
            pyautogui.hscroll(amount if direction == "right" else -amount)
        return ActionResult(success=True, output=f"Scrolled {direction} by {amount}.", action_type="scroll")

    # ── Keyboard action handlers ─────────────────────────────────

    def _do_type(self, action: dict) -> ActionResult:
        text = action.get("text", "")
        if not text:
            return ActionResult(success=False, error="No text to type.", action_type="type")

        if text.isascii() and not any(c in text for c in '\t'):
            # Plain ASCII — type directly, no clipboard involved
            pyautogui.write(text, interval=0.02)
        else:
            # Unicode or special chars — must use clipboard
            self._type_via_clipboard(text)

        return ActionResult(
            success=True,
            output=f"Typed: \"{text[:80]}{'...' if len(text) > 80 else ''}\"",
            action_type="type",
        )

    def _do_key(self, action: dict) -> ActionResult:
        keys = action.get("keys", action.get("text", ""))
        if not keys:
            return ActionResult(success=False, error="No keys specified.", action_type="key")
        repeat = action.get("repeat", 1)
        key_parts = [k.strip() for k in keys.split("+")]
        for _ in range(repeat):
            pyautogui.hotkey(*key_parts)
            time.sleep(0.05)
        return ActionResult(success=True, output=f"Pressed {keys} x{repeat}.", action_type="key")

    # ── Timing ───────────────────────────────────────────────────

    def _do_wait(self, action: dict) -> ActionResult:
        seconds = min(action.get("seconds", action.get("duration", 1)), 30)
        time.sleep(seconds)
        return ActionResult(success=True, output=f"Waited {seconds}s.", action_type="wait")

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _type_via_clipboard(text: str):
        """Type Unicode text via clipboard with verification."""
        old = ""
        try:
            old = pyperclip.paste()
        except Exception:
            pass

        pyperclip.copy(text)
        time.sleep(0.15)

        # Verify clipboard actually holds our text before pasting
        try:
            current = pyperclip.paste()
            if current != text:
                # Retry the copy
                pyperclip.copy(text)
                time.sleep(0.25)
        except Exception:
            pass

        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.15)

        try:
            pyperclip.copy(old)
        except Exception:
            pass
