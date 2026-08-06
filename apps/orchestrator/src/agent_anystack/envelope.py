"""Fixed Office Envelope — musts + workspace + autonomy intent; role in AGENT.md."""

from agent_anystack.domain.agent import AgentConfig


def build_office_envelope(
    *,
    agent: AgentConfig,
    user_id: str,
    effective_autonomy: int,
) -> str:
    """Office law for the LLM. Identity/routing stay in orchestrator + journal.

    user_id is accepted for call-site stability / future gold labels; not echoed here.
    effective_autonomy is stamped as intent — gates still own allow/deny.
    """
    _ = user_id  # owned by FastAPI / gold pack — not prompt overhead
    workspace_path = agent.workspace.path if agent.workspace else "(none)"
    return f"""# Office rules (do not ignore)

The orchestrator packs memory, gates tools, and approvals. You execute the task in your persona.

## Controllability
Effective autonomy for this run: {effective_autonomy}/100.
Lower → prefer asking / waiting on gated tools; higher → act within listed tools and workspace.
The office still gates tools and approvals — do not bypass locks.

## Must
- Use packed context + persona only; if you lack a fact, say so — do not invent company truth.
- Do not write shared OKF; do not store secrets in gold or replies.
- Use only tools listed for this run; if locked/gated, wait — do not bypass.
- File work stays under `{workspace_path}` only. Sampling is owned by the office.
"""
