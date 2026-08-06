"""Approval board HTTP — propose / list / decide (one action-card path)."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from agent_anystack.api.deps import get_user_id
from agent_anystack.config import Settings, get_settings
from agent_anystack.hitl import (
    ApprovalCard,
    ApprovalDecision,
    ApprovalService,
    ApprovalStatus,
    ApprovalStore,
)
from agent_anystack.hitl.service import ApprovalForbiddenError, ApprovalNotPendingError
from agent_anystack.memory import sqlite_path_from_database_url
from agent_anystack.runs.journal import RunJournal
from agent_anystack.runs.service import journal_path_from_database_url

router = APIRouter(tags=["approvals"])


class ProposeApprovalRequest(BaseModel):
    agent_id: str = Field(..., pattern=r"^[a-z][a-z0-9_-]*$", max_length=64)
    summary: str = Field(..., min_length=1, max_length=4000)
    team: str = Field(default="eng", pattern=r"^[a-z][a-z0-9_-]*$")
    action_type: str = Field(default="demo", max_length=64)
    run_id: str | None = Field(default=None, max_length=64)
    project_id: str | None = Field(default=None, max_length=128)


class DecideApprovalRequest(BaseModel):
    decision: ApprovalDecision
    note: str | None = Field(default=None, max_length=2000)


class ApprovalCardOut(BaseModel):
    id: str
    tag: str
    status: ApprovalStatus
    run_id: str
    agent_id: str
    user_id: str
    team: str
    project_id: str | None
    summary: str
    action_type: str
    created_at: str
    decided_at: str | None
    decided_by: str | None
    decision: ApprovalDecision | None
    note: str | None

    @classmethod
    def from_card(cls, card: ApprovalCard) -> "ApprovalCardOut":
        return cls(
            id=card.id,
            tag=card.tag,
            status=card.status,
            run_id=card.run_id,
            agent_id=card.agent_id,
            user_id=card.user_id,
            team=card.team,
            project_id=card.project_id,
            summary=card.summary,
            action_type=card.action_type,
            created_at=card.created_at,
            decided_at=card.decided_at,
            decided_by=card.decided_by,
            decision=card.decision,
            note=card.note,
        )


def get_approval_service(
    settings: Settings = Depends(get_settings),
) -> ApprovalService:
    db = sqlite_path_from_database_url(settings.database_url)
    journal = RunJournal(
        journal_path_from_database_url(settings.database_url, Path("./data"))
    )
    return ApprovalService(
        ApprovalStore(db),
        journal,
        approver_mode=settings.approver_mode,
        org_admins=settings.org_admins,
    )


@router.get("/approvals", response_model=list[ApprovalCardOut])
async def list_approvals(
    status_filter: ApprovalStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    svc: ApprovalService = Depends(get_approval_service),
    _user_id: str = Depends(get_user_id),
) -> list[ApprovalCardOut]:
    return [
        ApprovalCardOut.from_card(c)
        for c in svc.list_cards(status=status_filter, limit=limit)
    ]


@router.post(
    "/approvals",
    response_model=ApprovalCardOut,
    status_code=status.HTTP_201_CREATED,
)
async def propose_approval(
    body: ProposeApprovalRequest,
    user_id: str = Depends(get_user_id),
    svc: ApprovalService = Depends(get_approval_service),
) -> ApprovalCardOut:
    """Create a pending action card (demo / later agent gate)."""
    card = svc.propose(
        requester=user_id,
        agent_id=body.agent_id,
        team=body.team,
        summary=body.summary,
        action_type=body.action_type,
        run_id=body.run_id,
        project_id=body.project_id,
    )
    return ApprovalCardOut.from_card(card)


@router.post("/approvals/{approval_id}/decide", response_model=ApprovalCardOut)
async def decide_approval(
    approval_id: str,
    body: DecideApprovalRequest,
    user_id: str = Depends(get_user_id),
    svc: ApprovalService = Depends(get_approval_service),
) -> ApprovalCardOut:
    """Accept or reject — permissive: requester ∪ ORG_ADMINS. Writes journal."""
    try:
        card = svc.decide(
            approval_id=approval_id,
            actor=user_id,
            decision=body.decision,
            note=body.note,
        )
    except ApprovalNotPendingError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ApprovalForbiddenError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    return ApprovalCardOut.from_card(card)
