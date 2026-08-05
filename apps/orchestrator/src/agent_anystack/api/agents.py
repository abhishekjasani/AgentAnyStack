"""Agent desk HTTP routes — list / get / create (UI path; no seed desks)."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from agent_anystack.api.deps import get_user_id
from agent_anystack.config import Settings, get_settings
from agent_anystack.domain.agent import AgentConfig, AgentSummary, CreateAgentRequest
from agent_anystack.domain.org import OrgConfig
from agent_anystack.office import (
    AgentExistsError,
    AutonomyCeilingError,
    OfficeRepository,
)

router = APIRouter(tags=["agents"])


def get_office_repo(settings: Settings = Depends(get_settings)) -> OfficeRepository:
    return OfficeRepository(Path(settings.office_repo_path))


@router.get("/agents", response_model=list[AgentSummary])
async def list_agents(
    repo: OfficeRepository = Depends(get_office_repo),
    _user_id: str = Depends(get_user_id),
) -> list[AgentSummary]:
    """Desks from office git. Empty until UI/API creates agents."""
    return repo.list_agent_summaries()


@router.get("/agents/{agent_id}", response_model=AgentConfig)
async def get_agent(
    agent_id: str,
    repo: OfficeRepository = Depends(get_office_repo),
    _user_id: str = Depends(get_user_id),
) -> AgentConfig:
    agent = repo.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent not found: {agent_id}")
    return agent


@router.post(
    "/agents",
    response_model=AgentConfig,
    status_code=status.HTTP_201_CREATED,
)
async def create_agent(
    body: CreateAgentRequest,
    repo: OfficeRepository = Depends(get_office_repo),
    _user_id: str = Depends(get_user_id),
) -> AgentConfig:
    """Write office/teams/<team>/agents/<id>/ (agent.yaml + AGENT.md + gold/)."""
    try:
        return repo.create_agent(body)
    except AgentExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AutonomyCeilingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: str,
    repo: OfficeRepository = Depends(get_office_repo),
    _user_id: str = Depends(get_user_id),
) -> None:
    """Remove desk folder from office git tree."""
    try:
        repo.delete_agent(agent_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/org", response_model=OrgConfig)
async def get_org(repo: OfficeRepository = Depends(get_office_repo)) -> OrgConfig:
    try:
        return repo.load_org()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
