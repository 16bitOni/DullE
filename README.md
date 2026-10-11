# DullE

Hybrid CLI + Vision Windows desktop automation agent. Give it a plain-English command and it controls your computer — launching apps via shell commands for speed, and using screenshots + mouse/keyboard for GUI-only tasks.

**Multi-model:** routes through a single OpenAI-compatible endpoint. Cheap text model plans the steps, a vision model drives the screen, a reliable model verifies results.

## Quick Start

```bash
# 1. Clone and set up
cd DullE
uv sync

# 2. Configure
copy .env.example .env
# Edit .env — set your API key, base URL, and model names

# 3. Run
uv run dulle "open notepad and type hello world"

# Or interactive mode
uv run dulle

# Or via python directly
uv run python -m dulle
```

`uv sync` reads `pyproject.toml`, creates a `.venv`, and installs everything in one shot. No separate `pip install` needed.

## Configuration

All settings live in `.env` (prefix `DULLE_`):

```env
# Required — your OpenAI-compatible endpoint
DULLE_API_KEY=sk-...
DULLE_BASE_URL=http://127.0.0.1:8787/v1

# Model names (whatever your endpoint serves)
DULLE_PLANNER_MODEL=deepseek-chat           # Plans steps (text-only, cheap)
DULLE_EXECUTOR_MODEL=qwen-vl-max            # Drives the screen (vision)
DULLE_VERIFIER_MODEL=claude-sonnet-4-6      # Verifies results (reliable)
```

To use one model for everything, set all three to the same name.

## How It Works

```
User command
    │
    ▼
┌─────────────┐   "open word, write letter, save as PDF, send on WhatsApp"
│   Planner   │   Decomposes into numbered steps with CLI hints
│ (text model)│   Step 1: start winword        [cli]
└──────┬──────┘   Step 2: type the letter      [gui]
       │          Step 3: File > Save As > PDF  [gui]
       ▼          Step 4: check PDF exists      [cli]
┌─────────────┐   Step 5: open WhatsApp         [cli]
│  Executor   │   Step 6: send the PDF          [gui]
│(vision model)│
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Verifier   │   Confirms each step worked
│(reliable mdl)│
└─────────────┘
```

**CLI-first approach:** launching apps (`start winword`), checking files (`if exist ...`), and creating folders are done through shell commands. Screenshots and mouse/keyboard are only used when the task requires interacting with a GUI.

## Execution Modes

Set `DULLE_EXECUTION_MODE` in `.env`:

| Mode | What it does |
|------|-------------|
| `hybrid` | CLI commands first, screenshots for GUI-only tasks (default, recommended) |
| `vision` | Screenshot-only, classic computer use |
| `cli` | Command-line only, no screenshots |

## Safety

Three layers protect against accidents:

**Blocklist** — dangerous commands are never executed, regardless of what the model asks for:
`format`, `del /s`, `reg delete`, `shutdown`, `diskpart`, `bcdedit`, and more.

**Allowlist** — read-only commands (`dir`, `type`, `start`, `tasklist`, etc.) run without asking.

**Confirmation gate** — everything else (file copies, moves, deletes) prompts you before running:

```
  Confirmation needed:
  Command: copy "letter.pdf" "C:\Users\subha\Downloads\"
  Reason:  This command modifies the system.
  Allow? [y/N]
```

App launching via `start` is always allowed (opens a window, doesn't modify files).

## Project Structure

```
DullE/
├── .env.example          # Copy to .env, fill in your values
├── pyproject.toml        # Dependencies and project config
├── PLAN.md               # Full architecture and implementation plan
├── README.md             # This file
│
├── src/dulle/
│   ├── main.py           # CLI entry point and interactive mode
│   ├── agent.py          # Core loop: plan → execute → verify
│   ├── planner.py        # Decomposes commands into steps
│   ├── executor.py       # Runs actions (CLI + GUI)
│   ├── shell.py          # Safe command execution with blocklist/allowlist
│   ├── screen.py         # Screenshot capture, DPI awareness, coordinate scaling
│   ├── llm.py            # Single OpenAI client, routes by model name
│   ├── prompts.py        # System prompts for planner/executor/verifier
│   ├── models.py         # Data classes (Step, ActionResult, TaskResult)
│   └── config.py         # Settings from .env
│
├── tests/
├── audit_trail/          # Saved screenshots from runs
└── examples/
```

## Known App Shortcuts

The shell module knows how to launch these without navigating the Start menu:

| Name | Command |
|------|---------|
| Word | `start winword` |
| Excel | `start excel` |
| PowerPoint | `start powerpnt` |
| Chrome | `start chrome` |
| Edge | `start msedge` |
| WhatsApp | `start shell:AppsFolder\...` |
| Notepad | `start notepad` |
| File Explorer | `start explorer` |
| Terminal | `start wt` |
| Settings | `start ms-settings:` |

The agent prefers these over clicking through menus — faster and more reliable.

## Requirements

- Python 3.11+
- Windows 10/11
- An OpenAI-compatible API endpoint with access to at least one vision model
- Display scaling awareness (handled automatically)

## Detailed Plan

See [PLAN.md](PLAN.md) for the full architecture document covering:
- All 17 computer use member tools
- Screenshot coordinate scaling math
- The agentic loop in detail
- Guardrails design
- Evaluation metrics
- Performance optimization strategies
- Phased implementation roadmap
- Cost estimates
- Worked example of the full "Word → PDF → WhatsApp" chain
