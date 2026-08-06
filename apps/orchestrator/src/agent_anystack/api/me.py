"""Current user stub (X-User-Id)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from agent_anystack.api.deps import get_user_id

router = APIRouter(tags=["user"])


class MeResponse(BaseModel):
    user_id: str


@router.get("/me", response_model=MeResponse)
async def me(user_id: str = Depends(get_user_id)) -> MeResponse:
    """Who this request is — community default admin; multi-user via header."""
    return MeResponse(user_id=user_id)
