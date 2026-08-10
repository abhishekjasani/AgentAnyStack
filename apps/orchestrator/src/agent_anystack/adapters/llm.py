"""Stack adapters — OpenAI-compatible + Bedrock (see adapters.bedrock).

OpenAI-compatible covers Ollama, vLLM, LM Studio, etc. — switch host via base_url only.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


class StackAdapter(Protocol):
    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Yield assistant text deltas. Raises StackError on failure."""
        ...


class StackError(Exception):
    """Adapter/connectivity/model errors (server up but model missing, etc.)."""

    def __init__(self, message: str, *, code: str = "stack_error") -> None:
        self.code = code
        super().__init__(message)


@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: str


@dataclass
class ChatTurnResult:
    content: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)


def _apply_limits(
    payload: dict[str, Any],
    *,
    max_tokens: int | None,
) -> None:
    if max_tokens is not None and max_tokens > 0:
        payload["max_tokens"] = int(max_tokens)


class OpenAICompatibleAdapter:
    """One wire for any OpenAI chat-completions server — switch host via base_url."""

    def __init__(self, base_url: str, timeout: float = 120.0) -> None:
        self.base_url = _normalize_base_url(base_url)
        self.timeout = timeout

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        _apply_limits(payload, max_tokens=max_tokens)
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

    async def complete_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Non-streaming completion (extractor). Returns assistant text."""
        turn = await self.complete_chat_turn(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return turn.content.strip()

    async def complete_chat_turn(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ChatTurnResult:
        """Non-streaming turn — text and/or tool_calls (OpenAI tools shape)."""
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
        _apply_limits(payload, max_tokens=max_tokens)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code >= 400:
                    raise StackError(
                        _friendly_http_error(
                            resp.status_code,
                            resp.text,
                            model,
                            self.base_url,
                        ),
                        code="openai_compatible_http",
                    )
                data = resp.json()
                if err := data.get("error"):
                    msg = err if isinstance(err, str) else err.get("message", str(err))
                    raise StackError(
                        _friendly_http_error(200, str(msg), model, self.base_url),
                        code="openai_compatible_model",
                    )
                choices = data.get("choices") or []
                if not choices:
                    return ChatTurnResult()
                message = choices[0].get("message") or {}
                return ChatTurnResult(
                    content=(message.get("content") or "") or "",
                    tool_calls=_parse_tool_calls(message.get("tool_calls")),
                )
        except httpx.ConnectError as exc:
            raise StackError(
                f"Cannot reach OpenAI-compatible server at {self.base_url}.",
                code="openai_compatible_unreachable",
            ) from exc
        except httpx.TimeoutException as exc:
            raise StackError(
                f"OpenAI-compatible server timed out at {self.base_url}.",
                code="openai_compatible_timeout",
            ) from exc


def _parse_tool_calls(raw: Any) -> list[ToolCallRequest]:
    if not isinstance(raw, list):
        return []
    out: list[ToolCallRequest] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        fn = item.get("function") or {}
        if not isinstance(fn, dict):
            continue
        name = fn.get("name") or ""
        if not name:
            continue
        args = fn.get("arguments")
        if isinstance(args, dict):
            args_s = json.dumps(args, ensure_ascii=False)
        else:
            args_s = str(args or "")
        call_id = str(item.get("id") or f"call_{i}")
        out.append(ToolCallRequest(id=call_id, name=name, arguments=args_s))
    return out


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
