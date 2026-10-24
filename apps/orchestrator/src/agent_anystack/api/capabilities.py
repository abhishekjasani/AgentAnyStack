"""Org-wide capability catalog — read-only listing (per-desk view lives on /agents/{id}/capabilities)."""

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agent_anystack.api.deps import get_user_id
from agent_anystack.config import Settings, get_settings
from agent_anystack.capabilities.catalog import CapabilityCatalogItem, CapabilityCatalogService

router = APIRouter(tags=["capabilities"])


class CapabilityCatalogResponse(BaseModel):
    items: list[CapabilityCatalogItem] = Field(default_factory=list)


@router.get("/capabilities", response_model=CapabilityCatalogResponse)
async def list_capabilities(
    settings: Settings = Depends(get_settings),
    _user_id: str = Depends(get_user_id),
) -> CapabilityCatalogResponse:
    service = CapabilityCatalogService(Path(settings.office_repo_path))
    return CapabilityCatalogResponse(items=service.list())
