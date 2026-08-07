"""Gold tools — append / delete(ids) / clear; orchestrator scopes (agent_id, user_id)."""

from __future__ import annotations

import json
from typing import Any

from agent_anystack.domain.agent import AgentConfig
from agent_anystack.office import GoldTooLargeError, OfficeRepository
from agent_anystack.office.gold_notes import GOLD_RULES, format_gold_with_rules

GOLD_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_gold",
            "description": (
                "Read your personal working notes (gold). "
                "Each note has an id — use those ids with delete_gold."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "append_gold",
            "description": (
                "Append one durable working note (decision, open thread, preference). "
                "Do not dump the whole chat. Orchestrator assigns a unique id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "One durable bullet to remember.",
                    },
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_gold",
            "description": (
                "Delete one or more gold notes by id (from read_gold or packed gold). "
                "Pass a single id or a list of ids."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Note ids to remove.",
                        "minItems": 1,
                    },
                },
                "required": ["ids"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_gold",
            "description": "Remove all gold notes for this desk notepad.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
]


def execute_gold_tool(
    name: str,
    arguments: dict[str, Any] | str | None,
    *,
    repo: OfficeRepository,
    agent: AgentConfig,
    user_id: str,
    run_id: str | None = None,
) -> str:
    """Run a gold tool. agent/user/run identity from the run — never from model args."""
    args = _parse_args(arguments)
    if name == "read_gold":
        notes = repo.list_gold_notes(agent, user_id)
        body = format_gold_with_rules(notes)
        return body

    if name == "append_gold":
        text = args.get("text")
        if text is None:
            return "error: text is required"
        if not isinstance(text, str):
            return "error: text must be a string"
        if not text.strip():
            return "error: text is empty"
        try:
            note = repo.append_gold_note(
                agent, user_id, text, run_id=run_id
            )
        except GoldTooLargeError as exc:
            return f"error: {exc}"
        except ValueError as exc:
            return f"error: {exc}"
        return f"ok: appended id={note.id}"

    if name == "delete_gold":
        ids = _normalize_ids(args.get("ids"))
        if not ids:
            # Allow single "id" for forgiving models
            ids = _normalize_ids(args.get("id"))
        if not ids:
            return "error: ids is required (one or more note ids)"
        try:
            deleted = repo.delete_gold_notes(agent, user_id, ids)
        except GoldTooLargeError as exc:
            return f"error: {exc}"
        missing = [i for i in ids if i not in deleted]
        parts = [f"ok: deleted {len(deleted)}"]
        if deleted:
            parts.append("ids=" + ",".join(deleted))
        if missing:
            parts.append("missing=" + ",".join(missing))
        return "; ".join(parts)

    if name == "clear_gold":
        repo.clear_gold(agent, user_id)
        return "ok: gold cleared"

    return f"error: unknown tool {name}"


def _normalize_ids(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        s = raw.strip()
        return [s] if s else []
    if isinstance(raw, list):
        out: list[str] = []
        for item in raw:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out
    return []


def _parse_args(arguments: dict[str, Any] | str | None) -> dict[str, Any]:
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        raw = arguments.strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


# Re-export for pack/tests
__all__ = [
    "GOLD_RULES",
    "GOLD_TOOL_SCHEMAS",
    "execute_gold_tool",
]
