"""Office Q&A — front desk: status + OKF retrieve → optional soft LLM phrase."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from agent_anystack.adapters.llm import OpenAICompatibleAdapter
from agent_anystack.memory.fact import OkfFact
from agent_anystack.memory.okf_retrieve import (
    PassThroughRetriever,
    TokenOverlapRetriever,
    tokenize,
)
from agent_anystack.memory.okf_soft import OkfSoftAnswer
from agent_anystack.memory.store import OkfStore
from agent_anystack.runs.journal import JournalEntry, RunJournal

_STATUS_HINTS = re.compile(
    r"\b(status|running|who\s+ran|recent\s+runs?|activity|journal|what'?s\s+going)\b",
    re.I,
)
_WORK_HINTS = re.compile(
    r"\b(build|implement|deploy|send|email|call|refactor|fix|write\s+code|create\s+pr)\b",
    re.I,
)
_CHITCHAT = re.compile(
    r"^(hi|hello|hey|yo|sup|thanks|thank\s+you|ok|okay|bye)[\s!.?]*$",
    re.I,
)


class OfficeAskKind(str, Enum):
    status = "status"
    knowledge = "knowledge"
    work = "work"
    empty = "empty"


@dataclass
class Citation:
    fact_id: str | None = None
    run_id: str | None = None


@dataclass
class OfficeAskResult:
    kind: OfficeAskKind
    answer: str
    citations: list[Citation]
    team: str


def classify_office_ask(message: str) -> OfficeAskKind:
    if _is_chitchat(message):
        return OfficeAskKind.empty
    if _WORK_HINTS.search(message) and not _STATUS_HINTS.search(message):
        if not _looks_like_knowledge(message):
            return OfficeAskKind.work
    if _STATUS_HINTS.search(message):
        return OfficeAskKind.status
    return OfficeAskKind.knowledge


def _is_chitchat(message: str) -> bool:
    t = (message or "").strip()
    if not t:
        return True
    if _CHITCHAT.match(t):
        return True
    # Very short with no ≥3-letter tokens (e.g. "hi", "ok") — not knowledge lookup.
    if len(t) <= 12 and not tokenize(t):
        return True
    return False


def _looks_like_knowledge(message: str) -> bool:
    return bool(
        re.search(
            r"\b(what|what'?s|whats|how|when|policy|rule|commission|know|fact|mean)\b",
            message,
            re.I,
        )
    )


def match_facts(query: str, facts: list[OkfFact], *, limit: int = 8) -> list[OkfFact]:
    """Token overlap helper (tests / callers). Empty query → [] (no room dump)."""
    q = tokenize(query)
    if not q:
        return []
    scored: list[tuple[int, OkfFact]] = []
    for fact in facts:
        score = len(q & tokenize(fact.body))
        if score > 0:
            scored.append((score, fact))
    scored.sort(key=lambda x: -x[0])
    return [f for _, f in scored[:limit]]


def format_status(entries: list[JournalEntry]) -> OfficeAskResult:
    if not entries:
        return OfficeAskResult(
            kind=OfficeAskKind.empty,
            answer="No recent runs in the journal for this team.",
            citations=[],
            team="",
        )
    team = entries[-1].team
    lines = ["Recent runs (newest last):"]
    citations: list[Citation] = []
    for e in entries:
        lines.append(
            f"- [{e.run_id}] agent={e.agent_id} user={e.user_id} "
            f"status={e.status} at {e.started_at}"
        )
        citations.append(Citation(run_id=e.run_id))
    return OfficeAskResult(
        kind=OfficeAskKind.status,
        answer="\n".join(lines),
        citations=citations,
        team=team,
    )


def format_knowledge(facts: list[OkfFact], *, team: str) -> OfficeAskResult:
    if not facts:
        return OfficeAskResult(
            kind=OfficeAskKind.empty,
            answer=(
                f"No matching team OKF facts for team:{team}. "
                "I will not invent company knowledge."
            ),
            citations=[],
            team=team,
        )
    lines = [f"From team OKF (team:{team}):"]
    citations: list[Citation] = []
    for f in facts:
        lines.append(f"- [{f.id}] {f.body}")
        citations.append(Citation(fact_id=f.id))
    return OfficeAskResult(
        kind=OfficeAskKind.knowledge,
        answer="\n".join(lines),
        citations=citations,
        team=team,
    )


_WORK_ANSWER = (
    "That sounds like work for a desk agent (side effects / build). "
    "Open Team → pick a desk → Chat. Office Q&A is read-only status and knowledge."
)

_CHITCHAT_ANSWER = (
    "Hello — I'm the office front desk. Ask about team knowledge or recent run status. "
    "For build/work, open a desk on Team → Chat."
)


class OfficeQaService:
    def __init__(
        self,
        journal: RunJournal,
        okf: OkfStore,
        *,
        adapter: OpenAICompatibleAdapter | None = None,
        phrase_model: str | None = None,
        use_llm_phrase: bool = False,
        max_tokens: int | None = None,
        pack_char_budget: int | None = None,
    ) -> None:
        self.journal = journal
        self.okf = okf
        self.adapter = adapter
        self.phrase_model = phrase_model
        self.use_llm_phrase = use_llm_phrase
        self.max_tokens = max_tokens
        # Soft path: hand entire room (capped) to OFFICE_MODEL.
        max_chars = pack_char_budget if pack_char_budget and pack_char_budget > 0 else None
        self._pass_through = PassThroughRetriever(
            okf, max_facts=80, max_chars=max_chars
        )
        # Deterministic path when soft LLM off.
        self._overlap = TokenOverlapRetriever(okf, max_facts=8)
        self._soft: OkfSoftAnswer | None = None
        if use_llm_phrase and adapter and phrase_model:
            self._soft = OkfSoftAnswer(
                adapter, model=phrase_model, max_tokens=max_tokens
            )

    async def ask(self, *, message: str, team: str) -> OfficeAskResult:
        kind = classify_office_ask(message)
        if kind == OfficeAskKind.empty and _is_chitchat(message):
            return OfficeAskResult(
                kind=OfficeAskKind.empty,
                answer=_CHITCHAT_ANSWER,
                citations=[],
                team=team,
            )
        if kind == OfficeAskKind.work:
            return OfficeAskResult(
                kind=OfficeAskKind.work,
                answer=_WORK_ANSWER,
                citations=[],
                team=team,
            )
        if kind == OfficeAskKind.status:
            entries = self.journal.recent(15, team=team)
            result = format_status(entries)
            result.team = team
            return result

        # Knowledge: soft LLM gets pass-through slice; else token overlap only.
        if self._soft is not None:
            facts = self._pass_through.retrieve(message, team=team)
            if not facts:
                return format_knowledge([], team=team)
            soft = await self._soft.answer(message, facts)
            if soft:
                return OfficeAskResult(
                    kind=OfficeAskKind.knowledge,
                    answer=soft.text,
                    citations=[Citation(fact_id=i) for i in soft.cited_ids],
                    team=team,
                )
            # Model failed citation check — fall back to deterministic list of same slice.
            return format_knowledge(facts[:8], team=team)

        facts = self._overlap.retrieve(message, team=team)
        return format_knowledge(facts, team=team)
