"""Per-user gold notepad — gold(a,u) as gold/<user_id>.jsonl (id-addressable notes).

Primary write path: agent tools read_gold / append_gold / delete_gold / clear_gold.
HTTP GET (view) + PUT/DELETE (ops); Memory UI is view-only.
"""

from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException, status

from agent_anystack.api.agents import get_office_repo
from agent_anystack.api.deps import get_user_id
from agent_anystack.config import Settings, get_settings
from agent_anystack.office import GoldTooLargeError, OfficeRepository
from agent_anystack.office.gold_notes import format_gold_with_rules

router = APIRouter(tags=["gold"])


class GoldNoteOut(BaseModel):
    id: str
    text: str
    run_id: str | None = None
    created_at: str | None = None


class GoldResponse(BaseModel):
    agent_id: str
    user_id: str
    content: str
    entries: list[GoldNoteOut] = Field(default_factory=list)


class GoldWriteRequest(BaseModel):
    """Ops replace: non-empty lines become notes. Length capped via Settings."""

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
    notes = repo.list_gold_notes(agent, user_id)
    return GoldResponse(
        agent_id=agent.id,
        user_id=user_id,
        content=format_gold_with_rules(notes),
        entries=[
            GoldNoteOut(
                id=n.id,
                text=n.text,
                run_id=n.run_id,
                created_at=n.created_at,
            )
            for n in notes
        ],
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
    notes = repo.list_gold_notes(agent, user_id)
    return GoldResponse(
        agent_id=agent.id,
        user_id=user_id,
        content=format_gold_with_rules(notes),
        entries=[
            GoldNoteOut(
                id=n.id,
                text=n.text,
                run_id=n.run_id,
                created_at=n.created_at,
            )
            for n in notes
        ],
    )


@router.delete("/agents/{agent_id}/gold", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gold(
    agent_id: str,
    user_id: str = Depends(get_user_id),
    repo: OfficeRepository = Depends(get_office_repo),
) -> None:
    """Clear gold(a,u) for the current user."""
    agent = repo.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent not found: {agent_id}")
    repo.clear_gold(agent, user_id)
