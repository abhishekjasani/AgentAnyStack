from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agent_anystack.capabilities.tools.gold import (
    append_gold,
    clear_gold,
    delete_gold,
    read_gold,
)
from agent_anystack.domain.agent import AgentConfig
from agent_anystack.office import OfficeRepository


@dataclass(frozen=True)
class ToolContext:
    repo: OfficeRepository
    agent: AgentConfig
    user_id: str
    run_id: str


Handler = Callable[..., str]
HANDLERS: dict[str, Handler] = {
    "gold.read": read_gold,
    "gold.append": append_gold,
    "gold.delete": delete_gold,
    "gold.clear": clear_gold,
}


def has_handler(handler: str) -> bool:
    return handler in HANDLERS


def dispatch(binding: Any, arguments: dict[str, Any] | str | None, ctx: ToolContext) -> str:
    handler = HANDLERS.get(binding.item.handler or "")
    if handler is None:
        return "error: unknown tool"
    return handler(
        arguments,
        repo=ctx.repo,
        agent=ctx.agent,
        user_id=ctx.user_id,
        run_id=ctx.run_id,
    )