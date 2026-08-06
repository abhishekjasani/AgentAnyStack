"""Approval card model — action tag; gate fields from P14."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import uuid4


class ApprovalStatus(str, Enum):
    pending_human = "pending_human"
    accepted = "accepted"
    rejected = "rejected"
    denied = "denied"  # gate denied before human (no pending)


class ApprovalDecision(str, Enum):
    accept = "accept"
    reject = "reject"


def new_approval_id() -> str:
    return f"appr-{uuid4().hex[:16]}"


@dataclass
class ApprovalCard:
    """One durable action card on the office approval board."""

    id: str
    tag: str  # "action" in v0
    status: ApprovalStatus
    run_id: str
    agent_id: str
    user_id: str  # requester
    team: str
    summary: str
    action_type: str
    created_at: str
    project_id: str | None = None
    decided_at: str | None = None
    decided_by: str | None = None
    decision: ApprovalDecision | None = None
    note: str | None = None
    effective_autonomy: int | None = None
    gate: str | None = None  # allow | hitl | deny
