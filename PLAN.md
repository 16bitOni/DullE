# DullE — Windows Computer Use Agent: Ground-Up Build Plan

> A complete beginner-friendly architecture and implementation plan for building a
> Windows desktop automation agent using a **multi-model hybrid** approach:
> DeepSeek (planning), Qwen-VL (vision execution), Claude Sonnet 4.6 (verification).
> **Hybrid CLI + Vision**: uses shell commands for speed, screenshots for GUI-only tasks.
>
> **Status: v0.1 code is written.** See `src/dulle/` for the implementation.

---

## Table of Contents

1. [What Is Computer Use?](#1-what-is-computer-use)
2. [How It Works End-to-End](#2-how-it-works-end-to-end)
3. [Architecture Overview](#3-architecture-overview)
4. [Tech Stack](#4-tech-stack)
5. [The 17 Member Tools](#5-the-17-member-tools)
6. [The Agentic Loop](#6-the-agentic-loop)
7. [Screenshot Capture and Coordinate Scaling on Windows](#7-screenshot-capture-and-coordinate-scaling-on-windows)
8. [Executing Actions on Windows](#8-executing-actions-on-windows)
9. [Task Decomposition and Chaining](#9-task-decomposition-and-chaining)
10. [Guardrails and Safety](#10-guardrails-and-safety)
11. [Evaluation Metrics and Observability](#11-evaluation-metrics-and-observability)
12. [Performance Optimization](#12-performance-optimization)
13. [Project Folder Structure](#13-project-folder-structure)
14. [Phased Implementation Roadmap](#14-phased-implementation-roadmap)
15. [Worked Example: "Write a Letter, Save as PDF, Send on WhatsApp"](#15-worked-example)
16. [Cost Estimation](#16-cost-estimation)
17. [Risks and Mitigations](#17-risks-and-mitigations)
18. [References](#18-references)

---

## 1. What Is Computer Use?

Computer use is a Claude API feature that lets Claude **see your screen** and **control your
computer** the same way a human does: by looking at screenshots, clicking buttons, typing text,
scrolling, and pressing keyboard shortcuts.

Unlike traditional automation (scripted macros, Selenium, Win32 API calls), computer use is
**vision-driven**. Claude does not need to know the internal structure of an application. It
looks at the pixels on screen, reasons about what it sees, and issues actions. This means it
can operate any GUI application: Word, WhatsApp Desktop, a web browser, file explorer,
anything with a visual interface.

**Key mental model:**

```
You (the orchestrator)          Claude (the brain)
  |                                |
  |  1. Send screenshot ---------->|
  |                                |  2. Claude sees the screen,
  |                                |     decides what to do
  |  3. <-- Returns actions -------|     (click here, type this)
  |                                |
  |  4. Execute actions on         |
  |     the real desktop           |
  |                                |
  |  5. Take new screenshot ------>|
  |                                |  6. Observe result, decide next
  |  ... loop until task done ...  |
```

Your code is the **hands**. Claude is the **eyes and brain**. The API call shuttles
screenshots up and actions down in a loop.

---

## 2. How It Works End-to-End

Here is the full lifecycle of a single computer use session:

### Step 1: You declare the computer toolset

```python
tools = [
    {"type": "computer_toolset_20260801"}
]
```

One line. This gives Claude access to all 17 member tools (screenshot, click, type, etc.).
No beta header needed. No schema to write.

### Step 2: You send a message with the user's task

```python
messages = [
    {"role": "user", "content": "Open Microsoft Word and type 'Hello World'"}
]
```

### Step 3: Claude responds with tool_use blocks

Claude does not execute anything. It returns **instructions** in the form of `tool_use`
blocks:

```json
{
  "type": "tool_use",
  "id": "toolu_01ABC...",
  "name": "screenshot",
  "toolset_name": "computer",
  "input": {}
}
```

Every computer action carries `"toolset_name": "computer"`.

### Step 4: You execute the action and return the result

For a screenshot, you capture the screen and return the image. For a click, you move the
mouse and click, then return `"OK"`. Every result **must** echo `"toolset_name": "computer"`.

### Step 5: Loop

You append Claude's response and your tool results to the message history and call the API
again. Claude sees the new screenshot, reasons about what happened, and issues the next
action. This continues until Claude decides the task is done (stop_reason: "end_turn").

---

## 3. Architecture Overview

```
+------------------------------------------------------------------+
|                         DullE Agent                               |
|                                                                   |
|  +------------------+    +------------------+    +--------------+ |
|  |  Task Planner    |    |  Agentic Loop    |    |  Evaluator   | |
|  |  (decomposes     |--->|  (screenshot ->  |--->|  (did each   | |
|  |   user command   |    |   Claude call -> |    |   step       | |
|  |   into steps)    |    |   execute ->     |    |   succeed?)  | |
|  |                  |    |   repeat)        |    |              | |
|  +------------------+    +--------+---------+    +--------------+ |
|                                   |                               |
|                    +--------------+--------------+                |
|                    |                             |                |
|             +------v------+            +--------v--------+       |
|             | Screenshot  |            | Action Executor |       |
|             | Capture     |            | (pyautogui /    |       |
|             | (mss/Pillow)|            |  pynput)        |       |
|             +-------------+            +-----------------+       |
|                                                                   |
|  +------------------+    +------------------+    +--------------+ |
|  |  Guardrails      |    |  Logger /        |    |  Config      | |
|  |  (confirmation,  |    |  Observability   |    |  Manager     | |
|  |   blocklist,     |    |  (token cost,    |    |              | |
|  |   rollback)      |    |   latency, etc.) |    |              | |
|  +------------------+    +------------------+    +--------------+ |
+------------------------------------------------------------------+
         |                          |
         v                          v
  +-------------+          +------------------+
  | Claude API  |          | Windows Desktop  |
  | (Anthropic) |          | (the real screen)|
  +-------------+          +------------------+
```

### Components

| Component | Responsibility |
|-----------|---------------|
| **Task Planner** | Takes a natural language command and breaks it into a sequence of high-level steps Claude can execute one at a time. |
| **Agentic Loop** | The core loop: take screenshot, send to Claude, receive actions, execute them, repeat. |
| **Screenshot Capture** | Captures the Windows screen, scales it to fit Claude's image limits, returns base64 PNG. |
| **Action Executor** | Translates Claude's tool_use blocks into real Windows input events (mouse moves, clicks, keystrokes). |
| **Guardrails** | Safety checks: confirmation prompts for destructive actions, blocklisted operations, rollback capability. |
| **Evaluator** | After each step, verifies the expected outcome (e.g., "is Word open now?"). |
| **Logger / Observability** | Tracks every API call, token usage, latency, screenshots, actions, and outcomes. |
| **Config Manager** | Stores settings: API key, model choice, effort level, safety mode, etc. |

---

## 4. Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Language** | Python 3.11+ | Best Anthropic SDK support, rich ecosystem for desktop automation. |
| **Claude SDK** | `anthropic` (latest) | Official Python SDK. Handles auth, streaming, tool runner. |
| **Model** | `claude-opus-5-5` (default) | Best balance of capability and cost for computer use. Switch to `claude-sonnet-5-5` for faster/cheaper runs once stable. |
| **Screenshot capture** | `mss` + `Pillow` | `mss` is the fastest cross-platform screen grabber. `Pillow` handles resize and PNG encoding. |
| **Mouse/Keyboard** | `pyautogui` | Simple API for clicks, typing, key combos. Handles coordinate scaling. |
| **Keyboard (advanced)** | `pynput` | Lower-level control when pyautogui falls short (held keys, modifier combos). |
| **Logging** | `structlog` or `loguru` | Structured JSON logs for every action and API call. |
| **Config** | `pydantic-settings` | Type-safe settings from `.env` files. |
| **Testing** | `pytest` | Unit tests for action handlers, integration tests for the loop. |
| **Async (future)** | `asyncio` + `anthropic.AsyncAnthropic` | For non-blocking API calls if building a UI later. |

### Install command

```bash
pip install anthropic mss Pillow pyautogui pynput structlog pydantic-settings loguru
```

---

## 5. The 17 Member Tools

When you declare `{"type": "computer_toolset_20260801"}`, Claude gets access to these
17 tools. You do not define them; you just handle the execution.

### Visual tools (return images)

| Tool | Input | What it does | Your handler returns |
|------|-------|-------------|---------------------|
| `screenshot` | `{}` | Capture the full display | base64 PNG image block |
| `zoom` | `region: [x0, y0, x1, y1]` | Capture a region at full resolution | base64 PNG image block |

### Mouse tools (return "OK")

| Tool | Input | What it does |
|------|-------|-------------|
| `left_click` | `coordinate?: [x, y]`, `text?: modifiers` | Left click at position |
| `right_click` | same | Right click |
| `middle_click` | same | Middle click |
| `double_click` | same | Double click (open files, select words) |
| `triple_click` | same | Triple click (select lines/paragraphs) |
| `left_click_drag` | `start_coordinate: [x, y]`, `coordinate: [x, y]` | Click-drag (move windows, select regions) |
| `mouse_move` | `coordinate: [x, y]` | Move cursor without clicking |
| `left_mouse_down` | `{}` | Press and hold left button |
| `left_mouse_up` | `{}` | Release left button |
| `cursor_position` | `{}` | Report current cursor position |
| `scroll` | `scroll_direction`, `scroll_amount`, `coordinate?` | Scroll up/down/left/right |

### Keyboard tools (return "OK")

| Tool | Input | What it does |
|------|-------|-------------|
| `type` | `text: string` | Type literal text at keyboard focus |
| `key` | `text: combo`, `repeat?: 1-100` | Press key combination (e.g., `"ctrl+s"`) |
| `hold_key` | `text: key`, `duration: seconds` | Hold a key for a duration |

### Timing tool

| Tool | Input | What it does |
|------|-------|-------------|
| `wait` | `duration: seconds (max 300)` | Pause before next action |

---

## 6. The Agentic Loop

This is the heart of DullE. Here is the complete loop in pseudocode:

```
function run_task(user_command):
    messages = [system_prompt, {role: "user", content: user_command}]
    
    for iteration in range(MAX_ITERATIONS):
        response = claude.messages.create(
            model    = MODEL,
            tools    = [computer_toolset, bash_tool, text_editor],
            messages = messages,
            max_tokens = 4096,
            thinking = {type: "adaptive"},
            output_config = {effort: "high"},
        )
        
        # Append Claude's response to history
        messages.append({role: "assistant", content: response.content})
        
        # Check if Claude is done
        if response.stop_reason == "end_turn":
            return SUCCESS
        
        if response.stop_reason == "refusal":
            return handle_refusal(response)
        
        # Process tool calls
        tool_results = []
        failed = False
        
        for block in response.content:
            if block.type != "tool_use":
                continue
            
            if block.toolset_name == "computer":
                result = execute_computer_action(block, failed)
                if result.is_error:
                    failed = True
                tool_results.append(result)
        
        # Send results back
        messages.append({role: "user", content: tool_results})
    
    return TIMEOUT
```

### Key rules

- **Sequential execution for computer actions**: When Claude returns multiple tool_use
  blocks, execute them in order. Stop at the first failure.
- **Always echo `toolset_name`**: Every tool_result for a computer action must include
  `"toolset_name": "computer"`.
- **Handle `pause_turn`**: If Claude's server-side loop hits 10 iterations, you get
  `stop_reason: "pause_turn"`. Re-send the conversation to continue.
- **Cap iterations**: Set a MAX_ITERATIONS (e.g., 50) to prevent infinite loops.

### The system prompt

The system prompt is critical. It tells Claude what it can do, what OS it is on, and what
guardrails to follow:

```python
SYSTEM_PROMPT = """You are DullE, a Windows desktop automation agent.

Environment:
- Operating system: Windows 11
- Screen resolution: {width}x{height} pixels
- Available applications: Microsoft Word, WhatsApp Desktop, File Explorer,
  Chrome, and all standard Windows applications.

Rules:
1. Always take a screenshot first to observe the current state before acting.
2. After performing an action, take a screenshot to verify the result.
3. If something looks wrong, stop and describe the issue rather than guessing.
4. Never close applications the user didn't ask you to close.
5. For file operations, always verify the save location before writing.
6. When typing text, verify the cursor is in the correct field first.
7. If a dialog box appears unexpectedly, screenshot it and describe it before
   dismissing.
8. Prefer keyboard shortcuts over mouse clicks when both work (faster).

Task execution strategy:
- Break the task into clear steps.
- Execute one step at a time.
- Verify each step before moving to the next.
- If a step fails, try an alternative approach before giving up.
"""
```

---

## 7. Screenshot Capture and Coordinate Scaling on Windows

### The scaling problem

Claude accepts screenshots up to **1568px** on the long edge (for Opus 5.5 and most models).
A typical Windows display is 1920x1080 or higher. You must scale down.

But Claude's actions return coordinates **in the scaled screenshot's pixel space**. You must
scale those coordinates back up to the real display before executing them.

### Implementation

```python
import base64
import math
from io import BytesIO
import mss
from PIL import Image


class ScreenCapture:
    """Captures Windows screen and handles coordinate scaling."""

    # Claude's image limits
    MAX_LONG_EDGE = 1568       # pixels
    MAX_TOTAL_PIXELS = 1_150_000  # ~1.15 megapixels

    def __init__(self):
        self.sct = mss.mss()
        monitor = self.sct.monitors[1]  # Primary monitor
        self.screen_width = monitor["width"]
        self.screen_height = monitor["height"]
        self.scale = self._compute_scale()

    def _compute_scale(self) -> float:
        """Compute the scale factor to fit within Claude's image limits."""
        w, h = self.screen_width, self.screen_height
        long_edge = max(w, h)
        total_pixels = w * h

        long_edge_scale = self.MAX_LONG_EDGE / long_edge
        total_pixels_scale = math.sqrt(self.MAX_TOTAL_PIXELS / total_pixels)

        return min(1.0, long_edge_scale, total_pixels_scale)

    def capture(self) -> str:
        """Capture screen, scale it, return base64 PNG."""
        raw = self.sct.grab(self.sct.monitors[1])
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

        # Scale down
        new_w = int(self.screen_width * self.scale)
        new_h = int(self.screen_height * self.scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)

        # Encode to base64 PNG
        buffer = BytesIO()
        img.save(buffer, format="PNG", optimize=True)
        return base64.standard_b64encode(buffer.getvalue()).decode("utf-8")

    def scale_to_screen(self, x: int, y: int) -> tuple[int, int]:
        """Convert Claude's coordinates (scaled) to real screen coordinates."""
        return (int(x / self.scale), int(y / self.scale))

    def capture_region(self, x0: int, y0: int, x1: int, y1: int) -> str:
        """Capture a region (for zoom). Coordinates are in Claude's space."""
        # Convert to real screen coords
        rx0, ry0 = self.scale_to_screen(x0, y0)
        rx1, ry1 = self.scale_to_screen(x1, y1)

        region = {"left": rx0, "top": ry0, "width": rx1 - rx0, "height": ry1 - ry0}
        raw = self.sct.grab(region)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

        # Scale to fit the same dimensions as a full screenshot
        new_w = int(self.screen_width * self.scale)
        new_h = int(self.screen_height * self.scale)
        img.thumbnail((new_w, new_h), Image.LANCZOS)

        buffer = BytesIO()
        img.save(buffer, format="PNG", optimize=True)
        return base64.standard_b64encode(buffer.getvalue()).decode("utf-8")
```

### Windows DPI awareness

Windows with display scaling (125%, 150%) reports logical pixels that differ from physical
pixels. You must make your Python process DPI-aware:

```python
import ctypes

# Call this ONCE at startup, before any screen capture
ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor DPI aware
```

Without this, `mss` captures a blurry, incorrectly-sized image and all coordinates will be
wrong.

---

## 8. Executing Actions on Windows

### The Action Executor

```python
import pyautogui
import time

# Safety: pyautogui's built-in failsafe (move mouse to corner to abort)
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05  # Small pause between actions for stability


class ActionExecutor:
    """Translates Claude's tool_use blocks into real Windows actions."""

    def __init__(self, screen: ScreenCapture):
        self.screen = screen

    def execute(self, name: str, tool_input: dict) -> str | list:
        """Execute a computer action, return result content."""
        match name:
            # --- Visual tools ---
            case "screenshot":
                return self._screenshot()

            case "zoom":
                region = tool_input["region"]
                return self._zoom(region)

            # --- Mouse tools ---
            case "left_click":
                return self._click(tool_input, button="left")

            case "right_click":
                return self._click(tool_input, button="right")

            case "middle_click":
                return self._click(tool_input, button="middle")

            case "double_click":
                return self._double_click(tool_input)

            case "triple_click":
                return self._triple_click(tool_input)

            case "left_click_drag":
                return self._drag(tool_input)

            case "mouse_move":
                coord = tool_input["coordinate"]
                x, y = self.screen.scale_to_screen(coord[0], coord[1])
                pyautogui.moveTo(x, y)
                return "OK"

            case "left_mouse_down":
                pyautogui.mouseDown(button="left")
                return "OK"

            case "left_mouse_up":
                pyautogui.mouseUp(button="left")
                return "OK"

            case "cursor_position":
                pos = pyautogui.position()
                # Convert back to Claude's coordinate space
                cx = int(pos[0] * self.screen.scale)
                cy = int(pos[1] * self.screen.scale)
                return f"[{cx}, {cy}]"

            case "scroll":
                return self._scroll(tool_input)

            # --- Keyboard tools ---
            case "type":
                pyautogui.typewrite(tool_input["text"], interval=0.02)
                return "OK"

            case "key":
                combo = tool_input["text"]
                repeat = tool_input.get("repeat", 1)
                for _ in range(repeat):
                    pyautogui.hotkey(*combo.split("+"))
                return "OK"

            case "hold_key":
                # pynput is better for held keys
                from pynput.keyboard import Controller, Key
                kb = Controller()
                key_name = tool_input["text"]
                duration = tool_input["duration"]
                key = getattr(Key, key_name, key_name)
                kb.press(key)
                time.sleep(duration)
                kb.release(key)
                return "OK"

            # --- Timing ---
            case "wait":
                time.sleep(tool_input["duration"])
                return "OK"

            case _:
                raise ValueError(f"Unknown computer tool: {name}")

    def _screenshot(self):
        b64 = self.screen.capture()
        return [{"type": "image", "source": {
            "type": "base64", "media_type": "image/png", "data": b64
        }}]

    def _zoom(self, region):
        b64 = self.screen.capture_region(*region)
        return [{"type": "image", "source": {
            "type": "base64", "media_type": "image/png", "data": b64
        }}]

    def _click(self, tool_input, button):
        coord = tool_input.get("coordinate")
        if coord:
            x, y = self.screen.scale_to_screen(coord[0], coord[1])
            pyautogui.click(x, y, button=button)
        else:
            pyautogui.click(button=button)
        return "OK"

    def _double_click(self, tool_input):
        coord = tool_input.get("coordinate")
        if coord:
            x, y = self.screen.scale_to_screen(coord[0], coord[1])
            pyautogui.doubleClick(x, y)
        else:
            pyautogui.doubleClick()
        return "OK"

    def _triple_click(self, tool_input):
        coord = tool_input.get("coordinate")
        if coord:
            x, y = self.screen.scale_to_screen(coord[0], coord[1])
            pyautogui.click(x, y, clicks=3)
        else:
            pyautogui.click(clicks=3)
        return "OK"

    def _drag(self, tool_input):
        start = tool_input["start_coordinate"]
        end = tool_input["coordinate"]
        sx, sy = self.screen.scale_to_screen(start[0], start[1])
        ex, ey = self.screen.scale_to_screen(end[0], end[1])
        pyautogui.moveTo(sx, sy)
        pyautogui.drag(ex - sx, ey - sy, duration=0.5)
        return "OK"

    def _scroll(self, tool_input):
        direction = tool_input["scroll_direction"]
        amount = tool_input["scroll_amount"]
        coord = tool_input.get("coordinate")

        if coord:
            x, y = self.screen.scale_to_screen(coord[0], coord[1])
            pyautogui.moveTo(x, y)

        scroll_map = {
            "up": amount,
            "down": -amount,
            "left": -amount,  # horizontal
            "right": amount,
        }

        if direction in ("up", "down"):
            pyautogui.scroll(scroll_map[direction])
        else:
            pyautogui.hscroll(scroll_map[direction])
        return "OK"
```

### Windows-specific gotchas

| Issue | Solution |
|-------|---------|
| **UAC dialogs** | pyautogui cannot click on elevated (admin) dialogs. Run DullE as admin if needed. |
| **Display scaling (125%, 150%)** | Call `SetProcessDpiAwareness(2)` at startup. |
| **Lock screen** | If Windows locks, screenshots return black. Detect and warn. |
| **Multiple monitors** | Use `mss.monitors[1]` for primary. Support multi-monitor later. |
| **pyautogui.typewrite vs write** | `typewrite` only handles ASCII. For Unicode text (accented chars, emoji), use `pyperclip` + `ctrl+v` instead. |

### Unicode text input (important for real content)

```python
import pyperclip

def type_unicode(text: str):
    """Type any text including Unicode by pasting from clipboard."""
    old_clipboard = pyperclip.paste()
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.1)
    pyperclip.copy(old_clipboard)  # Restore clipboard
```

---

## 9. Task Decomposition and Chaining

For complex commands like *"Open Word, write a letter about how I love my mother, save it
as PDF in Downloads, send to mom on WhatsApp"*, Claude needs a plan.

### Strategy: Two-phase approach

**Phase A: Planning.** Send the user's command to Claude (without computer use tools) and
ask it to decompose into numbered steps. This is fast and cheap.

**Phase B: Execution.** Feed each step to the agentic loop with computer use tools enabled.
After each step completes, verify before moving to the next.

### The Task Planner

```python
PLANNING_PROMPT = """You are a task planner for a Windows desktop automation agent.

Given a user's command, break it into a numbered list of concrete steps that
can be executed one at a time using mouse clicks, keyboard input, and
screenshots on a Windows 11 computer.

Rules:
- Each step should be one clear action or a small group of related actions.
- Include verification steps (e.g., "verify Word is open").
- Include any save/export steps explicitly.
- If a step requires information you don't have (like a phone number or email),
  note it as [NEEDS_INPUT: description].

Example input: "Open Word, write a letter to mom, save as PDF, send on WhatsApp"

Example output:
1. Open Microsoft Word from the Start menu or taskbar.
2. Create a new blank document.
3. Type the letter content addressed to mom.
4. Verify the letter looks correct.
5. Save the document as PDF: File > Save As > choose Downloads folder > 
   change format to PDF > save.
6. Verify the PDF was saved in the Downloads folder.
7. Open WhatsApp Desktop.
8. Find mom's chat (search for "Mom" or the contact name).
9. Attach the PDF file from Downloads.
10. Send the message.
11. Verify the message was sent.

Now break down this command:
"""


async def plan_task(client, user_command: str) -> list[str]:
    """Use Claude to decompose a command into steps."""
    response = client.messages.create(
        model="claude-opus-5-5",
        max_tokens=2000,
        output_config={"effort": "medium"},   # Planning is cheap
        messages=[{
            "role": "user",
            "content": PLANNING_PROMPT + user_command
        }],
    )
    # Parse numbered list from response
    text = response.content[0].text
    steps = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if line and line[0].isdigit():
            # Remove the number prefix
            step = line.split(".", 1)[1].strip() if "." in line else line
            steps.append(step)
    return steps
```

### The Chain Executor

```python
async def execute_chain(client, steps: list[str], screen, executor):
    """Execute a chain of planned steps sequentially."""
    results = []

    for i, step in enumerate(steps):
        print(f"\n--- Step {i+1}/{len(steps)}: {step} ---")

        # Check if this step needs human input
        if "[NEEDS_INPUT:" in step:
            user_input = input(f"  Input needed: {step}\n  > ")
            step = step.replace(
                step[step.index("[NEEDS_INPUT:"):step.index("]")+1],
                user_input
            )

        # Execute the step
        result = run_agentic_loop(
            client=client,
            task=step,
            screen=screen,
            executor=executor,
            max_iterations=30,
        )

        results.append({"step": step, "result": result})

        if result["status"] == "failed":
            print(f"  Step failed: {result['error']}")
            retry = input("  Retry? (y/n): ")
            if retry.lower() == "y":
                result = run_agentic_loop(
                    client=client,
                    task=f"The previous attempt to '{step}' failed. Try again.",
                    screen=screen,
                    executor=executor,
                    max_iterations=30,
                )
                results[-1] = {"step": step, "result": result}

        if result["status"] == "failed":
            print(f"  Chain aborted at step {i+1}.")
            break

    return results
```

---

## 10. Guardrails and Safety

Computer use is powerful and can cause real harm. A misclick or wrong command can delete
files, send wrong messages, or close unsaved work. DullE needs multiple layers of safety.

### Layer 1: Confirmation gates

Require explicit user confirmation before destructive or irreversible actions:

```python
# Actions that require confirmation
CONFIRM_ACTIONS = {
    "send":       "Sending a message or email",
    "delete":     "Deleting a file or content",
    "submit":     "Submitting a form",
    "purchase":   "Making a purchase",
    "sign out":   "Signing out of an account",
    "uninstall":  "Uninstalling software",
    "format":     "Formatting a drive",
    "shutdown":   "Shutting down or restarting",
}

def needs_confirmation(step_text: str) -> str | None:
    """Check if a step requires user confirmation. Returns reason or None."""
    lower = step_text.lower()
    for keyword, reason in CONFIRM_ACTIONS.items():
        if keyword in lower:
            return reason
    return None
```

### Layer 2: Blocklist

Some actions should never be performed, regardless of what the user asks:

```python
BLOCKED_PATTERNS = [
    r"format\s+[a-zA-Z]:",           # Format a drive
    r"del\s+/[sS]",                   # Recursive delete
    r"rm\s+-rf",                      # Recursive delete (bash)
    r"reg\s+delete",                  # Registry deletion
    r"net\s+user.*\/delete",          # Delete user account
    r"shutdown\s+/[sStT]",           # System shutdown/restart
    r"bcdedit",                       # Boot config editing
    r"diskpart",                      # Disk partitioning
]
```

### Layer 3: Application allowlist

Restrict which applications DullE can open and interact with:

```python
ALLOWED_APPS = {
    "Microsoft Word", "Microsoft Excel", "Microsoft PowerPoint",
    "WhatsApp", "Chrome", "Firefox", "Edge",
    "File Explorer", "Notepad", "Paint",
    "Settings",  # Windows Settings
}
```

### Layer 4: Rollback capability

Before each major action, save a checkpoint:

```python
import shutil
from pathlib import Path

class RollbackManager:
    """Saves file backups before modifications."""

    def __init__(self, backup_dir: str = ".dulle_backups"):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(exist_ok=True)
        self.checkpoints = []

    def checkpoint_file(self, filepath: str):
        """Save a copy of a file before modifying it."""
        src = Path(filepath)
        if src.exists():
            dest = self.backup_dir / f"{src.name}.{len(self.checkpoints)}.bak"
            shutil.copy2(src, dest)
            self.checkpoints.append({"original": str(src), "backup": str(dest)})

    def rollback_last(self):
        """Restore the last backed-up file."""
        if self.checkpoints:
            cp = self.checkpoints.pop()
            shutil.copy2(cp["backup"], cp["original"])
            return cp["original"]
        return None
```

### Layer 5: Screenshot audit trail

Save every screenshot to disk for post-run review:

```python
def save_audit_screenshot(b64_data: str, step: int, action: str):
    audit_dir = Path("audit_trail") / datetime.now().strftime("%Y%m%d_%H%M%S")
    audit_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{step:03d}_{action}.png"
    with open(audit_dir / filename, "wb") as f:
        f.write(base64.b64decode(b64_data))
```

### Layer 6: System prompt guardrails

The system prompt (shown in section 6) instructs Claude to:
- Always screenshot before and after actions
- Never close apps the user didn't mention
- Verify save locations before writing
- Stop and describe unexpected dialogs

---

## 11. Evaluation Metrics and Observability

### What to measure

| Metric | What it tells you | How to compute |
|--------|------------------|----------------|
| **Task success rate** | Does DullE actually complete tasks? | `completed_tasks / total_tasks` |
| **Step success rate** | Which individual steps fail most? | `completed_steps / total_steps` per step type |
| **Actions per task** | Is DullE efficient or flailing? | Count tool_use blocks per completed task |
| **Latency per action** | Where is time spent? | Timestamp each API call and action execution |
| **API latency** | How fast is Claude responding? | Time from API call to response received |
| **Execution latency** | How fast is the local executor? | Time from receiving action to completion |
| **Total task latency** | End-to-end wall time | Start to finish of the full chain |
| **Token cost** | How much does each task cost? | Sum `input_tokens` + `output_tokens` from `response.usage` |
| **Screenshot count** | Are we sending too many images? | Count screenshot tool results per task |
| **Error rate** | How often do actions fail? | Count `is_error: true` results |
| **Retry rate** | How often does Claude retry? | Count re-attempts at the same step |
| **Refusal rate** | How often does Claude refuse? | Count `stop_reason: "refusal"` |

### The Metrics Tracker

```python
import time
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ActionMetric:
    action_name: str
    started_at: float
    ended_at: float
    success: bool
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""

    @property
    def latency_ms(self) -> float:
        return (self.ended_at - self.started_at) * 1000


@dataclass
class TaskMetrics:
    task_description: str
    started_at: datetime = field(default_factory=datetime.now)
    actions: list[ActionMetric] = field(default_factory=list)
    completed: bool = False

    @property
    def total_tokens(self) -> int:
        return sum(a.input_tokens + a.output_tokens for a in self.actions)

    @property
    def total_cost_usd(self) -> float:
        """Approximate cost using claude-opus-5-5 pricing."""
        input_tok = sum(a.input_tokens for a in self.actions)
        output_tok = sum(a.output_tokens for a in self.actions)
        return (input_tok * 4.0 / 1_000_000) + (output_tok * 20.0 / 1_000_000)

    @property
    def total_latency_s(self) -> float:
        if not self.actions:
            return 0
        return self.actions[-1].ended_at - self.actions[0].started_at

    def summary(self) -> dict:
        return {
            "task": self.task_description,
            "completed": self.completed,
            "total_actions": len(self.actions),
            "successful_actions": sum(1 for a in self.actions if a.success),
            "total_latency_s": round(self.total_latency_s, 2),
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(self.total_cost_usd, 4),
            "screenshots_sent": sum(
                1 for a in self.actions if a.action_name == "screenshot"
            ),
        }
```

### Logging structure

Every API call and action should produce a structured log entry:

```json
{
  "timestamp": "2026-10-11T14:23:01.123Z",
  "event": "api_call",
  "model": "claude-opus-5-5",
  "input_tokens": 12543,
  "output_tokens": 342,
  "latency_ms": 2340,
  "stop_reason": "tool_use",
  "tool_calls": ["screenshot"],
  "task_step": 3,
  "iteration": 7
}
```

---

## 12. Performance Optimization

### Strategy 1: Prompt caching

Screenshots dominate token cost (~1000-1800 tokens each). Use prompt caching to avoid
re-processing the system prompt and tool definitions on every turn:

```python
# Place a cache breakpoint on the system prompt
system_with_cache = [
    {
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"}
    }
]
```

The system prompt and tool definitions are stable across turns, so they hit cache on every
subsequent API call. This cuts input token cost by up to 90% for those tokens.

### Strategy 2: Effort tuning

Not every action needs deep reasoning:

| Situation | Effort level | Why |
|-----------|-------------|-----|
| **Planning** (decomposing the user's command) | `medium` | Planning is a well-defined text task |
| **Execution** (clicking, typing, navigating) | `high` | Needs good visual understanding |
| **Verification** (checking if a step succeeded) | `medium` | Usually a simple yes/no visual check |
| **Recovery** (something went wrong) | `xhigh` | Complex reasoning about what failed |

### Strategy 3: Minimize screenshots

Screenshots are the biggest cost driver. Strategies to reduce them:

- **Don't screenshot after every trivial action.** If Claude types a single key, it can
  reasonably expect the result without a screenshot. Only screenshot after actions where
  the visual result is uncertain.
- **Batch actions before screenshotting.** Claude can issue multiple actions per turn
  (e.g., click a field, type text, press Tab). Execute all, then screenshot once.
- **Prune old screenshots.** Every 25 turns, drop screenshots older than the last 3 from
  the message history to save context window space.

### Strategy 4: Use keyboard shortcuts over mouse clicks

Keyboard shortcuts are faster and more reliable than finding and clicking UI elements:

| Task | Mouse approach | Keyboard approach |
|------|---------------|------------------|
| Save a file | Click File > Save | `Ctrl+S` |
| Save as PDF | Navigate menus | `Ctrl+Shift+S`, then change format |
| Open Start menu | Click Windows button | `Win` key |
| Switch apps | Click taskbar | `Alt+Tab` |
| Select all text | Triple-click + drag | `Ctrl+A` |
| Copy/Paste | Right-click menus | `Ctrl+C` / `Ctrl+V` |

Encode this preference in the system prompt so Claude reaches for shortcuts first.

### Strategy 5: Smart model selection

```
Task planning      -> claude-sonnet-5-5 (cheap, fast, good enough)
Simple navigation  -> claude-sonnet-5-5
Complex visual UI  -> claude-opus-5-5 (better visual reasoning)
Error recovery     -> claude-opus-5-5
```

Use a router that picks the model based on the current step type.

---

## 13. Project Folder Structure

```
DullE/
├── PLAN.md                    # This document
├── README.md                  # Quick start guide
├── pyproject.toml             # Project config and dependencies
├── .env                       # ANTHROPIC_API_KEY and settings
├── .gitignore
│
├── src/
│   └── dulle/
│       ├── __init__.py
│       ├── main.py            # CLI entry point
│       ├── agent.py           # The agentic loop (core)
│       ├── planner.py         # Task decomposition
│       ├── screen.py          # Screenshot capture + scaling
│       ├── executor.py        # Action execution (pyautogui)
│       ├── guardrails.py      # Safety checks, confirmations
│       ├── rollback.py        # File backup/restore
│       ├── metrics.py         # Token/latency/cost tracking
│       ├── logger.py          # Structured logging
│       ├── config.py          # Settings (pydantic-settings)
│       ├── models.py          # Data classes (ActionResult, etc.)
│       ├── prompts.py         # System prompts and templates
│       └── utils.py           # Unicode typing, DPI awareness
│
├── tests/
│   ├── __init__.py
│   ├── test_screen.py         # Screenshot capture tests
│   ├── test_executor.py       # Action execution tests (mocked)
│   ├── test_planner.py        # Task decomposition tests
│   ├── test_guardrails.py     # Safety check tests
│   └── test_agent.py          # Integration tests
│
├── audit_trail/               # Saved screenshots from runs
│   └── 20261011_142300/
│       ├── 001_screenshot.png
│       ├── 002_left_click.png
│       └── ...
│
└── examples/
    ├── open_word_write.py     # Example: open Word, type text
    ├── save_as_pdf.py         # Example: save document as PDF
    └── send_whatsapp.py       # Example: send file on WhatsApp
```

---

## 14. Phased Implementation Roadmap

### Phase 1: Core Loop + Screenshot (Week 1)

**Goal:** Take a screenshot, send it to Claude, get a response. Prove the round-trip works.

| Task | File | Est. time |
|------|------|-----------|
| Set up project structure (pyproject.toml, src/) | all | 1 hr |
| Implement ScreenCapture with DPI awareness | `screen.py` | 2 hrs |
| Implement the basic agentic loop (no actions yet) | `agent.py` | 3 hrs |
| Handle `tool_result` for screenshot only | `agent.py` | 1 hr |
| Test: send screenshot, Claude describes what it sees | `test_agent.py` | 1 hr |

**Milestone:** Claude can see your desktop and describe what is on screen.

### Phase 2: Mouse and Keyboard Actions (Week 2)

**Goal:** Claude can click, type, scroll, and press keys. Full 17-tool coverage.

| Task | File | Est. time |
|------|------|-----------|
| Implement all 17 action handlers | `executor.py` | 4 hrs |
| Implement Unicode text input (clipboard paste) | `utils.py` | 1 hr |
| Wire action executor into agentic loop | `agent.py` | 2 hrs |
| Handle batch actions (sequential with error stop) | `agent.py` | 1 hr |
| Test: "Open Notepad and type Hello World" | manual | 1 hr |
| Test: "Open Chrome and search for something" | manual | 1 hr |

**Milestone:** Claude can control your computer to do simple single-app tasks.

### Phase 3: Task Planner and Chaining (Week 3)

**Goal:** Claude can break down complex commands and execute multi-step chains.

| Task | File | Est. time |
|------|------|-----------|
| Implement Task Planner | `planner.py` | 3 hrs |
| Implement Chain Executor | `agent.py` | 3 hrs |
| Handle [NEEDS_INPUT] placeholders | `planner.py` | 1 hr |
| Step verification (screenshot after each step) | `agent.py` | 2 hrs |
| Test: "Open Word, write text, save as PDF" | manual | 2 hrs |
| Build CLI entry point | `main.py` | 2 hrs |

**Milestone:** You can type a complex command and watch DullE execute it step by step.

### Phase 4: Guardrails and Evaluation (Week 4)

**Goal:** DullE is safe to use and you can measure its performance.

| Task | File | Est. time |
|------|------|-----------|
| Implement confirmation gates | `guardrails.py` | 2 hrs |
| Implement blocklist | `guardrails.py` | 1 hr |
| Implement application allowlist | `guardrails.py` | 1 hr |
| Implement rollback manager | `rollback.py` | 2 hrs |
| Implement metrics tracker | `metrics.py` | 2 hrs |
| Implement structured logging | `logger.py` | 2 hrs |
| Implement screenshot audit trail | `agent.py` | 1 hr |
| Build evaluation harness (run N tasks, report) | `tests/` | 3 hrs |

**Milestone:** DullE asks before destructive actions, logs everything, and reports metrics.

### Phase 5: Speed Optimization (Week 5)

**Goal:** Make DullE as fast as possible.

| Task | File | Est. time |
|------|------|-----------|
| Add prompt caching (system + tools) | `agent.py` | 2 hrs |
| Add effort tuning per step type | `agent.py` | 2 hrs |
| Add smart screenshot pruning | `agent.py` | 2 hrs |
| Add keyboard shortcut preference to system prompt | `prompts.py` | 1 hr |
| Add model routing (Sonnet for simple, Opus for hard) | `agent.py` | 3 hrs |
| Profile and optimize screenshot capture | `screen.py` | 2 hrs |
| Benchmark: measure 10 tasks before/after | manual | 3 hrs |

**Milestone:** DullE completes the "Word -> PDF -> WhatsApp" chain reliably and efficiently.

### Phase 6 (Stretch): UI and Polish

| Task | Description |
|------|-------------|
| Build a simple terminal UI (rich/textual) | Show live screenshots, step progress, cost |
| Add voice input (whisper) | Speak commands instead of typing |
| Add scheduling | "Every morning, open Outlook and summarize unread emails" |
| Add multi-monitor support | Handle more than one display |
| Package as executable | PyInstaller for easy distribution |

---

## 15. Worked Example

**User command:** "Open Word, write a letter about how I love my mother, save it in the
Downloads folder as a PDF, and send it to Mom on WhatsApp."

### Step 1: Task Planner decomposes the command

```
1. Open Microsoft Word from the Start menu or taskbar.
2. Create a new blank document.
3. Type a heartfelt letter about loving your mother.
4. Review the letter for completeness.
5. Save as PDF: File > Save As > Downloads > change type to PDF > Save.
6. Verify the PDF exists in the Downloads folder.
7. Open WhatsApp Desktop.
8. Search for "Mom" in the contacts/chats.
9. Open the chat with Mom.
10. Click the attachment (paperclip) icon.
11. Select the PDF from the Downloads folder.
12. Send the message.
13. Verify the message was sent (checkmark visible).
```

### Step 2: Agentic loop executes step 1

```
Iteration 1:
  Claude: {"name": "screenshot", "toolset_name": "computer", "input": {}}
  -> We capture the desktop and send it as base64 PNG.

Iteration 2:
  Claude sees the desktop. Decides to click the Start button.
  Claude: {"name": "key", "toolset_name": "computer", "input": {"text": "win"}}
  -> We press the Windows key. Return "OK".

Iteration 3:
  Claude: {"name": "screenshot", ...}
  -> We capture. Start menu is open.

Iteration 4:
  Claude: {"name": "type", "toolset_name": "computer", "input": {"text": "Word"}}
  -> We type "Word" into the Start menu search. Return "OK".

Iteration 5:
  Claude: {"name": "screenshot", ...}
  -> We capture. "Word" app appears in search results.

Iteration 6:
  Claude: {"name": "left_click", ..., "input": {"coordinate": [342, 198]}}
  -> We scale [342, 198] to real screen coords and click. Return "OK".

Iteration 7:
  Claude: {"name": "wait", "input": {"duration": 2}}
  -> Word is loading. We wait 2 seconds.

Iteration 8:
  Claude: {"name": "screenshot", ...}
  -> Word is open. Claude sees the template chooser.

Iteration 9:
  Claude: {"name": "left_click", ..., "input": {"coordinate": [512, 300]}}
  -> Click "Blank document". Return "OK".

Iteration 10:
  Claude: stop_reason = "end_turn"
  -> Step 1 complete. Word is open with a blank document.
```

### Step 3: Execute remaining steps similarly

Steps 2-13 each follow the same screenshot-action-verify loop. The chain executor runs
them one at a time, checking for success after each.

### Estimated performance for this task

| Metric | Estimate |
|--------|----------|
| Total steps | 13 |
| Average iterations per step | 6-10 |
| Total API calls | ~80-130 |
| Screenshots sent | ~40-65 |
| Total input tokens | ~150K-250K |
| Total output tokens | ~10K-20K |
| Estimated cost (Opus 5.5) | $0.80-$1.20 |
| Estimated wall time | 3-6 minutes |
| With Sonnet 5.5 (simpler steps) | $0.40-$0.60, 2-4 minutes |

---

## 16. Cost Estimation

### Per-task costs (Claude Opus 5.5: $4 input / $20 output per MTok)

| Task type | Est. tokens | Est. cost |
|-----------|------------|-----------|
| Simple (open app, type text) | 30K in / 3K out | $0.18 |
| Medium (write doc, save as PDF) | 80K in / 8K out | $0.48 |
| Complex (write + save + send) | 200K in / 15K out | $1.10 |
| Very complex (multi-app workflow) | 400K in / 25K out | $2.10 |

### Monthly cost at different usage levels

| Usage | Tasks/day | Monthly cost (Opus 5.5) | Monthly cost (Sonnet 5.5) |
|-------|-----------|------------------------|--------------------------|
| Light | 5 | ~$30-$50 | ~$15-$25 |
| Medium | 20 | ~$120-$200 | ~$60-$100 |
| Heavy | 50 | ~$300-$500 | ~$150-$250 |

### Cost optimization levers (in order)

1. **Prompt caching** (free win, ~40-60% input cost reduction)
2. **Screenshot pruning** (free win, ~20-30% input reduction)
3. **Effort tuning** (free win, ~15-25% output reduction)
4. **Model routing** (Sonnet for easy steps, Opus for hard ones, ~40% cost reduction)
5. **Smarter planning** (fewer wasted iterations, ~10-20% reduction)

---

## 17. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| **Misclick sends wrong message** | High | Confirmation gate before any "send" action |
| **Deletes important file** | High | Rollback manager backs up files before modification |
| **Infinite loop (Claude stuck)** | Medium | MAX_ITERATIONS cap, cost cap per task |
| **Claude can't find UI element** | Medium | Zoom tool for detailed inspection, retry with different approach |
| **Application not responding** | Medium | Timeout per action, detect "not responding" in title bar |
| **Wrong application in focus** | Medium | Screenshot verification before typing |
| **Screen resolution changes** | Low | Recalculate scale factor on each capture |
| **Windows update dialog blocks** | Low | Detect overlay dialogs, dismiss or escalate |
| **API rate limit** | Low | Exponential backoff, the SDK handles retries |
| **Cost runaway** | Medium | Per-task cost cap, daily budget limit |

---

## 18. References

| Resource | URL |
|----------|-----|
| **Claude Computer Use Docs** | https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool |
| **Claude API Tool Use** | https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview |
| **Anthropic Python SDK** | https://github.com/anthropics/anthropic-sdk-python |
| **pyautogui docs** | https://pyautogui.readthedocs.io/ |
| **mss (screenshot library)** | https://github.com/BoboTiG/python-mss |
| **Pillow (image processing)** | https://pillow.readthedocs.io/ |
| **pynput (keyboard/mouse)** | https://pynput.readthedocs.io/ |
| **Claude Pricing** | https://platform.claude.com/docs/en/about-claude/pricing |
| **Agent Design Patterns** | https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview |

---

## Quick Start Checklist

Once you are ready to start building:

- [ ] Create the project folder and virtual environment
- [ ] Install dependencies: `pip install anthropic mss Pillow pyautogui pynput`
- [ ] Set your API key: `echo ANTHROPIC_API_KEY=sk-ant-... > .env`
- [ ] Build `screen.py` first (Phase 1)
- [ ] Send one screenshot to Claude and verify it describes your desktop
- [ ] Build `executor.py` (Phase 2)
- [ ] Test: "Open Notepad and type Hello"
- [ ] Build `planner.py` and chain execution (Phase 3)
- [ ] Add guardrails (Phase 4)
- [ ] Optimize for speed (Phase 5)
- [ ] Run the full "Word -> PDF -> WhatsApp" chain

---

*Document created: 2026-10-11*
*Project: DullE — Windows Computer Use Agent*
