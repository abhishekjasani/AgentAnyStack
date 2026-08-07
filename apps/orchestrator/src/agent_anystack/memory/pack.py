"""Pack C(a,p,u) for a run — v0: gold(a,u) ∪ mem(team). Shelf ∩ P(p) later."""

from __future__ import annotations

from agent_anystack.memory.fact import OkfFact


def format_gold_section(gold: str) -> str:
    """Agent-facing gold — no user_id / path (orchestrator owns scoping)."""
    body = gold.strip() if gold.strip() else "(empty)"
    return (
        "## Gold (your working notes)\n\n"
        "Your personal notepad for this desk. Prefer read_gold before changing; "
        "use update_gold for durable bullets only — never dump the whole chat. "
        "Not shared OKF.\n\n"
        f"{body}"
    )


def format_team_okf_section(facts: list[OkfFact], *, char_budget: int) -> str | None:
    """Render team facts under budget. created_by_user is label only — not a filter."""
    if not facts or char_budget <= 0:
        return None

    header = (
        "## Team OKF (shared room)\n\n"
        "Shared facts for this team. Cite fact ids when using them. "
        "Do not invent company truth beyond this pack + gold + persona.\n\n"
    )
    used = len(header)
    lines: list[str] = []
    for fact in facts:
        projects = ",".join(fact.projects) if fact.projects else "agnostic"
        block = (
            f"- [{fact.id}] ({fact.type.value}, {projects}"
            f", by {fact.created_by_user}): {fact.body.strip()}\n"
        )
        if used + len(block) > char_budget:
            break
        lines.append(block)
        used += len(block)

    if not lines:
        return None
    return header + "".join(lines)


def pack_memory_sections(
    *,
    user_id: str,
    gold: str,
    team_facts: list[OkfFact],
    pack_token_budget: int,
) -> list[str]:
    """
    Build markdown sections for the system prompt.

    v0: C(a,p,u) ≈ gold ∪ mem(team). Floor/org ∩ P(p) not packed yet.
    Budget is approximate chars (~4 chars/token heuristic).
    user_id is call-site / pack identity only — not echoed in gold section.
    """
    _ = user_id
    char_budget = max(500, pack_token_budget * 4)
    sections: list[str] = []

    gold_sec = format_gold_section(gold)
    sections.append(gold_sec)
    char_budget -= len(gold_sec)

    okf_sec = format_team_okf_section(team_facts, char_budget=max(0, char_budget))
    if okf_sec:
        sections.append(okf_sec)

    return sections
