"""HITL approval cards — action board + autonomy gate."""

from agent_anystack.hitl.autonomy import (
    GATED_ACTION_TYPE,
    GateOutcome,
    compute_effective,
    gate_action,
)
from agent_anystack.hitl.card import ApprovalCard, ApprovalDecision, ApprovalStatus
from agent_anystack.hitl.service import ApprovalService, ProposeResult
from agent_anystack.hitl.store import ApprovalStore

__all__ = [
    "ApprovalCard",
    "ApprovalDecision",
    "ApprovalService",
    "ApprovalStatus",
    "ApprovalStore",
    "GATED_ACTION_TYPE",
    "GateOutcome",
    "ProposeResult",
    "compute_effective",
    "gate_action",
]
