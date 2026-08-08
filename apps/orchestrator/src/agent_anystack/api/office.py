"""Office front-desk Q&A + orchestrator.yaml config (pinned Office card)."""

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agent_anystack.adapters.llm import OpenAICompatibleAdapter
from agent_anystack.api.agents import get_office_repo
from agent_anystack.api.deps import get_user_id
from agent_anystack.config import Settings, get_settings
from agent_anystack.domain.orchestrator import (
    OrchestratorConfig,
    OrchestratorConfigUpdate,
)
from agent_anystack.domain.org import OrgConfig
from agent_anystack.memory import OkfStore, sqlite_path_from_database_url
from agent_anystack.office import OfficeRepository
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


class OfficeConfigResponse(BaseModel):
    """Pinned Office card payload — soft jobs + org ceiling (read)."""

    orchestrator: OrchestratorConfig
    org: OrgConfig
    # TODO: expose todos / planned knobs as structured list for UI


def get_office_qa(
    settings: Settings = Depends(get_settings),
    repo: OfficeRepository = Depends(get_office_repo),
) -> OfficeQaService:
    from agent_anystack.limits import resolve_run_limits

    orc = repo.load_orchestrator()
    journal = RunJournal(
        journal_path_from_database_url(settings.database_url, Path("./data"))
    )
    okf = OkfStore(sqlite_path_from_database_url(settings.database_url))
    adapter = None
    model = None
    num_ctx = None
    max_tokens = None
    if orc.office_qa_llm:
        adapter = OpenAICompatibleAdapter(
            settings.openai_compatible_base_url,
            timeout=settings.openai_compatible_timeout,
        )
        model = orc.model
        limits = resolve_run_limits(model=orc.model, orc=orc, agent=None)
        num_ctx = limits.num_ctx
        max_tokens = limits.max_output_tokens
    return OfficeQaService(
        journal,
        okf,
        adapter=adapter,
        phrase_model=model,
        use_llm_phrase=orc.office_qa_llm,
        num_ctx=num_ctx,
        max_tokens=max_tokens,
    )


@router.get("/office/config", response_model=OfficeConfigResponse)
async def get_office_config(
    repo: OfficeRepository = Depends(get_office_repo),
    _user_id: str = Depends(get_user_id),
) -> OfficeConfigResponse:
    """Office card + Configure form — from office/orchestrator.yaml (+ org.yaml)."""
    return OfficeConfigResponse(
        orchestrator=repo.load_orchestrator(),
        org=repo.load_org(),
    )


@router.put("/office/config", response_model=OfficeConfigResponse)
async def put_office_config(
    body: OrchestratorConfigUpdate,
    repo: OfficeRepository = Depends(get_office_repo),
    _user_id: str = Depends(get_user_id),
) -> OfficeConfigResponse:
    """Persist Office soft knobs to office/orchestrator.yaml."""
    # TODO: admin-only write when ORG_ADMINS enforcement ships for this route
    orc = repo.update_orchestrator(body)
    return OfficeConfigResponse(orchestrator=orc, org=repo.load_org())


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
