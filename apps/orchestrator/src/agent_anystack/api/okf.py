"""Team OKF HTTP — list / create / archive (seed path until extract pipeline)."""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from agent_anystack.api.deps import get_user_id
from agent_anystack.config import Settings, get_settings
from agent_anystack.memory import (
    CreateOkfFactRequest,
    OkfFact,
    OkfStore,
    sqlite_path_from_database_url,
)

router = APIRouter(tags=["okf"])


def get_okf_store(settings: Settings = Depends(get_settings)) -> OkfStore:
    return OkfStore(sqlite_path_from_database_url(settings.database_url))


@router.get("/okf/facts", response_model=list[OkfFact])
async def list_facts(
    team: str = Query(..., pattern=r"^[a-z][a-z0-9_-]*$"),
    store: OkfStore = Depends(get_okf_store),
    _user_id: str = Depends(get_user_id),
) -> list[OkfFact]:
    return store.list_team_facts(team)


@router.post(
    "/okf/facts",
    response_model=OkfFact,
    status_code=status.HTTP_201_CREATED,
)
async def create_fact(
    body: CreateOkfFactRequest,
    user_id: str = Depends(get_user_id),
    store: OkfStore = Depends(get_okf_store),
) -> OkfFact:
    """Manual team fact until background extract exists — not a desk-LLM write."""
    fact = OkfFact(
        type=body.type,
        scope=f"team:{body.team}",
        projects=body.projects,
        body=body.body.strip(),
        tags=body.tags,
        domain=body.domain,
        created_by_user=user_id,
        pinned=body.pinned,
        sensitivity=body.sensitivity,
    )
    return store.upsert(fact)


@router.delete("/okf/facts/{fact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_fact(
    fact_id: str,
    store: OkfStore = Depends(get_okf_store),
    _user_id: str = Depends(get_user_id),
) -> None:
    if not store.archive(fact_id):
        raise HTTPException(status_code=404, detail=f"fact not found: {fact_id}")
