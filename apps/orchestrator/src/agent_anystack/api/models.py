"""Local model catalog — list / pull (SSE) / delete via Ollama native API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent_anystack.adapters.ollama_models import (
    CURATED_CATALOG,
    OllamaModelManager,
    OllamaModelsError,
)
from agent_anystack.config import Settings, get_settings

router = APIRouter(tags=["models"])


class ModelNameBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)


def get_model_manager(settings: Settings = Depends(get_settings)) -> OllamaModelManager:
    return OllamaModelManager(settings.openai_compatible_base_url)


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _is_pulled(catalog_id: str, installed_names: set[str]) -> bool:
    if catalog_id in installed_names or f"{catalog_id}:latest" in installed_names:
        return True
    for n in installed_names:
        if n == catalog_id or n.startswith(catalog_id + ":"):
            return True
        if ":" not in catalog_id and n.split(":")[0] == catalog_id:
            return True
    return False


@router.get("/models")
async def list_models(mgr: OllamaModelManager = Depends(get_model_manager)) -> dict[str, Any]:
    reachable = await mgr.ping()
    installed: list[dict[str, Any]] = []
    error: str | None = None
    if reachable:
        try:
            rows = await mgr.list_installed()
            installed = [
                {"name": m.name, "size": m.size, "digest": m.digest} for m in rows
            ]
        except OllamaModelsError as exc:
            error = str(exc)
            reachable = False
    installed_names = {m["name"] for m in installed}
    catalog = [
        {**entry, "pulled": _is_pulled(entry["id"], installed_names)}
        for entry in CURATED_CATALOG
    ]
    return {
        "engine": {
            "kind": "ollama",
            "reachable": reachable,
            "native_base": mgr.native_base,
            "error": error,
        },
        "catalog": catalog,
        "installed": installed,
    }


@router.post("/models/pull")
async def pull_model(
    body: ModelNameBody,
    mgr: OllamaModelManager = Depends(get_model_manager),
) -> StreamingResponse:
    name = body.name.strip()

    async def event_stream() -> AsyncIterator[str]:
        yield _sse({"type": "meta", "name": name})
        try:
            async for chunk in mgr.pull_stream(name):
                yield _sse({"type": "progress", "name": name, **chunk})
            yield _sse({"type": "done", "name": name})
        except OllamaModelsError as exc:
            yield _sse(
                {
                    "type": "error",
                    "name": name,
                    "code": exc.code,
                    "message": str(exc),
                }
            )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/models/delete")
async def delete_model(
    body: ModelNameBody,
    mgr: OllamaModelManager = Depends(get_model_manager),
) -> dict[str, str]:
    try:
        await mgr.delete(body.name)
    except OllamaModelsError as exc:
        status = 400 if exc.code == "not_curated" else 502
        if exc.code == "unreachable":
            status = 503
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {"status": "deleted", "name": body.name.strip()}
