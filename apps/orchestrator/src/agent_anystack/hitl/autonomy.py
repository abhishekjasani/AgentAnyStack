"""Effective autonomy (§4.1) + one action gate (P14)."""

from __future__ import annotations

from enum import Enum

from agent_anystack.domain.agent import AgentConfig
from agent_anystack.domain.org import OrgConfig

# The one gated action type for v0 — bands on effective autonomy.
GATED_ACTION_TYPE = "external_send"


class GateOutcome(str, Enum):
    allow = "allow"
    hitl = "hitl"
    deny = "deny"


def effective_max(org: OrgConfig, agent: AgentConfig) -> int:
    agent_max = agent.autonomy.max if agent.autonomy.max is not None else 100
    return min(org.max_autonomy, agent_max)


def compute_effective(
    org: OrgConfig,
    agent: AgentConfig,
    *,
    user_override: int | None = None,
) -> int:
    """
    effective = clamp(user.override ?? agent.default ?? org.default, 0, effective_max)

    User may only tighten: override above effective_max is clamped down (never self-promote).
    """
    em = effective_max(org, agent)
    if user_override is not None:
        raw = user_override
    elif agent.autonomy.default is not None:
        raw = agent.autonomy.default
    else:
        raw = org.autonomy.default
    return max(0, min(int(raw), em))


def gate_action(action_type: str, effective: int) -> GateOutcome:
    """
    One gate: external_send uses autonomy bands.
    Other action types → always HITL (board path without auto).

    external_send bands (on effective):
      ≤20  → deny
      21–79 → hitl (pending card)
      ≥80  → allow (auto-accept + journal)
    """
    t = (action_type or "").strip().lower()
    if t != GATED_ACTION_TYPE:
        return GateOutcome.hitl
    if effective <= 20:
        return GateOutcome.deny
    if effective >= 80:
        return GateOutcome.allow
    return GateOutcome.hitl
