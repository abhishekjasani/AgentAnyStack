"""Pack C(a,p,u) for a run — gold ∪ mem(team) ∪ recent thread. Shelf ∩ P(p) later."""

from __future__ import annotations

from agent_anystack.channel_history import ChannelMessage
from agent_anystack.memory.fact import OkfFact
from agent_anystack.memory.recent import format_recent_thread_section
from agent_anystack.office.gold_notes import GoldNote, format_gold_with_rules


def format_gold_section(notes: list[GoldNote] | str) -> str:
    """Agent-facing gold — rules + id rows; no user_id / path."""
    if isinstance(notes, str):
        from agent_anystack.office.gold_notes import GOLD_RULES

        body = notes.strip() if notes.strip() else "(empty)"
        return f"## Gold (your working notes)\n\n{GOLD_RULES}\n\n{body}"
    return format_gold_with_rules(notes)


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
    gold: str | list[GoldNote],
    team_facts: list[OkfFact],
    pack_token_budget: int,
    recent_messages: list[ChannelMessage] | None = None,
    recent_history_days: int = 7,
    recent_history_char_budget: int = 6_000,
) -> list[str]:
    """
    Build markdown sections for the system prompt.

    v0: C ≈ gold ∪ mem(team) ∪ recent thread. Floor/org ∩ P(p) not packed yet.
    user_id is call-site identity only — not echoed in gold section.
    """
    _ = user_id
    char_budget = max(500, pack_token_budget * 4)
    sections: list[str] = []

    gold_sec = format_gold_section(gold)
    sections.append(gold_sec)
    char_budget -= len(gold_sec)

    recent_budget = min(recent_history_char_budget, max(0, char_budget // 2))
    recent_sec = format_recent_thread_section(
        recent_messages or [],
        days=recent_history_days,
        char_budget=recent_budget,
    )
    if recent_sec:
        sections.append(recent_sec)
        char_budget -= len(recent_sec)

    okf_sec = format_team_okf_section(team_facts, char_budget=max(0, char_budget))
    if okf_sec:
        sections.append(okf_sec)

    return sections
