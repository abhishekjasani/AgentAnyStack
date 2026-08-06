"""Team OKF HTTP — list / create / archive / export leave-path."""

import re
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from agent_anystack.api.deps import get_user_id
from agent_anystack.config import Settings, get_settings
from agent_anystack.memory import (
    CreateOkfFactRequest,
    OkfFact,
    OkfStore,
    export_okf_to_memory,
    sqlite_path_from_database_url,
)

router = APIRouter(tags=["okf"])

_TEAM_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


def get_okf_store(settings: Settings = Depends(get_settings)) -> OkfStore:
    return OkfStore(sqlite_path_from_database_url(settings.database_url))


class ExportOkfRequest(BaseModel):
    team: str | None = Field(
        default=None,
        description="Export one team; omit to export all scopes in DB",
    )
    include_archived: bool = True


class ExportOkfResponse(BaseModel):
    root: str
    teams: list[str]
    fact_count: int
    archived_count: int
    exported_at: str


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
    """Manual team fact — not a desk-LLM write."""
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


@router.post("/okf/export", response_model=ExportOkfResponse)
async def export_okf(
    body: ExportOkfRequest = Body(default_factory=ExportOkfRequest),
    store: OkfStore = Depends(get_okf_store),
    settings: Settings = Depends(get_settings),
    _user_id: str = Depends(get_user_id),
) -> ExportOkfResponse:
    """Write SQLite OKF → office/memory/ (portable leave-path; not hot pack)."""
    if body.team is not None and not _TEAM_RE.fullmatch(body.team):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="team must match ^[a-z][a-z0-9_-]*$",
        )
    result = export_okf_to_memory(
        store,
        Path(settings.office_repo_path),
        team=body.team,
        include_archived=body.include_archived,
    )
    return ExportOkfResponse(
        root=result.root,
        teams=result.teams,
        fact_count=result.fact_count,
        archived_count=result.archived_count,
        exported_at=result.exported_at,
    )
