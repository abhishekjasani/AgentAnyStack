"""Propose / list / decide — Accept → journal."""

from __future__ import annotations

from agent_anystack.hitl.card import (
    ApprovalCard,
    ApprovalDecision,
    ApprovalStatus,
    new_approval_id,
)
from agent_anystack.hitl.policy import can_decide, parse_org_admins
from agent_anystack.hitl.store import ApprovalStore
from agent_anystack.runs.journal import JournalEntry, RunJournal, new_run_id, utc_now


class ApprovalForbiddenError(PermissionError):
    """Actor may not decide this card under current approver_mode."""


class ApprovalNotPendingError(ValueError):
    """Card is missing or already decided."""


class ApprovalService:
    def __init__(
        self,
        store: ApprovalStore,
        journal: RunJournal,
        *,
        approver_mode: str = "permissive",
        org_admins: str = "",
    ) -> None:
        self.store = store
        self.journal = journal
        self.approver_mode = approver_mode
        self.org_admins = parse_org_admins(org_admins)

    def propose(
        self,
        *,
        requester: str,
        agent_id: str,
        team: str,
        summary: str,
        action_type: str = "demo",
        run_id: str | None = None,
        project_id: str | None = None,
    ) -> ApprovalCard:
        card = ApprovalCard(
            id=new_approval_id(),
            tag="action",
            status=ApprovalStatus.pending_human,
            run_id=run_id or new_run_id(),
            agent_id=agent_id,
            user_id=requester,
            team=team,
            project_id=project_id,
            summary=summary.strip(),
            action_type=action_type.strip() or "demo",
            created_at=utc_now(),
        )
        return self.store.upsert(card)

    def list_cards(
        self,
        *,
        status: ApprovalStatus | None = None,
        limit: int = 50,
    ) -> list[ApprovalCard]:
        return self.store.list_cards(status=status, limit=limit)

    def decide(
        self,
        *,
        approval_id: str,
        actor: str,
        decision: ApprovalDecision,
        note: str | None = None,
    ) -> ApprovalCard:
        card = self.store.get(approval_id)
        if card is None or card.status != ApprovalStatus.pending_human:
            raise ApprovalNotPendingError(f"approval not pending: {approval_id}")
        if not can_decide(
            actor=actor,
            requester=card.user_id,
            org_admins=self.org_admins,
            approver_mode=self.approver_mode,
        ):
            raise ApprovalForbiddenError(
                f"actor {actor!r} may not decide under {self.approver_mode}"
            )

        now = utc_now()
        card.decision = decision
        card.decided_by = actor
        card.decided_at = now
        card.note = (note or "").strip() or None
        card.status = (
            ApprovalStatus.accepted
            if decision == ApprovalDecision.accept
            else ApprovalStatus.rejected
        )
        self.store.upsert(card)
        self.journal.append(
            JournalEntry(
                run_id=card.run_id,
                agent_id=card.agent_id,
                user_id=card.user_id,
                team=card.team,
                project_id=card.project_id,
                channel="office_ui",
                stack="hitl",
                model="",
                effective_autonomy=0,
                status=f"approval_{decision.value}",
                started_at=card.created_at,
                ended_at=now,
                error=card.note,
                approval_id=card.id,
                decision=decision.value,
                decided_by=actor,
            )
        )
        return card
