"""Office soft LLM layer — cite-bound phrase over a retrieved OKF slice.

Last hop of: filter → rank → OFFICE_MODEL. Callers pass whatever the retriever
selected (v0 may pass the whole capped room). Never invent; empty slice → no call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_anystack.memory.fact import OkfFact

_SYSTEM = (
    "You are the office front desk. Answer ONLY using the listed facts. "
    "Every claim must include a citation like [fact-xxx] using an id from the list. "
    "If the facts do not answer the question, say so clearly. Do not invent."
)


@dataclass(frozen=True)
class SoftAnswerResult:
    text: str
    cited_ids: list[str]


class OkfSoftAnswer:
    """Summarize / phrase from retrieved facts via OFFICE_MODEL."""

    def __init__(
        self,
        adapter: Any,
        *,
        model: str,
        max_tokens: int | None = None,
        temperature: float = 0.2,
    ) -> None:
        self.adapter = adapter
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    async def answer(
        self,
        question: str,
        facts: list[OkfFact],
    ) -> SoftAnswerResult | None:
        if not facts:
            return None
        catalog = "\n".join(f"- [{f.id}] {f.body}" for f in facts)
        known = {f.id for f in facts}
        try:
            text = await self.adapter.complete_chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {
                        "role": "user",
                        "content": f"Question: {question}\n\nFacts:\n{catalog}",
                    },
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
        except Exception:  # noqa: BLE001 — caller falls back to deterministic list
            return None
        text = (text or "").strip()
        if not text:
            return None
        cited = [fid for fid in known if fid in text]
        if not cited:
            return None
        return SoftAnswerResult(text=text, cited_ids=cited)
