"""Recent channel thread pack — continuity only (not OKF / gold)."""

from __future__ import annotations

from agent_anystack.channel_history import ChannelMessage

_ASSISTANT_MAX = 240
_USER_MAX = 600


def format_recent_thread_section(
    messages: list[ChannelMessage],
    *,
    days: int,
    char_budget: int,
) -> str | None:
    """
    Render recent user-channel turns for the system prompt.

    Prefer user lines (more budget); truncate long assistant/office replies.
    Not company truth — continuity of what the human has been asking.
    """
    if not messages or char_budget <= 0 or days <= 0:
        return None

    header = (
        f"## Recent thread (last {days} days)\n\n"
        "Continuity of recent asks in this channel — not gold and not shared OKF. "
        "Use for intent; durable facts live in gold / team OKF.\n\n"
    )
    used = len(header)
    # Build from newest so we keep the most recent turns under budget, then reverse.
    blocks_rev: list[str] = []
    for m in reversed(messages):
        text = (m.text or "").strip()
        if not text:
            continue
        role = m.role if m.role in ("user", "assistant", "office") else "assistant"
        max_len = _USER_MAX if role == "user" else _ASSISTANT_MAX
        if len(text) > max_len:
            text = text[: max_len - 1].rstrip() + "…"
        label = "User" if role == "user" else ("Office" if role == "office" else "Assistant")
        desk = f" ({m.agent_id})" if m.agent_id and role == "assistant" else ""
        block = f"- {label}{desk}: {text}\n"
        if used + len(block) > char_budget:
            break
        blocks_rev.append(block)
        used += len(block)

    if not blocks_rev:
        return None
    blocks_rev.reverse()
    return header + "".join(blocks_rev)
