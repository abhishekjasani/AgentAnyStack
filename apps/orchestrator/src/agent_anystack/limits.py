"""Effective run limits: stack + agent max_input/max_output (-1 = inherit).

Local Ollama context/KV is owned by the server (e.g. OLLAMA_CONTEXT_LENGTH),
not per-request options.num_ctx — that path forced reloads on small GPUs.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_anystack.domain.agent import AgentConfig
from agent_anystack.domain.orchestrator import OrchestratorConfig


@dataclass(frozen=True)
class RunLimits:
    max_input_tokens: int
    max_output_tokens: int | None  # None = omit max_tokens on wire


def resolve_run_limits(
    *,
    model: str,
    orc: OrchestratorConfig,
    agent: AgentConfig | None = None,
) -> RunLimits:
    """Stack defaults for max_input / max_output; agent may tighten when > 0.

    -1 on stack max_input → use pack_token_budget as the input ceiling.
    -1 / unset on max_output → omit max_tokens on the wire.
    `model` is unused (kept for call-site stability).
    """
    _ = model

    stack_out = orc.default_max_output_tokens
    if agent is not None and agent.max_output_tokens is not None and agent.max_output_tokens > 0:
        max_out: int | None = min(
            agent.max_output_tokens,
            stack_out if stack_out > 0 else agent.max_output_tokens,
        )
    elif stack_out > 0:
        max_out = stack_out
    else:
        max_out = None

    stack_in = orc.default_max_input_tokens
    if stack_in > 0:
        base_in = stack_in
    else:
        base_in = max(512, int(orc.pack_token_budget))

    if agent is not None and agent.max_input_tokens is not None and agent.max_input_tokens > 0:
        max_in = min(agent.max_input_tokens, base_in)
    else:
        max_in = base_in

    max_in = max(256, max_in)
    return RunLimits(max_input_tokens=max_in, max_output_tokens=max_out)


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
