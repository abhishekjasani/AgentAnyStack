"""Local model catalog — list / pull (SSE) / verify / unload / delete via Ollama."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent_anystack.adapters.ollama_health import diagnose_gpu_health, verify_model_gpu
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
    return OllamaModelManager(
        settings.openai_compatible_base_url,
        timeout=settings.ollama_pull_timeout,
    )


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _is_pulled(catalog_id: str, installed_names: set[str]) -> bool:
    """Exact tag match only — llama3.2 must not match llama3.2:3b."""
    return catalog_id in installed_names or f"{catalog_id}:latest" in installed_names


def _http_status_for_models_error(exc: OllamaModelsError) -> int:
    if exc.code == "not_curated":
        return 400
    if exc.code == "unreachable":
        return 503
    return 502


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


@router.get("/models/health")
async def models_health(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    """On-demand GPU / Ollama ladder — Stacks UI only; not used by chat."""
    report = await diagnose_gpu_health(
        openai_compatible_base_url=settings.openai_compatible_base_url,
        ollama_container_name=settings.ollama_container_name,
    )
    return report.as_dict()


@router.post("/models/pull")
async def pull_model(
    body: ModelNameBody,
    request: Request,
    mgr: OllamaModelManager = Depends(get_model_manager),
) -> StreamingResponse:
    """SSE pull. Client disconnect / AbortController cancels the Ollama pull stream."""
    name = body.name.strip()

    async def event_stream() -> AsyncIterator[str]:
        yield _sse({"type": "meta", "name": name})
        stream = mgr.pull_stream(name)
        cancelled = False
        try:
            async for chunk in stream:
                if await request.is_disconnected():
                    cancelled = True
                    break
                yield _sse({"type": "progress", "name": name, **chunk})
            if cancelled:
                yield _sse(
                    {
                        "type": "cancelled",
                        "name": name,
                        "message": "Pull cancelled",
                    }
                )
            else:
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
        finally:
            await stream.aclose()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/models/verify")
async def verify_model(
    body: ModelNameBody,
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    """Warm-load model and report GPU/CPU — Stacks only; long-running SSE."""
    name = body.name.strip()

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for chunk in verify_model_gpu(
                openai_compatible_base_url=settings.openai_compatible_base_url,
                name=name,
            ):
                yield _sse(chunk)
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


@router.post("/models/unload")
async def unload_model(
    body: ModelNameBody,
    mgr: OllamaModelManager = Depends(get_model_manager),
) -> dict[str, Any]:
    """Unload model from Ollama RAM/VRAM (keep_alive: 0). Does not delete weights."""
    try:
        result = await mgr.unload(body.name.strip())
    except OllamaModelsError as exc:
        raise HTTPException(
            status_code=_http_status_for_models_error(exc),
            detail=str(exc),
        ) from exc
    return {"status": "unloaded", **result}


@router.post("/models/delete")
async def delete_model(
    body: ModelNameBody,
    mgr: OllamaModelManager = Depends(get_model_manager),
) -> dict[str, str]:
    try:
        await mgr.delete(body.name)
    except OllamaModelsError as exc:
        raise HTTPException(
            status_code=_http_status_for_models_error(exc),
            detail=str(exc),
        ) from exc
    return {"status": "deleted", "name": body.name.strip()}
