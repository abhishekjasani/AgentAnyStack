"""OKF fact contract (Pydantic) — shared long-term memory row."""

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class FactType(str, Enum):
    decision = "decision"
    constraint = "constraint"
    fact = "fact"
    glossary = "glossary"
    procedure = "procedure"
    contact_policy = "contact_policy"
    offer = "offer"
    outcome = "outcome"
    risk = "risk"


class Sensitivity(str, Enum):
    public = "public"
    internal = "internal"
    customer = "customer"
    legal = "legal"


def new_fact_id() -> str:
    return f"fact-{uuid4().hex[:16]}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class OkfFact(BaseModel):
    """One shared OKF fact (team room in v0). Pipeline/admin write — not the desk LLM."""

    id: str = Field(default_factory=new_fact_id)
    type: FactType = FactType.fact
    scope: str = Field(
        ...,
        description="e.g. team:eng — v0 packs team scope only",
        pattern=r"^team:[a-z][a-z0-9_-]*$",
    )
    projects: list[str] = Field(default_factory=list)
    body: str = Field(..., min_length=1, max_length=8000)
    tags: list[str] = Field(default_factory=list)
    domain: str = "general"
    created_by_user: str = "anonymous"
    created: str = Field(default_factory=utc_now_iso)
    pinned: bool = False
    archived: bool = False
    sensitivity: Sensitivity = Sensitivity.internal
    source_run: str | None = None


class CreateOkfFactRequest(BaseModel):
    """Manual / seed write until extract pipeline exists."""

    body: str = Field(..., min_length=1, max_length=8000)
    team: str = Field(..., pattern=r"^[a-z][a-z0-9_-]*$", min_length=1, max_length=64)
    type: FactType = FactType.fact
    projects: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    domain: str = "general"
    sensitivity: Sensitivity = Sensitivity.internal
    pinned: bool = False
