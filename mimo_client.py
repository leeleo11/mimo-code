"""
MiMo API client — OpenAI-compatible interface for Xiaomi MiMo models.

Supports:
  - Streaming chat with tool calling (Agent loop)
  - Real token usage parsing from API response
  - Image encoding for multi-modal models (MiMo-V2.5, MiMo-V2-Omni)
  - Multiple model variants with auto-detected base URLs
"""

import base64
import json as _json
import os
from dataclasses import dataclass
from typing import Generator

import httpx


MODEL_CONFIGS = {
    "flash": {
        "id": "mimo-v2-flash",
        "name": "MiMo-V2-Flash",
        "context_window": "262K",
        "description": "Fast, lightweight — good for chat & quick tasks",
        "default_base": "https://api.xiaomimimo.com/v1",
    },
    "pro": {
        "id": "mimo-v2.5-pro",
        "name": "MiMo-V2.5-Pro",
        "context_window": "100万 Token",
        "description": "Flagship agent model — best for complex coding & reasoning",
        "default_base": "https://api.xiaomimimo.com/v1",
    },
    "v25": {
        "id": "mimo-v2.5",
        "name": "MiMo-V2.5",
        "context_window": "100万 Token",
        "description": "All-modal model — text, image, video, audio",
        "default_base": "https://api.xiaomimimo.com/v1",
    },
    "omni": {
        "id": "mimo-v2-omni",
        "name": "MiMo-V2-Omni",
        "context_window": "100万 Token",
        "description": "Multi-modal understanding",
        "default_base": "https://api.xiaomimimo.com/v1",
    },
    "tts": {
        "id": "mimo-v2-tts",
        "name": "MiMo-V2-TTS",
        "context_window": "N/A",
        "description": "Text-to-speech synthesis",
        "default_base": "https://api.xiaomimimo.com/v1",
    },
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


@dataclass
class UsageStats:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class MiMoClient:
    """OpenAI-compatible client for Xiaomi MiMo API."""

    def __init__(
        self,
        api_key: str,
        model: str = "flash",
        base_url: str | None = None,
        workspace: str = ".",
        timeout: float = 120.0,
    ):
        self.api_key = api_key
        self.workspace = workspace
        self.timeout = timeout
        self.usage = UsageStats()

        if model in MODEL_CONFIGS:
            self._model_key = model
        else:
            matched = next((k for k, c in MODEL_CONFIGS.items() if c["id"] == model), None)
            if matched:
                self._model_key = matched
            else:
                print(f"警告: 未知模型 '{model}'，使用默认 flash")
                self._model_key = "flash"

        cfg = MODEL_CONFIGS[self._model_key]

        if base_url:
            self.base_url = base_url.rstrip("/")
        elif os.environ.get("MIMO_BASE_URL"):
            self.base_url = os.environ["MIMO_BASE_URL"].rstrip("/")
        else:
            self.base_url = cfg["default_base"]

        self.model_id = cfg["id"]
        self.context_window = cfg["context_window"]
        self._is_token_plan = "token-plan" in self.base_url
        self._endpoint = f"{self.base_url}/chat/completions"

    # ---- Model Management ----

    def model_display_name(self) -> str:
        cfg = MODEL_CONFIGS[self._model_key]
        return f"{cfg['name']} ({cfg['description']})"

    @property
    def model_key(self) -> str:
        return self._model_key

    def supports_multimodal(self) -> bool:
        """Check if current model supports image input."""
        return self._model_key in ("v25", "omni")

    def set_model(self, model: str):
        if model not in MODEL_CONFIGS:
            raise ValueError(f"Unknown model: {model}. Available: {list(MODEL_CONFIGS.keys())}")
        self._model_key = model
        self.model_id = MODEL_CONFIGS[model]["id"]
        self.context_window = MODEL_CONFIGS[model]["context_window"]
        if not os.environ.get("MIMO_BASE_URL"):
            self.base_url = MODEL_CONFIGS[model]["default_base"]
            self._is_token_plan = "token-plan" in self.base_url
            self._endpoint = f"{self.base_url}/chat/completions"

    def set_workspace(self, path: str):
        self.workspace = path

    # ---- Image Encoding ----

    @staticmethod
    def encode_image(path) -> dict | None:
        """Encode an image file as a base64 data URL for multi-modal API input."""
        import mimetypes as _mimetypes
        from pathlib import Path as _Path

        path = _Path(path)
        if not path.exists() or not path.is_file():
            return None

        ext = path.suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            return None

        mime_type = _mimetypes.guess_type(str(path))[0] or f"image/{ext[1:]}"
        try:
            with open(path, "rb") as f:
                data = base64.b64encode(f.read()).decode("utf-8")
            return {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{data}",
                    "detail": "auto",
                },
            }
        except Exception:
            return None

    # ---- Chat ----

    def chat_stream(self, messages: list[dict], **kwargs) -> Generator[str, None, None]:
        """Simple streaming chat — yields text tokens. For one-shot / backward compat."""
        for event in self.chat(messages, **kwargs):
            if event["type"] == "text":
                yield event["content"]

    def chat(
        self, messages: list[dict], tools: list[dict] | None = None, **kwargs
    ) -> Generator[dict, None, None]:
        """Stream chat with tool calling support.

        Yields:
          {"type": "text", "content": "..."}       — text token
          {"type": "tool_calls", "tool_calls": [...]} — complete tool calls at stream end
        """
        payload = {
            "model": self.model_id,
            "messages": messages,
            "stream": True,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7),
        }
        if tools:
            payload["tools"] = tools

        # Estimate input tokens as fallback
        input_text = "".join(
            m["content"] if isinstance(m.get("content"), str)
            else _json.dumps(m.get("content", ""))
            for m in messages
        )
        est_input = int(len(input_text) / 4.0)

        try:
            with httpx.stream(
                "POST",
                self._endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                timeout=self.timeout,
            ) as response:
                response.raise_for_status()

                text_content = ""
                pending_tool_calls: dict[int, dict] = {}

                for line in response.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break

                    try:
                        chunk = _json.loads(data)
                    except _json.JSONDecodeError:
                        continue

                    # ---- Real Usage Stats (Phase 1.2) ----
                    if "usage" in chunk:
                        real = chunk["usage"]
                        self.usage.prompt_tokens = real.get("prompt_tokens", 0)
                        self.usage.completion_tokens = real.get("completion_tokens", 0)
                        self.usage.total_tokens = real.get("total_tokens", 0)

                    choices = chunk.get("choices", [{}])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})

                    # ---- Text Content ----
                    if delta.get("content"):
                        text_content += delta["content"]
                        yield {"type": "text", "content": delta["content"]}

                    # ---- Tool Calls (Phase 2.2: stream accumulation) ----
                    for tc in delta.get("tool_calls", []):
                        idx = tc["index"]
                        if idx not in pending_tool_calls:
                            pending_tool_calls[idx] = {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        entry = pending_tool_calls[idx]
                        if tc.get("id"):
                            entry["id"] = tc["id"]
                        if tc.get("function", {}).get("name"):
                            entry["function"]["name"] += tc["function"]["name"]
                        if tc.get("function", {}).get("arguments"):
                            entry["function"]["arguments"] += tc["function"]["arguments"]

                # ---- Emit accumulated tool calls ----
                if pending_tool_calls:
                    yield {"type": "tool_calls", "tool_calls": list(pending_tool_calls.values())}

                # ---- Fallback usage estimation if API didn't return usage ----
                if self.usage.total_tokens == 0:
                    est_completion = int(len(text_content) / 4.0)
                    self.usage.prompt_tokens += est_input
                    self.usage.completion_tokens += est_completion
                    self.usage.total_tokens += est_input + est_completion

        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"API 请求失败 ({e.response.status_code}): {e.response.text[:500]}"
            )
        except httpx.RequestError as e:
            raise RuntimeError(f"网络请求失败: {e}")

    def estimate_tokens(self, text: str) -> int:
        return int(len(text) / 4.0)
