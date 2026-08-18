"""Map OpenCode /event SSE dicts → office chat events (slice A)."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_THINK_TYPES = frozenset({"reasoning", "thinking", "thought", "reasoning_content"})
_SKIP_PART_TYPES = frozenset(
    {
        "step-start",
        "step-finish",
        "tool",
        "tool-invocation",
        "file",
        "patch",
        "snapshot",
        "agent",
        "retry",
        "compaction",
        "source-url",
        "source",
    }
)


def _props(event: dict[str, Any]) -> dict[str, Any]:
    if event.get("properties") is not None and isinstance(event["properties"], dict):
        return event["properties"]
    data = event.get("data")
    return data if isinstance(data, dict) else {}


def _normalize_type(raw: Any) -> str:
    """OpenCode 1.18 emits versioned types like ``message.part.updated.1``."""
    t = str(raw or "")
    parts = t.split(".")
    if len(parts) >= 2 and parts[-1].isdigit():
        return ".".join(parts[:-1])
    return t


def parse_model_ref(raw: str) -> tuple[str, str]:
    """provider/model → (provider_id, model_id). Default provider opencode."""
    s = (raw or "").strip()
    if not s:
        return "opencode", "big-pickle"
    if "/" in s:
        provider, model = s.split("/", 1)
        return provider.strip() or "opencode", model.strip() or "big-pickle"
    return "opencode", s


def _error_message(err: Any) -> str:
    if err is None:
        return "opencode session error"
    if isinstance(err, str):
        return err
    if isinstance(err, dict):
        data = err.get("data") if isinstance(err.get("data"), dict) else err
        msg = data.get("message") or err.get("message") or err.get("name")
        if msg:
            return str(msg)
        return str(err)
    return str(err)


def _session_id(props: dict[str, Any], part: dict[str, Any] | None = None) -> str:
    if isinstance(part, dict):
        sid = str(part.get("sessionID") or "")
        if sid:
            return sid
    return str(props.get("sessionID") or "")


def _part_text(part: dict[str, Any]) -> str:
    text = part.get("text") or part.get("content")
    if isinstance(text, str) and text:
        return text
    nested = part.get("reasoningContent") or part.get("reasoning_content") or {}
    if isinstance(nested, dict):
        inner = nested.get("reasoningText") or nested.get("text") or nested
        if isinstance(inner, dict):
            return str(inner.get("text") or "")
        if isinstance(inner, str):
            return inner
    return str(text or "")


class EventMapper:
    """Stateful mapper for one session run (tracks streamed text offsets)."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._text_seen: dict[str, int] = {}
        self._think_seen: dict[str, int] = {}
        self._part_kind: dict[str, str] = {}

    def _ours(self, props: dict[str, Any], part: dict[str, Any] | None = None) -> bool:
        sid = _session_id(props, part)
        return bool(sid) and sid == self.session_id

    def map(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        etype = _normalize_type(event.get("type"))
        props = _props(event)
        out: list[dict[str, Any]] = []

        if etype == "permission.asked":
            if not self._ours(props):
                return out
            out.append(
                {
                    "type": "opencode_permission",
                    "permission_id": props.get("id"),
                    "permission": props.get("permission"),
                    "patterns": props.get("patterns"),
                }
            )
            return out

        if etype == "message.part.delta":
            if not self._ours(props):
                return out
            part_id = str(props.get("partID") or props.get("partId") or "")
            field = str(props.get("field") or "")
            chunk = str(props.get("delta") or "")
            if not chunk:
                return out
            kind = self._part_kind.get(part_id, "")
            if kind in _THINK_TYPES or field in _THINK_TYPES:
                out.append({"type": "thinking", "text": chunk})
            elif kind == "text" or (not kind and field == "text"):
                # Unknown part + field=text: wait for part.updated type.
                if kind == "text":
                    out.append({"type": "token", "text": chunk})
            return out

        if etype == "message.part.updated":
            part = props.get("part") or {}
            if not isinstance(part, dict):
                return out
            if not self._ours(props, part):
                return out
            part_type = str(part.get("type") or "")
            part_id = str(part.get("id") or "")
            if part_id and part_type:
                self._part_kind[part_id] = part_type
            live = props.get("delta")
            live_s = live if isinstance(live, str) else ""
            if part_type == "text":
                text = _part_text(part)
                already = self._text_seen.get(part_id, 0)
                if live_s:
                    delta = live_s
                    self._text_seen[part_id] = len(text) if text else already + len(delta)
                else:
                    delta = text[already:]
                    self._text_seen[part_id] = len(text)
                if delta:
                    out.append({"type": "token", "text": delta})
            elif part_type in _THINK_TYPES:
                text = _part_text(part)
                already = self._think_seen.get(part_id, 0)
                if live_s:
                    delta = live_s
                    self._think_seen[part_id] = len(text) if text else already + len(delta)
                else:
                    delta = text[already:]
                    self._think_seen[part_id] = len(text)
                if delta:
                    out.append({"type": "thinking", "text": delta})
            elif part_type and part_type not in _SKIP_PART_TYPES:
                log.debug("opencode part type ignored: %s", part_type)
            return out

        if etype == "message.updated":
            info = props.get("info") or props.get("message") or {}
            if not isinstance(info, dict):
                return out
            if not self._ours(props, info):
                return out
            if info.get("role") == "assistant" and info.get("error"):
                out.append(
                    {
                        "type": "error",
                        "message": _error_message(info.get("error")),
                        "code": "opencode_api_error",
                    }
                )
            return out

        if etype == "session.idle":
            if props.get("sessionID") == self.session_id:
                out.append({"type": "session_idle"})
            return out

        if etype == "session.error":
            if props.get("sessionID") == self.session_id:
                out.append(
                    {
                        "type": "error",
                        "message": _error_message(
                            props.get("error") or props.get("message")
                        ),
                        "code": "opencode_session_error",
                    }
                )
            return out

        return out


def collect_reasoning_from_messages(rows: Any) -> list[str]:
    """Pull reasoning part text from GET /session/{id}/message payloads."""
    if not isinstance(rows, list):
        return []
    out: list[str] = []
    for row in rows:
        parts: list[Any] = []
        if isinstance(row, dict):
            raw_parts = row.get("parts")
            if isinstance(raw_parts, list):
                parts = raw_parts
            else:
                info = row.get("info")
                if isinstance(info, dict) and isinstance(info.get("parts"), list):
                    parts = info["parts"]
        elif hasattr(row, "parts"):
            parts = list(getattr(row, "parts") or [])
        for part in parts:
            if not isinstance(part, dict):
                part = getattr(part, "__dict__", None) or {}
            if not isinstance(part, dict):
                continue
            if str(part.get("type") or "") not in _THINK_TYPES:
                continue
            text = _part_text(part).strip()
            if text:
                out.append(text)
    return out
