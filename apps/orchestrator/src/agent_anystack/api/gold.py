"""Per-user gold notepad — gold(a,u) under agents/<id>/gold/<user_id>.md.

Primary write path: agent tools read_gold / update_gold (orchestrator-mediated).
HTTP PUT/DELETE remain for ops; Memory UI is view-only.
"""

from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException, status

from agent_anystack.api.agents import get_office_repo
from agent_anystack.api.deps import get_user_id
from agent_anystack.config import Settings, get_settings
from agent_anystack.office import GoldTooLargeError, OfficeRepository

router = APIRouter(tags=["gold"])


class GoldResponse(BaseModel):
    agent_id: str
    user_id: str
    content: str


class GoldWriteRequest(BaseModel):
    """Length capped in put_gold via Settings.gold_max_chars (not a fixed Field)."""

    content: str = Field(default="")


@router.get("/agents/{agent_id}/gold", response_model=GoldResponse)
async def get_gold(
    agent_id: str,
    user_id: str = Depends(get_user_id),
    repo: OfficeRepository = Depends(get_office_repo),
) -> GoldResponse:
    agent = repo.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent not found: {agent_id}")
    return GoldResponse(
        agent_id=agent.id,
        user_id=user_id,
        content=repo.read_gold(agent, user_id),
    )


@router.put("/agents/{agent_id}/gold", response_model=GoldResponse)
async def put_gold(
    agent_id: str,
    body: GoldWriteRequest,
    user_id: str = Depends(get_user_id),
    repo: OfficeRepository = Depends(get_office_repo),
    settings: Settings = Depends(get_settings),
) -> GoldResponse:
    agent = repo.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent not found: {agent_id}")
    if len(body.content) > settings.gold_max_chars:
        raise HTTPException(
            status_code=400,
            detail=(
                f"gold exceeds {settings.gold_max_chars} characters "
                f"({len(body.content)})"
            ),
        )
    try:
        repo.write_gold(agent, user_id, body.content)
    except GoldTooLargeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GoldResponse(
        agent_id=agent.id,
        user_id=user_id,
        content=repo.read_gold(agent, user_id),
    )


@router.delete("/agents/{agent_id}/gold", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gold(
    agent_id: str,
    user_id: str = Depends(get_user_id),
    repo: OfficeRepository = Depends(get_office_repo),
) -> None:
    """Reset gold(a,u) for the current user."""
    agent = repo.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent not found: {agent_id}")
    repo.write_gold(agent, user_id, "")
