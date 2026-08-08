"""Effective run limits: stack num_ctx + agent max_input/max_output (-1 = inherit)."""

from __future__ import annotations

from dataclasses import dataclass

from agent_anystack.adapters.ollama_models import catalog_num_ctx
from agent_anystack.domain.agent import AgentConfig
from agent_anystack.domain.orchestrator import OrchestratorConfig

_SLACK_TOKENS = 64


@dataclass(frozen=True)
class RunLimits:
    num_ctx: int
    max_input_tokens: int
    max_output_tokens: int | None  # None = omit max_tokens on wire


def resolve_run_limits(
    *,
    model: str,
    orc: OrchestratorConfig,
    agent: AgentConfig | None = None,
) -> RunLimits:
    """Stack owns num_ctx (per-model catalog, else orc.default_num_ctx).

    Agent may only tighten max_input / max_output when > 0; -1 inherits stack.
    """
    num_ctx = catalog_num_ctx(model) or orc.default_num_ctx
    num_ctx = max(512, min(int(num_ctx), 131_072))

    stack_out = orc.default_max_output_tokens
    if agent is not None and agent.max_output_tokens is not None and agent.max_output_tokens > 0:
        max_out: int | None = min(agent.max_output_tokens, stack_out if stack_out > 0 else agent.max_output_tokens)
    elif stack_out > 0:
        max_out = stack_out
    else:
        max_out = None

    out_for_budget = max_out if max_out is not None else min(1024, num_ctx // 4)
    derived_in = max(512, num_ctx - out_for_budget - _SLACK_TOKENS)

    stack_in = orc.default_max_input_tokens
    if stack_in > 0:
        stack_in = min(stack_in, derived_in)
    else:
        stack_in = derived_in

    if agent is not None and agent.max_input_tokens is not None and agent.max_input_tokens > 0:
        max_in = min(agent.max_input_tokens, stack_in)
    else:
        max_in = stack_in

    max_in = max(256, min(max_in, derived_in))
    return RunLimits(num_ctx=num_ctx, max_input_tokens=max_in, max_output_tokens=max_out)


def approx_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def truncate_messages_to_input(
    messages: list[dict],
    *,
    max_input_tokens: int,
) -> list[dict]:
    """Keep user/tool turns; shrink oversized system content to fit max_input."""
    if max_input_tokens <= 0 or not messages:
        return messages
    budget_chars = max_input_tokens * 4
    total = sum(len(str(m.get("content") or "")) for m in messages)
    if total <= budget_chars:
        return messages

    out = [dict(m) for m in messages]
    # Prefer trimming the first system message.
    for i, m in enumerate(out):
        if m.get("role") != "system":
            continue
        other = sum(len(str(x.get("content") or "")) for j, x in enumerate(out) if j != i)
        allow = max(200, budget_chars - other)
        content = str(m.get("content") or "")
        if len(content) > allow:
            out[i]["content"] = content[: allow - 20] + "\n\n…[truncated for max_input]"
        break
    return out
