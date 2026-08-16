"""Map OpenCode /event SSE dicts → office chat events (slice A)."""

from __future__ import annotations

from typing import Any


def _props(event: dict[str, Any]) -> dict[str, Any]:
    if event.get("properties") is not None and isinstance(event["properties"], dict):
        return event["properties"]
    data = event.get("data")
    return data if isinstance(data, dict) else {}


def parse_model_ref(raw: str) -> tuple[str, str]:
    """provider/model → (provider_id, model_id). Default provider opencode."""
    s = (raw or "").strip()
    if not s:
        return "opencode", "big-pickle"
    if "/" in s:
        provider, model = s.split("/", 1)
        return provider.strip() or "opencode", model.strip() or "big-pickle"
    return "opencode", s


class EventMapper:
    """Stateful mapper for one session run (tracks streamed text offsets)."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._text_seen: dict[str, int] = {}
        self._think_seen: dict[str, int] = {}

    def map(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        etype = event.get("type")
        props = _props(event)
        out: list[dict[str, Any]] = []

        if etype == "permission.asked":
            if props.get("sessionID") != self.session_id:
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

        if etype == "message.part.updated":
            part = props.get("part") or {}
            if not isinstance(part, dict):
                return out
            if part.get("sessionID") != self.session_id:
                return out
            part_type = part.get("type")
            part_id = str(part.get("id") or "")
            if part_type == "text":
                text = str(part.get("text") or "")
                already = self._text_seen.get(part_id, 0)
                delta = text[already:]
                self._text_seen[part_id] = len(text)
                if delta:
                    out.append({"type": "token", "text": delta})
            elif part_type in ("reasoning", "thinking", "thought"):
                text = str(part.get("text") or part.get("content") or "")
                already = self._think_seen.get(part_id, 0)
                delta = text[already:]
                self._think_seen[part_id] = len(text)
                if delta:
                    out.append({"type": "thinking", "text": delta})
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
                        "message": str(props.get("error") or "opencode session error"),
                        "code": "opencode_session_error",
                    }
                )
            return out

        return out
