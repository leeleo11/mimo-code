# MiMo Code

Terminal AI coding assistant powered by [Xiaomi MiMo](https://platform.xiaomimimo.com) models.

A CLI-native Agent that reads, writes, edits, and searches code. Uses MiMo-V2.5-Pro's tool calling capability to form a full **read → analyze → execute → review** Agent loop.

## Features

- **Agent Tool Calling** — read_file, write_file, edit_file, search_code, list_dir, run_shell
- **Multi-turn Agent Loop** — model autonomously chains tool calls (up to 8 rounds per user message)
- **Streaming Chat** — real-time token streaming with rich Markdown rendering + syntax highlighting
- **Multi-modal Input** — `@screenshot.png` for MiMo-V2.5 / MiMo-V2-Omni image analysis
- **Real Token Tracking** — parses API `usage` field instead of char-count estimation
- **Session Persistence** — save/load conversations as JSON, including tool call history
- **Multi-model** — MiMo-V2-Flash / V2.5-Pro / V2.5 / V2-Omni, switch at runtime
- **One-shot Mode** — `mimo -c "question"` for scripting and CI integration

## Installation

```bash
git clone https://github.com/leeleo11/mimo-code.git
cd mimo-code
pip install -r requirements.txt
```

| Package | Purpose |
|---------|---------|
| [httpx](https://pypi.org/project/httpx/) | HTTP streaming client for MiMo API |
| [rich](https://pypi.org/project/rich/) | Terminal UI — colors, panels, live-rendering Markdown |

## Quick Start

### 1. Get a MiMo API key

Register at [platform.xiaomimimo.com](https://platform.xiaomimimo.com), create an API key from the Subscription Management page.

### 2. Set your API key

```bash
export MIMO_API_KEY=your-key-here
```

### 3. Start chatting

```bash
# Agent mode with Pro model (recommended)
python main.py -m pro

# Simple chat (no tools, faster)
python main.py --no-agent

# With multi-modal model for image analysis
python main.py -m v25

# One-shot: ask a question and exit
python main.py -m pro -c "explain the architecture of main.py"

# Load a previous session
python main.py -s my-session
```

## Agent Mode

When Agent mode is on (default for Pro/V2.5/Omni), MiMo Code provides the model with code manipulation tools:

```
User: Add a DEBUG flag to config.py

MiMo: Let me read the current config file first.
  🔧 read_file({"path":"config.py"})
     → DEFAULT_HOST = "localhost" ...

  🔧 edit_file({"path":"config.py","old_string":"DEFAULT_HOST ...","new_string":"DEBUG = False\n\nDEFAULT_HOST ..."})
     → Modified config.py (1 replacement)

MiMo: Added DEBUG = False at the top of config.py. Set the environment
      variable DEBUG=true to enable debug mode.
```

### Agent Workflow

```
User Input
    │
    ▼
┌─────────────────────┐
│  MiMo API (stream)  │◄── messages + tools
└──────┬──────────────┘
       │
       ▼
  Tool calls in response?
       │
   ┌───┴───┐
   │ YES   │ NO
   ▼       ▼
┌──────┐  ┌──────────┐
│Execute│  │  Output  │
│ tool │  │ directly │
└──┬───┘  └──────────┘
   │
   ▼
┌──────────────────┐
│ Tool result added │
│ to messages      │
└──────┬───────────┘
       │
       ▼
  Back to MiMo API (up to 8 rounds)
```

Each round carries full tool definitions and accumulated context, consuming significant tokens in typical Agent workflows.

## Usage

```
usage: main.py [-h] [-m {flash,pro,v25,omni,tts}] [-c COMMAND]
               [-s SESSION] [--save SAVE] [--api-key API_KEY]
               [--base-url BASE_URL] [-w WORKSPACE] [--tokens]
               [--system SYSTEM] [--no-agent]

Options:
  -m, --model     Model: flash / pro / v25 / omni (default: flash)
  -c, --command   One-shot command (non-interactive mode)
  -s, --session   Load saved session
  --save          Save session on exit
  --no-agent      Disable tool calling (plain chat mode)
  --api-key       MiMo API key (or set MIMO_API_KEY)
  --base-url      Custom API base URL
  -w, --workspace Working directory (default: current)
  --tokens        Show token usage statistics
  --system        Custom system prompt
```

## Interactive Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all available commands |
| `/model <id>` | Switch model (flash / pro / v25 / omni) |
| `/agent [on\|off]` | Toggle Agent tool calling |
| `/tokens` | Show token usage + tool round stats |
| `/clear` | Clear conversation history |
| `/save [name]` | Save current session |
| `/load <name>` | Load a saved session |
| `/list` | List saved sessions |
| `/system <msg>` | Set custom system prompt |
| `/workspace <path>` | Change working directory |
| `/shell <cmd>` | Execute shell command |
| `/quit` | Exit |

### File References

| Syntax | Effect |
|--------|--------|
| `@main.py` | Include file contents in context |
| `@screenshot.png` | Encode image for multi-modal models |
| `@src/**/*.py` | Glob match (up to 5 files) |

## Tools

| Tool | Description | Safety |
|------|-------------|--------|
| `read_file` | Read file contents (text + image) | Read-only |
| `write_file` | Create or overwrite file | File I/O |
| `edit_file` | Find-and-replace in file (unique match required) | File I/O |
| `list_dir` | List directory contents with recursive depth | Read-only |
| `search_code` | Grep across project text files | Read-only |
| `run_shell` | Execute whitelisted read-only commands | Command whitelist |

## Session Storage

Sessions are saved as JSON in `~/.mimo-code/sessions/`:

```
~/.mimo-code/sessions/
├── 20260505-refactor.json   # Full history + tool calls
├── debug-session.json
└── ...
```

## Supported Models

| CLI Flag | Model ID | Context | Best For |
|----------|----------|---------|----------|
| `flash` | mimo-v2-flash | 262K | Quick chat, simple tasks (no tool calling) |
| `pro` | mimo-v2.5-pro | 1M | Agent coding, complex reasoning |
| `v25` | mimo-v2.5 | 1M | Multi-modal (text, image, video, audio) |
| `omni` | mimo-v2-omni | 1M | Multi-modal understanding |

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `MIMO_API_KEY` | MiMo API key (required) |
| `MIMO_BASE_URL` | Custom API base URL (auto-detected if unset) |

## Project Structure

```
mimo-code/
├── main.py           # CLI entry point, REPL, Agent loop, image handling
├── mimo_client.py    # MiMo API client (streaming, tool calls, usage parsing)
├── session.py        # Conversation state, persistence, token tracking
├── tools.py          # Tool definitions + safe executor
├── requirements.txt  # httpx, rich
└── README.md
```

## License

MIT — feel free to use, modify, and distribute.
