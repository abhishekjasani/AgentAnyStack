"""Stack adapters — one module; add Anthropic/Cursor classes here when shipped.

OpenAI-compatible covers Ollama, vLLM, LM Studio, etc. — switch host via base_url only.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx


class StackAdapter(Protocol):
    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
    ) -> AsyncIterator[str]:
        """Yield assistant text deltas. Raises StackError on failure."""
        ...


class StackError(Exception):
    """Adapter/connectivity/model errors (server up but model missing, etc.)."""

    def __init__(self, message: str, *, code: str = "stack_error") -> None:
        self.code = code
        super().__init__(message)


class OpenAICompatibleAdapter:
    """One wire for any OpenAI chat-completions server — switch host via base_url."""

    def __init__(self, base_url: str, timeout: float = 120.0) -> None:
        self.base_url = _normalize_base_url(base_url)
        self.timeout = timeout

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
    ) -> AsyncIterator[str]:
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", url, json=payload) as resp:
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode("utf-8", errors="replace")
                        raise StackError(
                            _friendly_http_error(resp.status_code, body, model, self.base_url),
                            code="openai_compatible_http",
                        )
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[len("data:") :].strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if err := chunk.get("error"):
                            msg = err if isinstance(err, str) else err.get("message", str(err))
                            raise StackError(
                                _friendly_http_error(200, str(msg), model, self.base_url),
                                code="openai_compatible_model",
                            )
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        content = delta.get("content") or ""
                        if content:
                            yield content
        except httpx.ConnectError as exc:
            raise StackError(
                f"Cannot reach OpenAI-compatible server at {self.base_url}. "
                "For local Ollama: start it and set OPENAI_COMPATIBLE_BASE_URL "
                "(e.g. http://127.0.0.1:11434/v1).",
                code="openai_compatible_unreachable",
            ) from exc
        except httpx.TimeoutException as exc:
            raise StackError(
                f"OpenAI-compatible server timed out at {self.base_url}.",
                code="openai_compatible_timeout",
            ) from exc


def _normalize_base_url(base_url: str) -> str:
    """Accept host-only (…:11434) or …/v1 — always end with /v1 for chat path."""
    url = base_url.rstrip("/")
    if url.endswith("/v1"):
        return url
    return f"{url}/v1"


def _friendly_http_error(status: int, body: str, model: str, base_url: str) -> str:
    lower = body.lower()
    if "not found" in lower or "pull" in lower or status == 404:
        hint = (
            f" Pull it first: ollama pull {model}"
            if "11434" in base_url or "ollama" in base_url.lower()
            else ""
        )
        return (
            f"Model '{model}' is not available at {base_url}.{hint} "
            "Server can be up with zero models loaded."
        )
    return f"OpenAI-compatible error ({status}) at {base_url}: {body[:500]}"
