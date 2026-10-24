"""Org-wide capability catalog — read-only listing (per-desk view lives on /agents/{id}/capabilities)."""

from pathlib import Path
import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from agent_anystack.api.deps import get_user_id
from agent_anystack.config import Settings, get_settings
from agent_anystack.capabilities.catalog import CapabilityCatalogItem, CapabilityCatalogService
from agent_anystack.capabilities.mcp.client import discover_mcp_tools
from agent_anystack.database import sqlite_path_from_database_url
from agent_anystack.security.capability_oauth import CapabilityOAuthStore

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


@router.post(
    "/capabilities",
    response_model=CapabilityCatalogItem,
    status_code=status.HTTP_201_CREATED,
)
async def create_capability(
    body: CapabilityCatalogItem,
    settings: Settings = Depends(get_settings),
    _user_id: str = Depends(get_user_id),
) -> CapabilityCatalogItem:
    service = CapabilityCatalogService(Path(settings.office_repo_path))
    try:
        return service.save(body, create_only=True)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/capabilities/{capability_id}", response_model=CapabilityCatalogItem)
async def update_capability(
    capability_id: str,
    body: CapabilityCatalogItem,
    settings: Settings = Depends(get_settings),
    _user_id: str = Depends(get_user_id),
) -> CapabilityCatalogItem:
    if body.id != capability_id:
        raise HTTPException(status_code=400, detail="capability id is immutable")
    service = CapabilityCatalogService(Path(settings.office_repo_path))
    existing = service.get(capability_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"capability not found: {capability_id}")
    if existing.kind != body.kind:
        raise HTTPException(status_code=400, detail="capability kind is immutable")
    try:
        return service.save(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/capabilities/{capability_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_capability(
    capability_id: str,
    settings: Settings = Depends(get_settings),
    _user_id: str = Depends(get_user_id),
) -> None:
    service = CapabilityCatalogService(Path(settings.office_repo_path))
    item = service.get(capability_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"capability not found: {capability_id}")
    from agent_anystack.api.agents import get_office_repo

    repo = get_office_repo(settings)
    for agent in repo.list_agents():
        registrations = agent.capability_registrations
        for category in ("tools", "mcp", "skills", "apis"):
            if capability_id in getattr(registrations, category):
                raise HTTPException(
                    status_code=409,
                    detail=f"capability is still registered to desk: {agent.id}",
                )
    try:
        deleted = service.delete(capability_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"capability not found: {capability_id}")


@router.post("/capabilities/{capability_id}/discover")
async def discover_capability_tools(
    capability_id: str,
    settings: Settings = Depends(get_settings),
    user_id: str = Depends(get_user_id),
) -> dict:
    service = CapabilityCatalogService(Path(settings.office_repo_path))
    item = service.get(capability_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"capability not found: {capability_id}")
    if item.kind.value != "mcp":
        raise HTTPException(status_code=400, detail="tool discovery applies only to MCP capabilities")

    oauth_store = None
    if item.auth.get("type") == "oauth2_user":
        oauth_store = _oauth_store(settings)

    async def oauth_token(request_user: str, item_id: str) -> str | None:
        if oauth_store is None:
            return None
        return await oauth_store.get_access_token(
            request_user,
            item_id,
            secret_resolver=os.environ.get,
        )

    try:
        tools = await discover_mcp_tools(
            item,
            secret_resolver=os.environ.get,
            user_id=user_id,
            oauth_token_resolver=oauth_token,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"MCP discovery failed ({type(exc).__name__})",
        ) from exc
    return {
        "capability_id": item.id,
        "tools": [
            {
                "name": tool.name,
                "description": tool.description or tool.title,
                "parameters": tool.input_schema,
            }
            for tool in tools
        ],
    }


def _oauth_store(settings: Settings) -> CapabilityOAuthStore:
    try:
        return CapabilityOAuthStore(
            sqlite_path_from_database_url(settings.database_url),
            settings.capability_oauth_encryption_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _registered_oauth_capability(agent_id, capability_id, repo):
    from agent_anystack.capabilities.catalog import CapabilityKind

    agent = repo.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent not found: {agent_id}")
    if capability_id not in agent.capability_registrations.apis + agent.capability_registrations.mcp:
        raise HTTPException(status_code=403, detail="capability is not registered to this desk")
    capability = CapabilityCatalogService(repo.root).get(capability_id)
    if capability is None or capability.kind not in {CapabilityKind.api, CapabilityKind.mcp}:
        raise HTTPException(status_code=404, detail=f"OAuth capability not found: {capability_id}")
    if capability.auth.get("type") != "oauth2_user":
        raise HTTPException(status_code=400, detail="capability does not use per-user OAuth")
    return capability


@router.post("/agents/{agent_id}/capabilities/{capability_id}/oauth/start")
async def start_capability_oauth(
    agent_id: str,
    capability_id: str,
    settings: Settings = Depends(get_settings),
    user_id: str = Depends(get_user_id),
):
    from agent_anystack.api.agents import get_office_repo

    repo = get_office_repo(settings)
    capability = _registered_oauth_capability(agent_id, capability_id, repo)
    store = _oauth_store(settings)
    try:
        result = store.start_authorization(
            user_id=user_id,
            capability_id=capability.id,
            auth=capability.auth,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"authorization_url": result.authorization_url, "state": result.state}


@router.get("/agents/{agent_id}/capabilities/{capability_id}/oauth/status")
async def capability_oauth_status(
    agent_id: str,
    capability_id: str,
    settings: Settings = Depends(get_settings),
    user_id: str = Depends(get_user_id),
):
    from agent_anystack.api.agents import get_office_repo

    repo = get_office_repo(settings)
    capability = _registered_oauth_capability(agent_id, capability_id, repo)
    return _oauth_store(settings).status(user_id, capability.id)


@router.delete("/agents/{agent_id}/capabilities/{capability_id}/oauth")
async def disconnect_capability_oauth(
    agent_id: str,
    capability_id: str,
    settings: Settings = Depends(get_settings),
    user_id: str = Depends(get_user_id),
):
    from agent_anystack.api.agents import get_office_repo

    repo = get_office_repo(settings)
    capability = _registered_oauth_capability(agent_id, capability_id, repo)
    disconnected = _oauth_store(settings).disconnect(user_id, capability.id)
    return {"connected": False, "disconnected": disconnected}


@router.get("/capability-oauth/callback", response_class=HTMLResponse)
async def capability_oauth_callback(
    state: str,
    code: str | None = None,
    error: str | None = None,
    settings: Settings = Depends(get_settings),
):
    if error or not code:
        raise HTTPException(status_code=400, detail="OAuth authorization was not completed")
    store = _oauth_store(settings)
    try:
        await store.complete_authorization(
            state=state,
            code=code,
            secret_resolver=os.environ.get,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return "<main><h1>Authorization connected</h1><p>You can return to AgentAnyStack.</p></main>"
