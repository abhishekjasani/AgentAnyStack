"""Office front-desk Q&A — status + cited knowledge (no desk agent)."""

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agent_anystack.adapters.llm import OpenAICompatibleAdapter
from agent_anystack.api.deps import get_user_id
from agent_anystack.config import Settings, get_settings
from agent_anystack.memory import OkfStore, sqlite_path_from_database_url
from agent_anystack.office_qa import OfficeAskKind, OfficeQaService
from agent_anystack.runs.journal import RunJournal
from agent_anystack.runs.service import journal_path_from_database_url

router = APIRouter(tags=["office"])


class OfficeAskRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    team: str = Field(default="eng", pattern=r"^[a-z][a-z0-9_-]*$")


class CitationOut(BaseModel):
    fact_id: str | None = None
    run_id: str | None = None


class OfficeAskResponse(BaseModel):
    kind: OfficeAskKind
    answer: str
    citations: list[CitationOut]
    team: str


def get_office_qa(settings: Settings = Depends(get_settings)) -> OfficeQaService:
    journal = RunJournal(
        journal_path_from_database_url(settings.database_url, Path("./data"))
    )
    okf = OkfStore(sqlite_path_from_database_url(settings.database_url))
    adapter = None
    model = None
    if settings.office_qa_llm:
        adapter = OpenAICompatibleAdapter(
            settings.openai_compatible_base_url,
            timeout=settings.openai_compatible_timeout,
        )
        model = settings.office_model
    return OfficeQaService(
        journal,
        okf,
        adapter=adapter,
        phrase_model=model,
        use_llm_phrase=settings.office_qa_llm,
    )


@router.post("/office/ask", response_model=OfficeAskResponse)
async def office_ask(
    body: OfficeAskRequest,
    _user_id: str = Depends(get_user_id),
    qa: OfficeQaService = Depends(get_office_qa),
) -> OfficeAskResponse:
    """Front desk: journal status or OKF knowledge with citations. Read-only."""
    result = await qa.ask(message=body.message.strip(), team=body.team)
    return OfficeAskResponse(
        kind=result.kind,
        answer=result.answer,
        citations=[
            CitationOut(fact_id=c.fact_id, run_id=c.run_id) for c in result.citations
        ],
        team=result.team or body.team,
    )
