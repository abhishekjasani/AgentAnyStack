"""Fixed Office Envelope — musts + workspace + autonomy intent; role in AGENT.md."""

from agent_anystack.domain.agent import AgentConfig


def build_office_envelope(
    *,
    agent: AgentConfig,
    user_id: str,
    effective_autonomy: int,
) -> str:
    """Office law for the LLM. Keep behavioral rules — do not name infra (orchestrator).

    user_id is accepted for call-site stability; not echoed here (gold scoping is infra).
    effective_autonomy is stamped as intent — gates still own allow/deny.
    """
    _ = user_id
    workspace_path = agent.workspace.path if agent.workspace else "(none)"
    return f"""# Office rules (do not ignore)

Follow your persona for this desk. Use only the packed context in this prompt.

## Controllability
Effective autonomy for this run: {effective_autonomy}/100.
Lower → prefer asking / waiting on gated tools; higher → act within listed tools and workspace.
Do not bypass locks, approvals, or tool gates.

## Must
- Stay in your persona (mission, tone, role). Do not invent other identities, tools, or a fictional workspace.
- Use packed context + persona only; if you lack a fact, say so — do not invent company truth.
- Recent thread is continuity of asks only — not durable truth; prefer gold and team OKF for facts.
- Gold is your personal working notes. Prefer append_gold / delete_gold / clear_gold (and read_gold); do not invent notes that are not there.
- Do not write shared OKF; do not store secrets in gold or replies.
- Use only tools listed for this run; if locked/gated, wait — do not bypass.
- File work stays under `{workspace_path}` only.
"""
