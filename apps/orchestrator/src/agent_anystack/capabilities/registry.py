from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agent_anystack.capabilities.apis.auth import SecretResolver
from agent_anystack.capabilities.apis.executor import execute_api_operation
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
    repo: OfficeRepository | None
    agent: AgentConfig
    user_id: str
    run_id: str
    secret_resolver: SecretResolver | None = None
    oauth_token_resolver: Any = None


Handler = Callable[..., str]
HANDLERS: dict[str, Handler] = {
    "gold.read": read_gold,
    "gold.append": append_gold,
    "gold.delete": delete_gold,
    "gold.clear": clear_gold,
}


def has_handler(handler: str) -> bool:
    return handler in HANDLERS


async def dispatch(
    binding: Any,
    arguments: dict[str, Any] | str | None,
    ctx: ToolContext,
) -> str:
    if binding.kind.value == "api":
        return await execute_api_operation(
            binding,
            arguments,
            secret_resolver=ctx.secret_resolver,
            oauth_token_resolver=ctx.oauth_token_resolver,
            user_id=ctx.user_id,
        )
    if binding.kind.value == "mcp":
        from agent_anystack.capabilities.mcp.client import call_mcp_tool

        args = arguments if isinstance(arguments, dict) else {}
        return await call_mcp_tool(
            binding,
            args,
            secret_resolver=ctx.secret_resolver,
            oauth_token_resolver=ctx.oauth_token_resolver,
            user_id=ctx.user_id,
        )

    handler = HANDLERS.get(binding.item.handler or "")
    if handler is None:
        return "error: unknown tool"
    if ctx.repo is None:
        return "error: missing repository context"
    return handler(
        arguments,
        repo=ctx.repo,
        agent=ctx.agent,
        user_id=ctx.user_id,
        run_id=ctx.run_id,
    )