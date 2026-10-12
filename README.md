<div align="center">

```
 ____        _ _ _____
|  _ \ _   _| | | ____|
| | | | | | | | |  _|
| |_| | |_| | | | |___
|____/ \__,_|_|_|_____|
```

# DullE

**Hybrid CLI + Vision Windows Desktop Agent**

Give it a plain-English command. It controls your PC.

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D4?style=flat-square&logo=windows&logoColor=white)](https://microsoft.com/windows)
[![Version](https://img.shields.io/badge/Version-0.1.0-22c55e?style=flat-square)](https://github.com)
[![License](https://img.shields.io/badge/License-MIT-f59e0b?style=flat-square)](LICENSE)
[![uv](https://img.shields.io/badge/Packaged%20with-uv-7c3aed?style=flat-square)](https://docs.astral.sh/uv)

</div>

---

## What is DullE?

DullE is a Windows computer-use agent that understands plain English and executes tasks on your desktop. It uses a **CLI-first, vision-fallback** approach — shell commands for speed, screenshots + mouse/keyboard only when the task truly needs it.

```
uv run dulle "open WhatsApp and send Subho a message saying hello"
uv run dulle "create a folder called Projects in Downloads"
uv run dulle "search for lofi music on YouTube"
uv run dulle "open Word, write a cover letter, save it as PDF"
```

---

## Features

| | Feature | Description |
|---|---|---|
| ⚡ | **CLI-first execution** | Shell commands for apps, files, URLs — no clicking through menus |
| 🧠 | **Multi-model routing** | Cheap text model plans, vision model drives the screen, reliable model verifies |
| 📦 | **Action batching** | Returns sequences of actions in one LLM call — fewer round-trips |
| ❓ | **Asks when unsure** | Pauses mid-task to ask you for clarification when it hits genuine ambiguity |
| 🔍 | **Dynamic app discovery** | Finds any installed app via `Get-StartApps` — no hardcoded paths |
| 🛡️ | **Three-layer safety** | Blocklist, allowlist, and confirmation gate protect against accidents |
| 📓 | **Personal knowledge base** | Teach it facts about your setup — it remembers context across tasks |
| 📊 | **Built-in eval suite** | Run benchmarks, compare runs, track improvement over time |
| 🔁 | **Loop detection** | Automatically detects stuck loops and escalates to a stronger model |
| 📸 | **Full audit trail** | Every screenshot, action, and result saved to disk for replay |

---

## How It Works

```
You: "open WhatsApp and send Subho a message introducing yourself"
         │
         ▼
  ┌──────────────┐
  │   PLANNER    │  Decomposes into steps (text model, fast + cheap)
  │              │  Step 1: [cli]  discover WhatsApp app ID
  │              │  Step 2: [cli]  launch WhatsApp
  │              │  Step 3: [wait] wait for app to load
  │              │  Step 4: [gui]  find Subho and open chat   ← needs_input?
  │              │  Step 5: [gui]  type and send message
  └──────┬───────┘
         │
         ▼
  ┌──────────────┐
  │   EXECUTOR   │  Drives the screen (vision model)
  │              │  • Runs CLI commands directly via cmd.exe
  │              │  • Takes screenshots, decides next action
  │              │  • Batches predictable sequences (click+type+send)
  │              │  • Asks you if it hits genuine ambiguity
  │              │  • Handles popups, errors, loading states
  └──────┬───────┘
         │
         ▼
  ┌──────────────┐
  │   VERIFIER   │  Confirms each step worked (reliable model)
  │              │  Retries if page is still loading
  └──────────────┘
```

---

## Quick Start

### 1 — Install

```bash
git clone https://github.com/yourname/DullE.git
cd DullE
uv sync
```

### 2 — Configure

```bash
copy .env.example .env
# Edit .env — set your API key, base URL, and model names
```

Minimum required in `.env`:

```env
DULLE_API_KEY=your-api-key
DULLE_BASE_URL=https://your-endpoint/v1
DULLE_PLANNER_MODEL=your-text-model
DULLE_EXECUTOR_MODEL=your-vision-model
DULLE_VERIFIER_MODEL=your-reliable-model
```

### 3 — Run

```bash
# Single command
uv run dulle "open notepad and type hello world"

# Interactive mode
uv run dulle

# Auto mode — no confirmation prompts
uv run dulle --auto
uv run dulle -y "create a folder called test in Downloads"
```

---

## Usage

### Interactive mode

```
DullE> open chrome and go to youtube
DullE> search for lofi music
DullE> open word and write a short poem about rain
DullE> quit
```

### Single command

```bash
uv run dulle "open calculator"
uv run dulle "take a screenshot and save it to Desktop"
uv run dulle "open WhatsApp and message Mom saying I'll be late"
```

### Auto mode (skip confirmation prompts)

```bash
uv run dulle --auto
uv run dulle -y "create a folder called Projects in Downloads"
```

### Eval suite

```bash
# Run all tasks
uv run dulle --eval

# Run specific tasks
uv run dulle --eval --tasks notepad_open,calculator_open

# Compare two runs
uv run dulle --eval-compare eval/results/20261012_120000 eval/results/20261012_130000
```

---

## Configuration

All settings in `.env` use the `DULLE_` prefix.

<details>
<summary><b>Full configuration reference</b></summary>

```env
# ── API ─────────────────────────────────────────────────────────
DULLE_API_KEY=                        # Your API key
DULLE_BASE_URL=                       # OpenAI-compatible endpoint

# ── Models ──────────────────────────────────────────────────────
DULLE_PLANNER_MODEL=                  # Text model — plans steps (cheap)
DULLE_EXECUTOR_MODEL=                 # Vision model — drives the screen
DULLE_VERIFIER_MODEL=                 # Reliable model — confirms results
DULLE_EXECUTOR_MODEL_HEAVY=           # Fallback when executor gets stuck

# ── Agent behavior ──────────────────────────────────────────────
DULLE_MAX_ITERATIONS=40               # Max actions per step
DULLE_MAX_STEPS=20                    # Max steps per task
DULLE_STEP_TIMEOUT_S=120.0            # Seconds before a step is abandoned
DULLE_EXECUTION_MODE=hybrid           # hybrid | vision | cli

# ── Shell safety ────────────────────────────────────────────────
DULLE_REQUIRE_SHELL_CONFIRMATION=true # Ask before write commands
DULLE_REQUIRE_CONFIRMATION=true       # Master confirmation toggle
DULLE_ENABLE_SHELL_BLOCKLIST=true     # Block dangerous commands

# ── Screenshot ──────────────────────────────────────────────────
DULLE_SCREENSHOT_FORMAT=png           # png | jpeg
DULLE_MAX_LONG_EDGE=1568              # Resize before sending to model

# ── Knowledge base ──────────────────────────────────────────────
DULLE_KNOWLEDGE_FILE=knowledge.yaml   # Your personal facts file

# ── Audit trail ─────────────────────────────────────────────────
DULLE_ENABLE_AUDIT_TRAIL=true
DULLE_AUDIT_TRAIL_DIR=audit_trail
```

</details>

### Recommended model combos

| Planner | Executor | Verifier | Notes |
|---------|----------|----------|-------|
| `deepseek-chat` | `qwen-vl-max` | `claude-sonnet-4-6` | Best cost/quality |
| `gpt-4o-mini` | `gpt-4o` | `gpt-4o` | OpenAI-only |
| `gemini-2.0-flash` | `gemini-2.5-pro` | `gemini-2.5-pro` | Google-only |
| `claude-haiku-4` | `claude-sonnet-4-6` | `claude-sonnet-4-6` | Anthropic-only |

---

## Safety

Three layers protect against accidents:

### 🚫 Blocklist — never runs, no matter what
`format C:`, `del /s`, `reg delete`, `shutdown`, `diskpart`, `bcdedit`, `rmdir /s`, and more. These patterns are blocked before any command executes.

### ✅ Allowlist — runs freely
Read-only commands like `dir`, `type`, `start`, `tasklist`, `ipconfig`, `echo` — safe by definition, no prompt.

### ⚠️ Confirmation gate — asks before writing

```
  Confirmation needed:
  Command: copy "report.docx" "C:\Users\subha\Downloads\"
  Reason:  This command modifies the system.
  Allow? [y/N]
```

Skip this for a session with `--auto` / `-y`, or permanently with `DULLE_REQUIRE_CONFIRMATION=false` in `.env`.

---

## Knowledge Base

Edit `knowledge.yaml` to teach DullE facts about your setup:

```yaml
- fact: "I have YouTube Premium — no ads, no skip buttons needed"
  tags: [youtube, video, ads]

- fact: "My work Chrome profile is Profile 2"
  tags: [chrome, browser, profile, work]

- fact: "Subho's WhatsApp name is Subho Chattopadhyay"
  tags: [whatsapp, contact, subho]

- fact: "Downloads folder is at C:\Users\subha\Downloads"
  tags: [downloads, folder, path]
```

Relevant entries are automatically retrieved and injected into the planner and executor context at runtime.

---

## Project Structure

```
DullE/
├── .env.example              # Copy to .env and configure
├── pyproject.toml            # Dependencies
├── knowledge.yaml            # Your personal facts
├── eval_tasks.yaml           # Benchmark task definitions
│
├── src/dulle/
│   ├── config.py             # Settings (pydantic, DULLE_ prefix)
│   ├── models.py             # Shared data classes
│   ├── main.py               # CLI entry point + interactive REPL
│   │
│   ├── agent/                # Core orchestration
│   │   ├── core.py           # DullEAgent — plan → execute → verify loop
│   │   ├── steps.py          # Step routing (CLI / GUI / verify / wait)
│   │   ├── batch.py          # Single-action and batch-action execution
│   │   ├── loop_detect.py    # Stuck-loop detection and intervention
│   │   ├── context.py        # Conversation pruning, message builders
│   │   └── audit.py          # On-disk audit trail (screenshots + actions)
│   │
│   ├── llm/                  # LLM client and prompts
│   │   ├── client.py         # LLMClient — retry, token tracking, escalation
│   │   └── prompts.py        # System prompts for planner / executor / verifier
│   │
│   ├── execution/            # What actually runs on the machine
│   │   ├── actions.py        # ActionExecutor — all GUI + CLI action handlers
│   │   ├── shell.py          # Safe shell execution, blocklist/allowlist
│   │   └── screen.py         # Screenshot capture, DPI scaling
│   │
│   ├── planning/             # Task decomposition
│   │   ├── planner.py        # plan_task(), describe_screen()
│   │   └── knowledge.py      # KnowledgeBase — retrieval from knowledge.yaml
│   │
│   └── eval/                 # Evaluation suite
│       ├── runner.py         # Runs tasks, records results
│       ├── checks.py         # Post-task verification (process, file, screen)
│       └── report.py         # Compare runs, show diffs
│
├── eval/results/             # Saved eval run results (JSON)
└── audit_trail/              # Per-task screenshots and action logs
```

---

## Requirements

- **Python** 3.11+
- **Windows** 10 or 11
- **An OpenAI-compatible API endpoint** with at least one vision-capable model
- `uv` for dependency management ([install](https://docs.astral.sh/uv/getting-started/installation/))

---

## How the Agent Handles Surprises

DullE is designed to recover, not crash:

| Situation | What it does |
|-----------|-------------|
| Popup or dialog appears | Reads it, dismisses it, continues the task |
| App is loading | Waits, retries — won't click a spinner |
| CLI command fails | Falls back to GUI automatically |
| Gets stuck in a loop | Detects it, escalates to stronger model |
| Unknown app path | Runs `Get-StartApps` to discover it dynamically |
| Genuine ambiguity | Pauses and asks you before continuing |
| Multiple contacts match | Shows options, waits for your choice |

---

<div align="center">

Made for Windows · Powered by vision models · Built with [uv](https://docs.astral.sh/uv)

</div>
