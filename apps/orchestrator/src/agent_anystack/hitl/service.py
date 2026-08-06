"""Propose / list / decide — gate on propose (P14); Accept → journal."""

from __future__ import annotations

from dataclasses import dataclass

from agent_anystack.hitl.autonomy import (
    GATED_ACTION_TYPE,
    GateOutcome,
    compute_effective,
    gate_action,
)
from agent_anystack.hitl.card import (
    ApprovalCard,
    ApprovalDecision,
    ApprovalStatus,
    new_approval_id,
)
from agent_anystack.hitl.policy import can_decide, parse_org_admins
from agent_anystack.hitl.store import ApprovalStore
from agent_anystack.office import OfficeRepository
from agent_anystack.runs.journal import JournalEntry, RunJournal, new_run_id, utc_now


class ApprovalForbiddenError(PermissionError):
    """Actor may not decide this card under current approver_mode."""


class ApprovalNotPendingError(ValueError):
    """Card is missing or already decided."""


class ApprovalGateDeniedError(PermissionError):
    """Effective autonomy gate denied the propose."""

    def __init__(self, message: str, *, effective: int, gate: GateOutcome) -> None:
        super().__init__(message)
        self.effective = effective
        self.gate = gate


class AgentNotFoundError(LookupError):
    """Propose requires a real desk for autonomy lookup."""


@dataclass
class ProposeResult:
    card: ApprovalCard
    gate: GateOutcome
    effective_autonomy: int


class ApprovalService:
    def __init__(
        self,
        store: ApprovalStore,
        journal: RunJournal,
        repo: OfficeRepository,
        *,
        approver_mode: str = "permissive",
        org_admins: str = "",
    ) -> None:
        self.store = store
        self.journal = journal
        self.repo = repo
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
        user_override: int | None = None,
    ) -> ProposeResult:
        agent = self.repo.get_agent(agent_id)
        if agent is None:
            raise AgentNotFoundError(f"agent not found: {agent_id}")
        org = self.repo.load_org()
        effective = compute_effective(org, agent, user_override=user_override)
        outcome = gate_action(action_type, effective)
        now = utc_now()
        rid = run_id or new_run_id()

        if outcome == GateOutcome.deny:
            card = ApprovalCard(
                id=new_approval_id(),
                tag="action",
                status=ApprovalStatus.denied,
                run_id=rid,
                agent_id=agent_id,
                user_id=requester,
                team=team or agent.team,
                project_id=project_id,
                summary=summary.strip(),
                action_type=action_type.strip() or "demo",
                created_at=now,
                decided_at=now,
                decided_by="gate",
                note=f"denied by autonomy gate (effective={effective})",
                effective_autonomy=effective,
                gate=outcome.value,
            )
            self.store.upsert(card)
            self._journal_gate(card, status="approval_deny", actor="gate")
            raise ApprovalGateDeniedError(
                f"{GATED_ACTION_TYPE} denied at effective autonomy {effective}/100 "
                f"(need >20 for HITL, ≥80 for auto-allow)",
                effective=effective,
                gate=outcome,
            )

        if outcome == GateOutcome.allow:
            card = ApprovalCard(
                id=new_approval_id(),
                tag="action",
                status=ApprovalStatus.accepted,
                run_id=rid,
                agent_id=agent_id,
                user_id=requester,
                team=team or agent.team,
                project_id=project_id,
                summary=summary.strip(),
                action_type=action_type.strip() or "demo",
                created_at=now,
                decided_at=now,
                decided_by="gate",
                decision=ApprovalDecision.accept,
                note=f"auto-allow (effective={effective})",
                effective_autonomy=effective,
                gate=outcome.value,
            )
            self.store.upsert(card)
            self._journal_gate(card, status="approval_accept", actor="gate")
            return ProposeResult(card=card, gate=outcome, effective_autonomy=effective)

        # hitl — pending human
        card = ApprovalCard(
            id=new_approval_id(),
            tag="action",
            status=ApprovalStatus.pending_human,
            run_id=rid,
            agent_id=agent_id,
            user_id=requester,
            team=team or agent.team,
            project_id=project_id,
            summary=summary.strip(),
            action_type=action_type.strip() or "demo",
            created_at=now,
            effective_autonomy=effective,
            gate=outcome.value,
        )
        self.store.upsert(card)
        return ProposeResult(card=card, gate=outcome, effective_autonomy=effective)

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
        self._journal_gate(
            card,
            status=f"approval_{decision.value}",
            actor=actor,
        )
        return card

    def _journal_gate(
        self,
        card: ApprovalCard,
        *,
        status: str,
        actor: str,
    ) -> None:
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
                effective_autonomy=card.effective_autonomy or 0,
                status=status,
                started_at=card.created_at,
                ended_at=card.decided_at or utc_now(),
                error=card.note,
                approval_id=card.id,
                decision=card.decision.value if card.decision else (
                    "deny" if status == "approval_deny" else None
                ),
                decided_by=actor,
            )
        )
