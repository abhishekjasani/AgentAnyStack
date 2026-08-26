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

    async def stream_chat_events(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, str]]:
        """Yield streamed events ({'type': 'thinking'|'token', 'text': str})."""
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
    reasoning: str = ""


_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


def extract_reasoning_and_content(
    content: str | None,
    raw_reasoning: str | None = None,
) -> tuple[str, str]:
    """Extract clean assistant content and reasoning trace.

    Handles explicit reasoning fields and/or <think>...</think> XML blocks.
    """
    clean_text = (content or "").strip()
    reasoning_parts: list[str] = []
    if raw_reasoning and str(raw_reasoning).strip():
        reasoning_parts.append(str(raw_reasoning).strip())

    if _THINK_OPEN in clean_text:
        clean_content_parts: list[str] = []
        idx = 0
        while idx < len(clean_text):
            start = clean_text.find(_THINK_OPEN, idx)
            if start == -1:
                clean_content_parts.append(clean_text[idx:])
                break
            if start > idx:
                clean_content_parts.append(clean_text[idx:start])
            end = clean_text.find(_THINK_CLOSE, start + len(_THINK_OPEN))
            if end == -1:
                thought = clean_text[start + len(_THINK_OPEN) :].strip()
                if thought:
                    reasoning_parts.append(thought)
                break
            thought = clean_text[start + len(_THINK_OPEN) : end].strip()
            if thought:
                reasoning_parts.append(thought)
            idx = end + len(_THINK_CLOSE)
        clean_text = "".join(clean_content_parts).strip()

    return clean_text, "\n".join(p for p in reasoning_parts if p).strip()


class StreamingThinkParser:
    """Parses streamed content deltas for <think>...</think> tags.

    Emits typed chunks:
      ('thinking', chunk)
      ('token', chunk)
    """

    def __init__(self) -> None:
        self.in_think: bool = False
        self.buffer: str = ""

    def feed(self, text: str) -> list[tuple[str, str]]:
        if not text:
            return []
        self.buffer += text
        events: list[tuple[str, str]] = []

        while self.buffer:
            if not self.in_think:
                idx = self.buffer.find(_THINK_OPEN)
                if idx != -1:
                    if idx > 0:
                        events.append(("token", self.buffer[:idx]))
                    self.in_think = True
                    self.buffer = self.buffer[idx + len(_THINK_OPEN) :]
                    continue
                matched_prefix = False
                for l in range(min(len(_THINK_OPEN) - 1, len(self.buffer)), 0, -1):
                    suffix = self.buffer[-l:]
                    if _THINK_OPEN.startswith(suffix):
                        if len(self.buffer) > l:
                            events.append(("token", self.buffer[:-l]))
                            self.buffer = suffix
                        matched_prefix = True
                        break
                if matched_prefix:
                    break
                events.append(("token", self.buffer))
                self.buffer = ""
            else:
                idx = self.buffer.find(_THINK_CLOSE)
                if idx != -1:
                    if idx > 0:
                        events.append(("thinking", self.buffer[:idx]))
                    self.in_think = False
                    self.buffer = self.buffer[idx + len(_THINK_CLOSE) :]
                    continue
                matched_prefix = False
                for l in range(min(len(_THINK_CLOSE) - 1, len(self.buffer)), 0, -1):
                    suffix = self.buffer[-l:]
                    if _THINK_CLOSE.startswith(suffix):
                        if len(self.buffer) > l:
                            events.append(("thinking", self.buffer[:-l]))
                            self.buffer = suffix
                        matched_prefix = True
                        break
                if matched_prefix:
                    break
                events.append(("thinking", self.buffer))
                self.buffer = ""

        return events

    def flush(self) -> list[tuple[str, str]]:
        events: list[tuple[str, str]] = []
        if self.buffer:
            kind = "thinking" if self.in_think else "token"
            events.append((kind, self.buffer))
            self.buffer = ""
        return events



def _apply_limits(
    payload: dict[str, Any],
    *,
    max_tokens: int | None,
) -> None:
    if max_tokens is not None and max_tokens > 0:
        payload["max_tokens"] = int(max_tokens)


class OpenAICompatibleAdapter:
    """One wire for any OpenAI chat-completions server — switch host via base_url."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 120.0,
        api_key: str | None = None,
    ) -> None:
        self.base_url = _normalize_base_url(base_url)
        self.timeout = timeout
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def stream_chat_events(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, str]]:
        """Stream events ('thinking' or 'token') from OpenAI chat completions."""
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        _apply_limits(payload, max_tokens=max_tokens)
        headers = self._headers()
        parser = StreamingThinkParser()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
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

                        # 1. Dedicated reasoning delta field
                        r_delta = (
                            delta.get("reasoning_content")
                            or delta.get("reasoning")
                            or delta.get("thought")
                        )
                        if r_delta:
                            yield {"type": "thinking", "text": str(r_delta)}

                        # 2. Content delta (parsed for inline <think> tags)
                        content = delta.get("content") or ""
                        if content:
                            for kind, text in parser.feed(content):
                                if text:
                                    yield {"type": kind, "text": text}

                    for kind, text in parser.flush():
                        if text:
                            yield {"type": kind, "text": text}
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

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        async for ev in self.stream_chat_events(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
        ):
            if ev.get("type") == "token" and ev.get("text"):
                yield ev["text"]

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
        headers = self._headers()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
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
                raw_reasoning = (
                    message.get("reasoning_content")
                    or message.get("reasoning")
                    or message.get("thought")
                )
                raw_content = message.get("content") or ""
                clean_content, reasoning = extract_reasoning_and_content(
                    raw_content,
                    str(raw_reasoning) if raw_reasoning is not None else None,
                )
                return ChatTurnResult(
                    content=clean_content,
                    tool_calls=_parse_tool_calls(message.get("tool_calls")),
                    reasoning=reasoning,
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

    async def list_models(self) -> list[str]:
        """Query GET /models to discover available models."""
        url = f"{self.base_url}/models"
        headers = self._headers()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code in (401, 403):
                    raise StackError(
                        f"Authentication failed ({resp.status_code}) at {self.base_url}. Check your API key.",
                        code="openai_compatible_auth",
                    )
                if resp.status_code >= 400:
                    raise StackError(
                        f"Could not list models from {self.base_url} (HTTP {resp.status_code}): {resp.text[:200]}",
                        code="openai_compatible_http",
                    )
                data = resp.json()
                items = data.get("data") or data.get("models") or []
                if isinstance(items, list):
                    out = []
                    for item in items:
                        if isinstance(item, dict) and item.get("id"):
                            out.append(str(item["id"]))
                        elif isinstance(item, str):
                            out.append(item)
                    return out
                return []
        except httpx.ConnectError as exc:
            raise StackError(
                f"Cannot reach server at {self.base_url}.",
                code="openai_compatible_unreachable",
            ) from exc
        except httpx.TimeoutException as exc:
            raise StackError(
                f"Server timed out at {self.base_url}.",
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
