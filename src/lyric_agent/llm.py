"""LLM provider abstraction layer.

Supports two protocols:
- anthropic: Claude (Anthropic native API)
- openai: Any OpenAI-compatible API (OpenAI, DeepSeek, Qwen, etc.)

Adapted from seatunnel_agent — stripped tool-use wiring,
focused on text generation for batch annotation.
"""

from __future__ import annotations

import json
import threading
import logging
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import Settings

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    reply_text: str
    thinking_text: str = ""
    usage: dict[str, int] = field(default_factory=dict)


class LLMClient:
    """Unified text-generation interface over Anthropic and OpenAI-compatible APIs."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.provider = settings.llm_provider

        timeout = getattr(settings, "llm_timeout", 120) or 120
        if self.provider == "anthropic":
            import anthropic
            self._client = anthropic.Anthropic(api_key=settings.api_key,
                                               timeout=timeout)
        elif self.provider == "openai":
            import openai
            kwargs: dict[str, Any] = {"api_key": settings.api_key,
                                      "timeout": timeout}
            if settings.llm_base_url:
                kwargs["base_url"] = settings.llm_base_url
            self._client = openai.OpenAI(**kwargs)
        else:
            raise ValueError(
                f"Unknown LLM_PROVIDER: '{self.provider}'. "
                "Supported: 'anthropic', 'openai'"
            )

    def generate(
        self,
        system_prompt: str,
        user_message: str,
        on_text_delta: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        messages = [{"role": "user", "content": user_message}]
        if self.provider == "anthropic":
            fn = self._call_anthropic_stream if on_text_delta else self._call_anthropic
            args = (system_prompt, messages, on_text_delta) if on_text_delta else (system_prompt, messages)
            return self._call_with_retry(fn, *args)
        else:
            fn = self._call_openai_stream if on_text_delta else self._call_openai
            args = (system_prompt, messages, on_text_delta) if on_text_delta else (system_prompt, messages)
            return self._call_with_retry(fn, *args)

    def generate_json(
        self,
        system_prompt: str,
        user_message: str,
    ) -> Any:
        resp = self.generate(system_prompt, user_message)
        text = resp.reply_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]  # remove ```json
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return json.loads(text)

    # ------------------------------------------------------------------
    # Retry helper
    # ------------------------------------------------------------------

    def _call_with_retry(
        self,
        fn: Callable[..., LLMResponse],
        *args: Any,
        max_retries: int = 3,
    ) -> LLMResponse:
        for attempt in range(max_retries):
            try:
                resp = fn(*args)
                _record_usage(self.model, resp.usage)
                return resp
            except Exception as exc:
                status = (
                    getattr(exc, "status_code", None)
                    or getattr(getattr(exc, "response", None), "status_code", None)
                    or getattr(exc, "http_status", None)
                )
                if isinstance(status, str):
                    status = None
                retryable = status in (429, 500, 502, 503, 529) or "rate" in str(exc).lower()
                if not retryable or attempt == max_retries - 1:
                    raise
                wait = 2 ** attempt
                logger.warning(
                    "Retryable error (attempt %d/%d), waiting %ds: %s",
                    attempt + 1, max_retries, wait, exc,
                )
                time.sleep(wait)
        raise RuntimeError("Unreachable")

    # ------------------------------------------------------------------
    # Anthropic
    # ------------------------------------------------------------------

    @staticmethod
    def _supports_thinking(model_name: str) -> bool:
        return any(k in model_name for k in ("claude-sonnet", "claude-opus", "claude-fable"))

    def _anthropic_kwargs(self, system_prompt: str, messages: list) -> dict[str, Any]:
        kwargs: dict[str, Any] = dict(
            model=self.settings.model_name,
            max_tokens=self.settings.max_tokens,
            system=system_prompt,
            messages=messages,
        )
        if self._supports_thinking(self.settings.model_name):
            # budget_tokens must be >= 1024 and < max_tokens
            budget = min(4096, max(1024, self.settings.max_tokens // 2))
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
            # temperature must stay at its default when thinking is enabled
        elif self.settings.temperature > 0:
            kwargs["temperature"] = self.settings.temperature
        return kwargs

    def _call_anthropic(self, system_prompt: str, messages: list) -> LLMResponse:
        kwargs = self._anthropic_kwargs(system_prompt, messages)
        response = self._client.messages.create(**kwargs)

        thinking = ""
        text = ""
        for block in response.content:
            if not hasattr(block, "type"):
                continue
            if block.type == "thinking" and getattr(block, "thinking", ""):
                thinking = block.thinking
            elif block.type == "text" and block.text:
                text = block.text

        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "input_tokens": getattr(response.usage, "input_tokens", 0),
                "output_tokens": getattr(response.usage, "output_tokens", 0),
            }

        return LLMResponse(reply_text=text, thinking_text=thinking, usage=usage)

    def _call_anthropic_stream(
        self,
        system_prompt: str,
        messages: list,
        on_text_delta: Callable[[str], None],
    ) -> LLMResponse:
        thinking = ""
        text_parts: list[str] = []

        kwargs = self._anthropic_kwargs(system_prompt, messages)

        usage = {}
        with self._client.messages.stream(**kwargs) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "thinking_delta":
                        thinking += delta.thinking
                    elif delta.type == "text_delta":
                        text_parts.append(delta.text)
                        on_text_delta(delta.text)

            final_msg = stream.get_final_message()
            if hasattr(final_msg, "usage") and final_msg.usage:
                usage = {
                    "input_tokens": getattr(final_msg.usage, "input_tokens", 0),
                    "output_tokens": getattr(final_msg.usage, "output_tokens", 0),
                }

        return LLMResponse(
            reply_text="".join(text_parts),
            thinking_text=thinking,
            usage=usage,
        )

    # ------------------------------------------------------------------
    # OpenAI-compatible
    # ------------------------------------------------------------------

    def _call_openai(self, system_prompt: str, messages: list) -> LLMResponse:
        import openai

        oai_messages = [{"role": "system", "content": system_prompt}] + messages

        kwargs: dict[str, Any] = dict(
            model=self.settings.model_name,
            max_tokens=self.settings.max_tokens,
            messages=oai_messages,
        )
        if self.settings.temperature > 0:
            kwargs["temperature"] = self.settings.temperature
        try:
            try:
                response = self._client.chat.completions.create(**kwargs)
            except openai.BadRequestError as exc:
                # some proxies/models only accept the default temperature
                if "temperature" in str(exc) and "temperature" in kwargs:
                    kwargs.pop("temperature")
                    response = self._client.chat.completions.create(**kwargs)
                else:
                    raise
        except openai.APITimeoutError:
            raise RuntimeError("API request timed out.")
        except openai.APIConnectionError:
            raise RuntimeError("Cannot connect to API. Check LLM_BASE_URL.")

        if not response.choices:
            raise RuntimeError("API returned empty response.")

        choice = response.choices[0]
        text = choice.message.content or ""
        thinking = getattr(choice.message, "reasoning_content", "") or ""

        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "input_tokens": getattr(response.usage, "prompt_tokens", 0),
                "output_tokens": getattr(response.usage, "completion_tokens", 0),
            }

        return LLMResponse(reply_text=text, thinking_text=thinking, usage=usage)

    def _call_openai_stream(
        self,
        system_prompt: str,
        messages: list,
        on_text_delta: Callable[[str], None],
    ) -> LLMResponse:
        import openai

        oai_messages = [{"role": "system", "content": system_prompt}] + messages

        kwargs: dict[str, Any] = dict(
            model=self.settings.model_name,
            max_tokens=self.settings.max_tokens,
            messages=oai_messages,
            stream=True,
        )
        if self.settings.temperature > 0:
            kwargs["temperature"] = self.settings.temperature
        if not self.settings.llm_base_url:
            kwargs["stream_options"] = {"include_usage": True}
        try:
            try:
                stream = self._client.chat.completions.create(**kwargs)
            except openai.BadRequestError as exc:
                # some proxies/models only accept the default temperature
                if "temperature" in str(exc) and "temperature" in kwargs:
                    kwargs.pop("temperature")
                    stream = self._client.chat.completions.create(**kwargs)
                else:
                    raise
        except openai.APITimeoutError:
            raise RuntimeError("API request timed out.")
        except openai.APIConnectionError:
            raise RuntimeError("Cannot connect to API. Check LLM_BASE_URL.")

        text_parts: list[str] = []
        usage: dict[str, int] = {}

        for chunk in stream:
            if hasattr(chunk, "usage") and chunk.usage:
                usage = {
                    "input_tokens": getattr(chunk.usage, "prompt_tokens", 0),
                    "output_tokens": getattr(chunk.usage, "completion_tokens", 0),
                }
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                text_parts.append(delta.content)
                on_text_delta(delta.content)

        return LLMResponse(
            reply_text="".join(text_parts),
            thinking_text="",
            usage=usage,
        )


# ── token usage accounting (⚙️ 设置页可视化) ────────────────────────────
_USAGE_PATH = Path("data/cache/llm_usage.json")
_usage_lock = threading.Lock()


def _record_usage(model: str, usage: dict) -> None:
    """Accumulate per-call token usage; never raises (accounting must not
    break the call it is accounting for)."""
    tin = int(usage.get("input_tokens", 0) or 0)
    tout = int(usage.get("output_tokens", 0) or 0)
    day = time.strftime("%Y-%m-%d")
    try:
        with _usage_lock:
            try:
                data = json.loads(_USAGE_PATH.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {"total": {}, "days": {}}
            for bucket in (data.setdefault("total", {}),
                           data.setdefault("days", {}).setdefault(day, {})):
                bucket["calls"] = bucket.get("calls", 0) + 1
                bucket["input_tokens"] = bucket.get("input_tokens", 0) + tin
                bucket["output_tokens"] = bucket.get("output_tokens", 0) + tout
            data["last_model"] = model
            _USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _USAGE_PATH.write_text(json.dumps(data, ensure_ascii=False,
                                              indent=1), encoding="utf-8")
    except Exception:
        logger.debug("usage accounting skipped", exc_info=True)


def load_usage() -> dict:
    try:
        return json.loads(_USAGE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"total": {}, "days": {}}
