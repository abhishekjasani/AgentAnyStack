"""Request identity stub — no SSO yet; header proves two users distinct."""

import re
from typing import Annotated

from fastapi import Header, HTTPException

_USER_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
DEFAULT_USER_ID = "anonymous"


def get_user_id(
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
) -> str:
    """Read X-User-Id; default anonymous. Same desk, different notepads later."""
    raw = (x_user_id or "").strip() or DEFAULT_USER_ID
    if not _USER_ID_RE.match(raw):
        raise HTTPException(
            status_code=400,
            detail="X-User-Id must match ^[a-z][a-z0-9_-]{0,63}$",
        )
    return raw
