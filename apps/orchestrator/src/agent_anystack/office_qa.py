"""Office Q&A — front desk: status + cited knowledge (no desk agent)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from agent_anystack.adapters.llm import OpenAICompatibleAdapter
from agent_anystack.memory.fact import OkfFact
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
    if _WORK_HINTS.search(message) and not _STATUS_HINTS.search(message):
        # work-like without status → route to agent
        if not _looks_like_knowledge(message):
            return OfficeAskKind.work
    if _STATUS_HINTS.search(message):
        return OfficeAskKind.status
    return OfficeAskKind.knowledge


def _looks_like_knowledge(message: str) -> bool:
    return bool(
        re.search(
            r"\b(what|what'?s|whats|how|when|policy|rule|commission|know|fact|mean)\b",
            message,
            re.I,
        )
    )


def _tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]{3,}", text.lower()) if t}


def match_facts(query: str, facts: list[OkfFact], *, limit: int = 8) -> list[OkfFact]:
    q = _tokenize(query)
    if not q:
        return facts[:limit]
    scored: list[tuple[int, OkfFact]] = []
    for fact in facts:
        body_tokens = _tokenize(fact.body)
        score = len(q & body_tokens)
        if score > 0:
            scored.append((score, fact))
    scored.sort(key=lambda x: (-x[0], x[1].created), reverse=False)
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


class OfficeQaService:
    def __init__(
        self,
        journal: RunJournal,
        okf: OkfStore,
        *,
        adapter: OpenAICompatibleAdapter | None = None,
        phrase_model: str | None = None,
        use_llm_phrase: bool = False,
        num_ctx: int | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.journal = journal
        self.okf = okf
        self.adapter = adapter
        self.phrase_model = phrase_model
        self.use_llm_phrase = use_llm_phrase
        self.num_ctx = num_ctx
        self.max_tokens = max_tokens

    async def ask(self, *, message: str, team: str) -> OfficeAskResult:
        kind = classify_office_ask(message)
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

        facts = match_facts(message, self.okf.list_team_facts(team))
        result = format_knowledge(facts, team=team)
        if (
            result.kind == OfficeAskKind.knowledge
            and self.use_llm_phrase
            and self.adapter
            and self.phrase_model
            and facts
        ):
            phrased = await self._phrase_with_citations(message, facts)
            if phrased:
                result.answer = phrased
        return result

    async def _phrase_with_citations(
        self,
        question: str,
        facts: list[OkfFact],
    ) -> str | None:
        assert self.adapter and self.phrase_model
        catalog = "\n".join(f"- [{f.id}] {f.body}" for f in facts)
        system = (
            "You are the office front desk. Answer ONLY using the listed facts. "
            "Every claim must include a citation like [fact-xxx]. "
            "If the facts do not answer the question, say so. Do not invent."
        )
        try:
            text = await self.adapter.complete_chat(
                model=self.phrase_model,
                messages=[
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": f"Question: {question}\n\nFacts:\n{catalog}",
                    },
                ],
                temperature=0.0,
                num_ctx=self.num_ctx,
                max_tokens=self.max_tokens,
            )
        except Exception:  # noqa: BLE001 — fall back to deterministic list
            return None
        # Require at least one known fact id in the phrase
        if not any(f.id in text for f in facts):
            return None
        return text.strip() or None
