"""Who may Accept / Reject — permissive vs strict."""

from __future__ import annotations


def parse_org_admins(raw: str) -> frozenset[str]:
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def can_decide(
    *,
    actor: str,
    requester: str,
    org_admins: frozenset[str],
    approver_mode: str,
) -> bool:
    """
    permissive: requester ∪ org admin (MCP/cred owner later).
    strict: org admin only (requester cannot Accept).
    """
    mode = (approver_mode or "permissive").strip().lower()
    if mode == "strict":
        return actor in org_admins
    # permissive (default)
    return actor == requester or actor in org_admins
