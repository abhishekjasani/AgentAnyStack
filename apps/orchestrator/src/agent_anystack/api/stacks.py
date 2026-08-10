"""Unified stack catalog — list stacks and selectable models per stack."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from agent_anystack.adapters.bedrock_store import BedrockProviderStore, bedrock_data_dir
from agent_anystack.adapters.ollama_models import OllamaModelManager
from agent_anystack.adapters.stack_models import KNOWN_STACKS, list_models_for_stack
from agent_anystack.api.deps import get_user_id
from agent_anystack.config import Settings, get_settings

router = APIRouter(tags=["stacks"])


def get_bedrock_store(settings: Settings = Depends(get_settings)) -> BedrockProviderStore:
    return BedrockProviderStore(bedrock_data_dir(settings.database_url))


def get_ollama_manager(settings: Settings = Depends(get_settings)) -> OllamaModelManager:
    return OllamaModelManager(
        settings.openai_compatible_base_url,
        timeout=settings.ollama_pull_timeout,
    )


@router.get("/stacks")
async def list_stacks(_user_id: str = Depends(get_user_id)) -> dict[str, Any]:
    """Known stacks and whether desk chat is wired."""
    return {"stacks": list(KNOWN_STACKS)}


@router.get("/stacks/{stack}/models")
async def stack_models(
    stack: str,
    ollama: OllamaModelManager = Depends(get_ollama_manager),
    bedrock: BedrockProviderStore = Depends(get_bedrock_store),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """Selectable models for Create/Configure — one shape for every stack."""
    sid = (stack or "").strip()
    if not sid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="stack required")
    result = await list_models_for_stack(
        sid,
        ollama=ollama,
        bedrock_store=bedrock,
    )
    return result.as_dict()
