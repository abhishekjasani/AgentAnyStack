"""Agent desk HTTP routes (list only in P2 — create in P3)."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from agent_anystack.config import Settings, get_settings
from agent_anystack.domain.agent import AgentSummary
from agent_anystack.domain.org import OrgConfig
from agent_anystack.office import OfficeRepository

router = APIRouter(tags=["agents"])


def get_office_repo(settings: Settings = Depends(get_settings)) -> OfficeRepository:
    return OfficeRepository(Path(settings.office_repo_path))


@router.get("/agents", response_model=list[AgentSummary])
async def list_agents(
    repo: OfficeRepository = Depends(get_office_repo),
) -> list[AgentSummary]:
    """Desks from office git. Empty until UI creates agents (P3)."""
    return repo.list_agent_summaries()


@router.get("/org", response_model=OrgConfig)
async def get_org(repo: OfficeRepository = Depends(get_office_repo)) -> OrgConfig:
    try:
        return repo.load_org()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
