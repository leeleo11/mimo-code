"""
Session management — conversation history, persistence, and token tracking.

Supports:
  - Multi-modal messages (content can be str or list of parts)
  - Tool call and tool result messages (Agent loop)
  - Save/load as JSON in ~/.mimo-code/sessions/
"""

import json
from datetime import datetime
from pathlib import Path


class Session:
    """Manages conversation context: messages, system prompt, and persistence."""

    def __init__(self, sessions_dir: str | None = None):
        self._system = ""
        self._messages: list[dict] = []
        self._tokens_per_turn: list[int] = []
        self._tool_rounds: int = 0
        self._created_at = datetime.now().isoformat()

        if sessions_dir:
            self._dir = Path(sessions_dir)
        else:
            self._dir = Path.home() / ".mimo-code" / "sessions"

        self._dir.mkdir(parents=True, exist_ok=True)

    # ---- System Prompt ----

    def set_system(self, content: str):
        self._system = content

    def get_system(self) -> str:
        return self._system

    # ---- Messages ----

    def add_user(self, content):
        """Add user message. content can be str or list (multi-modal content array)."""
        self._messages.append({"role": "user", "content": content})

    def add_assistant(self, content: str):
        self._messages.append({"role": "assistant", "content": content})
        self._estimate_turn_tokens()

    def add_assistant_with_tools(self, content: str, tool_calls: list[dict]):
        """Add assistant message that includes tool calls (Agent loop)."""
        msg: dict = {"role": "assistant", "content": content or None}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self._messages.append(msg)
        self._tool_rounds += 1

    def add_tool_result(self, tool_call_id: str, tool_name: str, result: str):
        """Add tool execution result to conversation."""
        self._messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result,
        })

    def build_messages(self) -> list[dict]:
        """Build complete message list for API call."""
        msgs: list[dict] = []
        if self._system:
            msgs.append({"role": "system", "content": self._system})
        msgs.extend(self._messages)
        return msgs

    def clear(self) -> int:
        """Clear all messages, return number of turns cleared."""
        turns = len(self._tokens_per_turn)
        self._messages = []
        self._tokens_per_turn = []
        self._tool_rounds = 0
        return turns

    # ---- Token Tracking ----

    def _estimate_turn_tokens(self):
        """Estimate tokens for the most recent turn."""
        if len(self._messages) < 2:
            return
        total_len = 0
        for msg in self._messages[-2:]:
            content = msg.get("content", "")
            if isinstance(content, str):
                total_len += len(content)
            elif isinstance(content, list):
                total_len += len(json.dumps(content))
        est = int(total_len / 4)
        self._tokens_per_turn.append(est)

    def current_usage(self) -> dict:
        """Return token usage stats for current session."""
        total = sum(self._tokens_per_turn)
        return {
            "last_tokens": self._tokens_per_turn[-1] if self._tokens_per_turn else 0,
            "total_tokens": total,
            "turns": len(self._tokens_per_turn),
            "tool_rounds": self._tool_rounds,
        }

    # ---- Persistence ----

    def save(self, name: str | None = None) -> Path:
        """Save current session to disk. Auto-generates name if not provided."""
        if not name:
            name = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self._dir / f"{name}.json"

        data = {
            "version": 2,
            "name": name,
            "created_at": self._created_at,
            "saved_at": datetime.now().isoformat(),
            "system": self._system,
            "messages": self._messages,
            "tokens_per_turn": self._tokens_per_turn,
            "tool_rounds": self._tool_rounds,
        }

        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load(self, name: str):
        """Load a session from disk, replacing current state."""
        path = self._dir / f"{name}.json"
        if not path.exists():
            path = Path(name)
            if not path.exists():
                raise FileNotFoundError(f"Session '{name}' not found")

        data = json.loads(path.read_text(encoding="utf-8"))
        self._system = data.get("system", "")
        self._messages = data.get("messages", [])
        self._tokens_per_turn = data.get("tokens_per_turn", [])
        self._tool_rounds = data.get("tool_rounds", 0)
        self._created_at = data.get("created_at", datetime.now().isoformat())

    def list_sessions(self) -> list[Path]:
        """List all saved sessions, most recent first."""
        return sorted(
            self._dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
