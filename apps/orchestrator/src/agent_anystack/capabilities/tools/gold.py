from __future__ import annotations

import json
from typing import Any

from agent_anystack.domain.agent import AgentConfig
from agent_anystack.office import GoldTooLargeError, OfficeRepository
from agent_anystack.office.gold_notes import (
    SYSTEM_GOLD_ID,
    format_gold_with_rules,
)


def read_gold(
    arguments: dict[str, Any] | str | None,
    *,
    repo: OfficeRepository,
    agent: AgentConfig,
    user_id: str,
    run_id: str | None = None,
) -> str:
    del arguments, run_id
    return format_gold_with_rules(repo.list_gold_notes(agent, user_id))


def append_gold(
    arguments: dict[str, Any] | str | None,
    *,
    repo: OfficeRepository,
    agent: AgentConfig,
    user_id: str,
    run_id: str | None = None,
) -> str:
    args = _parse_args(arguments)
    text = args.get("text")
    if text is None:
        return "error: text is required"
    if not isinstance(text, str):
        return "error: text must be a string"
    if not text.strip():
        return "error: text is empty"
    try:
        note = repo.append_gold_note(agent, user_id, text, run_id=run_id)
    except GoldTooLargeError as exc:
        return f"error: {exc}"
    except ValueError as exc:
        return f"error: {exc}"
    return f"ok: appended id={note.id}"


def delete_gold(
    arguments: dict[str, Any] | str | None,
    *,
    repo: OfficeRepository,
    agent: AgentConfig,
    user_id: str,
    run_id: str | None = None,
) -> str:
    del run_id
    args = _parse_args(arguments)
    ids = _normalize_ids(args.get("ids"))
    if not ids:
        ids = _normalize_ids(args.get("id"))
    if not ids:
        return "error: ids is required (one or more note ids)"
    try:
        deleted = repo.delete_gold_notes(agent, user_id, ids)
    except GoldTooLargeError as exc:
        return f"error: {exc}"
    protected = [item_id for item_id in ids if item_id == SYSTEM_GOLD_ID]
    missing = [item_id for item_id in ids if item_id not in deleted and item_id != SYSTEM_GOLD_ID]
    parts = [f"ok: deleted {len(deleted)}"]
    if deleted:
        parts.append("ids=" + ",".join(deleted))
    if protected:
        parts.append(f"protected={SYSTEM_GOLD_ID}")
    if missing:
        parts.append("missing=" + ",".join(missing))
    return "; ".join(parts)


def clear_gold(
    arguments: dict[str, Any] | str | None,
    *,
    repo: OfficeRepository,
    agent: AgentConfig,
    user_id: str,
    run_id: str | None = None,
) -> str:
    del arguments, run_id
    repo.clear_gold(agent, user_id)
    return f"ok: gold cleared; primer {SYSTEM_GOLD_ID} restored"


def execute_gold_tool(
    name: str,
    arguments: dict[str, Any] | str | None,
    *,
    repo: OfficeRepository,
    agent: AgentConfig,
    user_id: str,
    run_id: str | None = None,
) -> str:
    handlers = {
        "read_gold": read_gold,
        "append_gold": append_gold,
        "delete_gold": delete_gold,
        "clear_gold": clear_gold,
    }
    handler = handlers.get(name)
    if handler is None:
        return f"error: unknown tool {name}"
    return handler(
        arguments,
        repo=repo,
        agent=agent,
        user_id=user_id,
        run_id=run_id,
    )


def _normalize_ids(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        value = raw.strip()
        return [value] if value else []
    if isinstance(raw, list):
        return [item.strip() for item in raw if isinstance(item, str) and item.strip()]
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