"""OKF retrieve slice for Office soft answer.

Future: filter (scope · project) → FTS/vector rank → top-K.
v0: PassThroughRetriever hands the whole team room (capped) to the soft LLM.
"""

from __future__ import annotations

import re
from typing import Protocol

from agent_anystack.memory.fact import OkfFact
from agent_anystack.memory.store import OkfStore

_DEFAULT_MAX_FACTS = 80


class OkfRetriever(Protocol):
    """Select facts to hand to OkfSoftAnswer (or deterministic list)."""

    def retrieve(
        self,
        query: str,
        *,
        team: str,
        limit: int | None = None,
    ) -> list[OkfFact]:
        ...


def tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]{3,}", text.lower()) if t}


class PassThroughRetriever:
    """v0: entire team OKF (newest-first), hard-capped — interface-ready for rank later."""

    def __init__(
        self,
        okf: OkfStore,
        *,
        max_facts: int = _DEFAULT_MAX_FACTS,
        max_chars: int | None = None,
    ) -> None:
        self.okf = okf
        self.max_facts = max(1, max_facts)
        self.max_chars = max_chars

    def retrieve(
        self,
        query: str,
        *,
        team: str,
        limit: int | None = None,
    ) -> list[OkfFact]:
        _ = query  # reserved for FTS/vector
        cap = limit if limit is not None else self.max_facts
        facts = self.okf.list_team_facts(team)
        # Prefer newer rows when capping.
        facts = sorted(facts, key=lambda f: f.created, reverse=True)
        out: list[OkfFact] = []
        used = 0
        for f in facts:
            body = (f.body or "").strip()
            if not body:
                continue
            block_len = len(body) + len(f.id) + 8
            if self.max_chars is not None and out and used + block_len > self.max_chars:
                break
            out.append(f)
            used += block_len
            if len(out) >= cap:
                break
        return out


class TokenOverlapRetriever:
    """Legacy Office matcher — score > 0 only (no empty-query dump of the room)."""

    def __init__(self, okf: OkfStore, *, max_facts: int = 8) -> None:
        self.okf = okf
        self.max_facts = max(1, max_facts)

    def retrieve(
        self,
        query: str,
        *,
        team: str,
        limit: int | None = None,
    ) -> list[OkfFact]:
        cap = limit if limit is not None else self.max_facts
        facts = self.okf.list_team_facts(team)
        q = tokenize(query)
        if not q:
            return []
        scored: list[tuple[int, OkfFact]] = []
        for fact in facts:
            score = len(q & tokenize(fact.body))
            if score > 0:
                scored.append((score, fact))
        scored.sort(key=lambda x: -x[0])
        return [f for _, f in scored[:cap]]
