"""Liveness endpoint."""

from fastapi import APIRouter

from agent_anystack import __version__

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
