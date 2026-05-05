# MiMo Code

Terminal AI coding assistant powered by [Xiaomi MiMo](https://platform.xiaomimimo.com) models.

A CLI-native Agent that reads, writes, edits, and searches code — built for the [MiMo Orbit](https://100t.xiaomimimo.com) creator incentive program. Uses MiMo-V2.5-Pro's tool calling to form a full **read → analyze → execute → review** Agent loop.

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

### 1. Get a free MiMo API key

Apply at the **[MiMo Orbit incentive program](https://100t.xiaomimimo.com)** — 100 trillion free tokens, deadline **May 28, 2026**.

After approval, create your API key at **Subscription Management** in the [MiMo Platform](https://platform.xiaomimimo.com).

### 2. Set your API key

```bash
export MIMO_API_KEY=your-tp-key-here
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
python main.py -m pro -c "解释 main.py 的架构设计"

# Load a previous session
python main.py -s my-session
```

## Agent Mode

When Agent mode is on (default for Pro/V2.5/Omni), MiMo Code provides the model with code manipulation tools:

```
User: 帮我在 config.py 中添加一个 DEBUG 开关

MiMo: Let me read the current config file first.
  🔧 read_file({"path":"config.py"})
     → DEFAULT_HOST = "localhost" ...

  🔧 edit_file({"path":"config.py","old_string":"DEFAULT_HOST ...","new_string":"DEBUG = False\n\nDEFAULT_HOST ..."})
     → 已修改 config.py（1 处替换）

MiMo: 已在 config.py 顶部添加 `DEBUG = False`。你可以通过设置环境变量
      `DEBUG=true` 来开启调试模式。
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
  响应中有 tool_calls？
       │
   ┌───┴───┐
   │ YES   │ NO
   ▼       ▼
┌──────┐  ┌──────────┐
│执行工具│  │ 直接输出  │
└──┬───┘  └──────────┘
   │
   ▼
┌──────────────────┐
│ 工具结果加入 messages │
│ role: tool        │
└──────┬───────────┘
       │
       ▼
  回到 MiMo API（最多 8 轮）
```

Each round carries full tool definitions and accumulated context, consuming **5-50K tokens per user message** in typical Agent workflows.

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

## Token Consumption Scenarios

Typical usage patterns for assessing MiMo Orbit application needs:

| Scenario | Token Usage | Description |
|----------|-------------|-------------|
| Simple chat | 500-2K | One-shot Q&A, no tools |
| Agent single tool call | 3K-8K | read_file or search_code + response |
| Agent multi-tool chain | 8K-30K | 2-4 tools in sequence |
| Full-project analysis | 50K-200K | Multiple files loaded via @references |
| Multi-modal analysis | 5K-20K | Image + text input, code generation |
| Extended coding session | 50K-500K | 10+ Agent turns accumulating context |

The Agent loop model of **read → analyze → edit → verify** consumes **5-10x more tokens** than simple chat because each iteration re-sends the full tool definitions and accumulated conversation history.

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

Base URL auto-detection:
- `tp-*` keys → `token-plan-cn.xiaomimimo.com` (free tier)
- `sk-*` keys → `api.xiaomimimo.com` (pay-per-use)

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

---

Built with [MiMo API](https://platform.xiaomimimo.com) · Apply for tokens at [100t.xiaomimimo.com](https://100t.xiaomimimo.com)
