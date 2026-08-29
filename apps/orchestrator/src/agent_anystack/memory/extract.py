"""Post-run OKF extract — async, never blocks the chat SSE."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from agent_anystack.memory.fact import FactType, OkfFact
from agent_anystack.memory.store import OkfStore

logger = logging.getLogger(__name__)

_EXTRACT_SYSTEM = """You extract durable team knowledge facts from a chat turn.
Rules:
- Extract ONLY statements clearly present in the user or assistant text.
- Do not invent, infer, or add world knowledge.
- Skip greetings, chit-chat, and one-off task noise.
- Prefer atomic one-sentence facts.
- Return JSON only: {"facts":[{"type":"fact|decision|constraint|glossary|procedure|outcome|risk","body":"..."}]}
- If nothing durable, return {"facts":[]}
"""


@dataclass
class ExtractJob:
    run_id: str
    agent_id: str
    user_id: str
    team: str
    model: str
    user_message: str
    assistant_text: str
    project_id: str | None = None


def _parse_facts_json(raw: str) -> list[dict]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
    facts = data.get("facts") if isinstance(data, dict) else None
    if not isinstance(facts, list):
        return []
    return [f for f in facts if isinstance(f, dict)]


def _remember_line_facts(user_message: str) -> list[dict]:
    """Deterministic fallback: 'remember: …' lines in the user message."""
    out: list[dict] = []
    for line in user_message.splitlines():
        m = re.match(r"^\s*remember:\s*(.+)$", line, flags=re.IGNORECASE)
        if m:
            body = m.group(1).strip()
            if body:
                out.append({"type": "fact", "body": body})
    return out


async def run_okf_extract(
    job: ExtractJob,
    *,
    okf: OkfStore,
    adapter: Any,
    max_tokens: int | None = None,
    temperature: float = 0.0,
    use_llm: bool = True,
    use_remember_lines: bool = True,
) -> int:
    """
    Extract facts and upsert into team OKF. Returns count written.

    Uses job.model — callers must set the orchestrator office_model (not desk model).
    Failures are logged — never raised to the chat client.

    use_llm / use_remember_lines are independent (gated by okf_extract_* in yaml).
    """
    if not job.assistant_text.strip() and not job.user_message.strip():
        return 0

    candidates: list[dict] = []
    if use_remember_lines:
        candidates.extend(_remember_line_facts(job.user_message))

    if use_llm:
        try:
            if adapter is None:
                raise ValueError("No adapter provided for LLM extract")
            raw = await adapter.complete_chat(
                model=job.model,
                messages=[
                    {"role": "system", "content": _EXTRACT_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"User message:\n{job.user_message}\n\n"
                            f"Assistant reply:\n{job.assistant_text}"
                        ),
                    },
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            candidates.extend(_parse_facts_json(raw))
        except Exception as exc:
            logger.warning("okf extract LLM failed run=%s: %s", job.run_id, exc)

    # Fallback to deterministic remember lines if LLM threw an error or produced 0 parseable facts
    if not candidates:
        candidates.extend(_remember_line_facts(job.user_message))

    if not candidates:
        return 0

    written = 0
    seen_bodies: set[str] = set()
    projects = [job.project_id] if job.project_id else []

    for item in candidates:
        body = str(item.get("body") or "").strip()
        if not body or body.lower() in seen_bodies:
            continue
        seen_bodies.add(body.lower())
        type_raw = str(item.get("type") or "fact").strip().lower()
        try:
            ftype = FactType(type_raw)
        except ValueError:
            ftype = FactType.fact
        fact = OkfFact(
            type=ftype,
            scope=f"team:{job.team}",
            projects=projects,
            body=body,
            created_by_user=job.user_id,
            source_run=job.run_id,
        )
        okf.upsert(fact)
        written += 1

    if written:
        logger.info(
            "okf extract run=%s team=%s wrote=%s llm=%s remember=%s",
            job.run_id,
            job.team,
            written,
            use_llm,
            use_remember_lines,
        )
    return written
