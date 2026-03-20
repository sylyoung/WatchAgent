"""Thin wrapper around an OpenAI-compatible chat API (default: DeepSeek V3)."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

log = logging.getLogger(__name__)


@dataclass
class ChatWithToolsResponse:
    content: str
    tool_calls: list[Any] = field(default_factory=list)
    finish_reason: str = ""

_DEFAULT_BASE_URL = "https://api.deepseek.com"
_DEFAULT_MODEL = "deepseek-chat"
_DEFAULT_TIMEOUT = 10  # seconds – watch interactions should be snappy


def sanitize_pii(text: str) -> str:
    """Remove or mask PII before sending to external LLM."""
    # Truncate individual message content to 20 chars
    text = re.sub(r"消息内容[：:]\s*(.{20}).+", r"消息内容：\1…", text)
    # Mask phone numbers
    text = re.sub(r"1[3-9]\d{9}", "1**********", text)
    # Mask email addresses
    text = re.sub(r"[a-zA-Z0-9.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9.]+", "***@***.***", text)
    return text


class LLMClient:
    """Synchronous LLM chat client (designed for use inside ThreadPoolExecutor)."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self.base_url = base_url or os.environ.get("LLM_BASE_URL", _DEFAULT_BASE_URL)
        self.model = model or os.environ.get("LLM_MODEL", _DEFAULT_MODEL)
        self.timeout = timeout or float(os.environ.get("LLM_TIMEOUT", str(_DEFAULT_TIMEOUT)))

        self._client: OpenAI | None = None
        if self.api_key:
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url if self.base_url.endswith("/v1") else f"{self.base_url.rstrip('/')}/v1",
                timeout=self.timeout,
            )

    @property
    def available(self) -> bool:
        return self._client is not None

    def chat(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 100,
        fallback: str = "",
    ) -> str:
        """Send a single-turn chat request. Returns *fallback* on any error."""
        if not self._client:
            log.warning("LLM client not configured (no API key). Using fallback.")
            return fallback

        user_message = sanitize_pii(user_message)

        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=max_tokens,
                temperature=0.7,
            )
            text = (resp.choices[0].message.content or "").strip()
            return text if text else fallback
        except Exception:
            log.exception("LLM call failed, returning fallback")
            return fallback

    def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 500,
    ) -> ChatWithToolsResponse:
        """Call DeepSeek V3 tool-calling API. Returns empty tool_calls on error."""
        if not self._client:
            log.warning("LLM client not configured (no API key). Skipping tool call.")
            return ChatWithToolsResponse(content="", tool_calls=[], finish_reason="error")

        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                max_tokens=max_tokens,
            )
            choice = resp.choices[0]
            return ChatWithToolsResponse(
                content=choice.message.content or "",
                tool_calls=list(choice.message.tool_calls or []),
                finish_reason=choice.finish_reason or "",
            )
        except Exception:
            log.exception("chat_with_tools failed")
            return ChatWithToolsResponse(content="", tool_calls=[], finish_reason="error")
