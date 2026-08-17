"""Stacks connections — list / enable / test (thin Connect cards)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from agent_anystack.adapters.bedrock_store import BedrockProviderStore, bedrock_data_dir
from agent_anystack.adapters.connections import (
    ConnectionNotFound,
    ConnectionStore,
    connection_store_from_database_url,
)
from agent_anystack.adapters.ollama_models import OllamaModelManager
from agent_anystack.adapters.opencode import list_opencode_models
from agent_anystack.adapters.opencode.serve import find_opencode_bin
from agent_anystack.adapters.llm import StackError
from agent_anystack.api.deps import get_user_id
from agent_anystack.config import Settings, get_settings
from agent_anystack.office import OfficeRepository
from agent_anystack.api.agents import get_office_repo
from agent_anystack.runs.journal import RunJournal
from agent_anystack.runs.service import journal_path_from_database_url

router = APIRouter(tags=["stacks-connections"])


def get_connection_store(
    settings: Settings = Depends(get_settings),
) -> ConnectionStore:
    return connection_store_from_database_url(settings.database_url)


def get_journal(settings: Settings = Depends(get_settings)) -> RunJournal:
    return RunJournal(
        journal_path_from_database_url(settings.database_url, Path("./data"))
    )


def get_ollama(settings: Settings = Depends(get_settings)) -> OllamaModelManager:
    return OllamaModelManager(
        settings.openai_compatible_base_url,
        timeout=settings.ollama_pull_timeout,
    )


def get_bedrock_store(settings: Settings = Depends(get_settings)) -> BedrockProviderStore:
    return BedrockProviderStore(bedrock_data_dir(settings.database_url))


class EnableBody(BaseModel):
    enabled: bool


def _used_by(
    repo: OfficeRepository, connection_id: str, stack: str
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for a in repo.list_agents():
        cid = getattr(a, "connection_id", None)
        if cid == connection_id or (not cid and a.stack == stack):
            out.append({"id": a.id, "name": a.name, "team": a.team})
    return out


@router.get("/stacks/connections")
async def list_connections(
    store: ConnectionStore = Depends(get_connection_store),
    repo: OfficeRepository = Depends(get_office_repo),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """All stack connections grouped for Stacks UI (by kind)."""
    items = []
    for c in store.list():
        d = c.as_dict()
        d["used_by"] = _used_by(repo, c.id, c.stack())
        items.append(d)
    kind_order = ("inference", "agent_runtime", "external")
    grouped = {k: [] for k in kind_order}
    for d in items:
        grouped.setdefault(d["kind"], []).append(d)
    return {
        "connections": items,
        "by_kind": [
            {
                "kind": k,
                "label": (
                    "Inference"
                    if k == "inference"
                    else "Agent runtime"
                    if k == "agent_runtime"
                    else "External agent"
                ),
                "connections": grouped.get(k, []),
            }
            for k in kind_order
        ],
    }


@router.get("/stacks/connections/{connection_id}")
async def get_connection(
    connection_id: str,
    store: ConnectionStore = Depends(get_connection_store),
    repo: OfficeRepository = Depends(get_office_repo),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    try:
        c = store.get_required(connection_id)
    except ConnectionNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    d = c.as_dict()
    d["used_by"] = _used_by(repo, c.id, c.stack())
    return d


@router.patch("/stacks/connections/{connection_id}")
async def patch_connection(
    connection_id: str,
    body: EnableBody,
    store: ConnectionStore = Depends(get_connection_store),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """Enable or disable an entire connection (not serve start/stop).

    Disabling OpenCode also stops live ``opencode serve`` processes.
    """
    try:
        c = store.set_enabled(connection_id, body.enabled)
    except ConnectionNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if not body.enabled and c.product == "opencode":
        from agent_anystack.adapters.opencode.runtime import stop_all_opencode_serves

        await stop_all_opencode_serves(force=True)
    return c.as_dict()


class StopServeBody(BaseModel):
    cwd: str


@router.get("/stacks/connections/{connection_id}/runtimes")
async def connection_runtimes(
    connection_id: str,
    store: ConnectionStore = Depends(get_connection_store),
    journal: RunJournal = Depends(get_journal),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """Live OpenCode serves/sessions, or recent journal runs for inference stacks."""
    try:
        c = store.get_required(connection_id)
    except ConnectionNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if c.product == "opencode":
        from agent_anystack.adapters.opencode.runtime import (
            list_serves_snapshot,
            list_sessions,
        )

        return {
            "connection_id": c.id,
            "kind": "agent_runtime",
            "serves": list_serves_snapshot(),
            "sessions": [s.as_dict() for s in list_sessions()],
            "runs": [],
        }

    # Inference: journal runs only (no fake sessions)
    runs = [
        {
            "run_id": e.run_id,
            "agent_id": e.agent_id,
            "user_id": e.user_id,
            "status": e.status,
            "model": e.model,
            "started_at": e.started_at,
            "ended_at": e.ended_at,
            "error": e.error,
        }
        for e in journal.recent_for_stack(c.stack(), limit=20)
    ]
    return {
        "connection_id": c.id,
        "kind": "inference",
        "serves": [],
        "sessions": [],
        "runs": runs,
    }


@router.post("/stacks/connections/{connection_id}/serves/stop")
async def stop_connection_serve(
    connection_id: str,
    body: StopServeBody,
    store: ConnectionStore = Depends(get_connection_store),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    try:
        c = store.get_required(connection_id)
    except ConnectionNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if c.product != "opencode":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="serve stop only applies to opencode connections",
        )
    from agent_anystack.adapters.opencode.runtime import stop_serve_by_cwd

    try:
        await stop_serve_by_cwd(body.cwd, connection_id=c.id)
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"ok": True, "cwd": body.cwd}


@router.post("/stacks/connections/{connection_id}/sessions/{session_id}/kill")
async def kill_connection_session(
    connection_id: str,
    session_id: str,
    store: ConnectionStore = Depends(get_connection_store),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    try:
        c = store.get_required(connection_id)
    except ConnectionNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if c.product != "opencode":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="session kill only applies to opencode connections",
        )
    from agent_anystack.adapters.opencode.runtime import kill_session

    try:
        row = await kill_session(session_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"ok": True, "session": row.as_dict()}


class RegisterModelBody(BaseModel):
    inference_connection_id: str
    inference_model_id: str


@router.get("/stacks/connections/{connection_id}/inference-candidates")
async def inference_candidates(
    connection_id: str,
    store: ConnectionStore = Depends(get_connection_store),
    ollama: OllamaModelManager = Depends(get_ollama),
    bedrock: BedrockProviderStore = Depends(get_bedrock_store),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """Inference catalog rows that can be Test & registered onto OpenCode."""
    try:
        c = store.get_required(connection_id)
    except ConnectionNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if c.product != "opencode":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="inference candidates only apply to opencode connections",
        )
    from agent_anystack.adapters.opencode.providers import list_inference_candidates

    rows = await list_inference_candidates(store, bedrock=bedrock, ollama=ollama)
    registered = {m.inference_model_id for m in c.registered_models}
    for row in rows:
        row["registered"] = row["model_id"] in registered
    return {
        "connection_id": c.id,
        "candidates": rows,
        "registered_models": [m.as_dict() for m in c.registered_models],
    }


@router.post("/stacks/connections/{connection_id}/models/register")
async def register_opencode_model(
    connection_id: str,
    body: RegisterModelBody,
    store: ConnectionStore = Depends(get_connection_store),
    bedrock: BedrockProviderStore = Depends(get_bedrock_store),
    settings: Settings = Depends(get_settings),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """Inject Inference into OpenCode serve and persist the working provider/model pair."""
    from agent_anystack.adapters.opencode.register import RegisterError, register_inference_model

    try:
        return await register_inference_model(
            store=store,
            connection_id=connection_id,
            inference_connection_id=body.inference_connection_id,
            inference_model_id=body.inference_model_id,
            settings=settings,
            bedrock=bedrock,
        )
    except ConnectionNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RegisterError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/stacks/connections/{connection_id}/models/{model_ref:path}")
async def delete_opencode_model(
    connection_id: str,
    model_ref: str,
    store: ConnectionStore = Depends(get_connection_store),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    try:
        c = store.get_required(connection_id)
    except ConnectionNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if c.product != "opencode":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="registered models only apply to opencode connections",
        )
    try:
        updated = store.remove_registered_model(c.id, model_ref)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"ok": True, "connection": updated.as_dict()}


@router.post("/stacks/connections/{connection_id}/test")
async def test_connection(
    connection_id: str,
    store: ConnectionStore = Depends(get_connection_store),
    ollama: OllamaModelManager = Depends(get_ollama),
    bedrock: BedrockProviderStore = Depends(get_bedrock_store),
    settings: Settings = Depends(get_settings),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """Reachability / credentials smoke test for a connection."""
    try:
        c = store.get_required(connection_id)
    except ConnectionNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    ok = False
    error: str | None = None
    meta: dict[str, Any] = {}

    try:
        if c.product == "opencode":
            if settings.opencode_bin.strip():
                import os

                os.environ["OPENCODE_BIN"] = settings.opencode_bin.strip()
            bin_path = find_opencode_bin()
            models = await list_opencode_models()
            meta = {
                "bin": bin_path,
                "model_count": len(models),
            }
            ok = True
        elif c.product == "ollama":
            reachable = await ollama.ping()
            if not reachable:
                error = "Ollama not reachable"
            else:
                rows = await ollama.list_installed()
                meta = {"model_count": len(rows)}
                ok = True
        elif c.product == "bedrock":
            from agent_anystack.adapters.bedrock import BedrockAdapter
            from agent_anystack.adapters.bedrock_store import resolve_creds

            creds = resolve_creds(
                bedrock,
                env_access_key_id=settings.aws_access_key_id,
                env_secret_access_key=settings.aws_secret_access_key,
                env_session_token=settings.aws_session_token,
                env_region=settings.aws_region,
            )
            adapter = BedrockAdapter(
                access_key_id=creds.access_key_id,
                secret_access_key=creds.secret_access_key,
                session_token=creds.session_token,
                region=creds.region,
            )
            if not adapter.configured():
                error = "Bedrock credentials not configured"
            else:
                ident = await adapter.test_credentials()
                meta = {
                    "account": ident.get("account") or ident.get("Account"),
                    "arn": ident.get("arn") or ident.get("Arn"),
                }
                ok = True
        else:
            error = f"no test implemented for product '{c.product}'"
    except StackError as exc:
        error = str(exc)
        ok = False
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        ok = False

    updated = store.set_test_result(connection_id, ok=ok, error=error, meta=meta)
    return {
        "ok": ok,
        "error": error,
        "connection": updated.as_dict(),
    }
