"""Gold tools — agent personal notepad; orchestrator scopes (agent_id, user_id)."""

from __future__ import annotations

import json
from typing import Any

from agent_anystack.domain.agent import AgentConfig
from agent_anystack.office import GoldTooLargeError, OfficeRepository

GOLD_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_gold",
            "description": (
                "Read your personal working notes (gold). "
                "Prefer this before update_gold so you do not overwrite blindly."
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
            "name": "update_gold",
            "description": (
                "Write your personal working notes (gold). "
                "Use for durable bullets (decisions, open threads, preferences) — "
                "never dump the whole chat. "
                "mode=replace overwrites; mode=append adds to the end."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Markdown notes to store (or append).",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["replace", "append"],
                        "description": "replace (default) or append.",
                    },
                },
                "required": ["content"],
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
) -> str:
    """Run a gold tool. Identity comes from the run — never from model args."""
    args = _parse_args(arguments)
    if name == "read_gold":
        text = repo.read_gold(agent, user_id)
        return text if text.strip() else "(empty)"
    if name == "update_gold":
        content = args.get("content")
        if content is None:
            return "error: content is required"
        if not isinstance(content, str):
            return "error: content must be a string"
        mode = args.get("mode") or "replace"
        if mode not in ("replace", "append"):
            return "error: mode must be replace or append"
        if mode == "append":
            prev = repo.read_gold(agent, user_id)
            if prev.strip() and content.strip():
                content = prev.rstrip() + "\n" + content
            elif prev.strip() and not content.strip():
                content = prev
        try:
            repo.write_gold(agent, user_id, content)
        except GoldTooLargeError as exc:
            return f"error: {exc}"
        return "ok: gold updated"
    return f"error: unknown tool {name}"


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
