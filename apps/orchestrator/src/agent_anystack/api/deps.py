"""Request identity stub — no SSO yet; header proves users distinct when multi-user."""

import re
from typing import Annotated

from fastapi import Header, HTTPException

_USER_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
# Community default: one admin. Multi-user via X-User-Id still works; edition switch later.
DEFAULT_USER_ID = "admin"


def get_user_id(
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
) -> str:
    """Read X-User-Id; default admin (community single seat)."""
    raw = (x_user_id or "").strip() or DEFAULT_USER_ID
    if not _USER_ID_RE.match(raw):
        raise HTTPException(
            status_code=400,
            detail="X-User-Id must match ^[a-z][a-z0-9_-]{0,63}$",
        )
    return raw
