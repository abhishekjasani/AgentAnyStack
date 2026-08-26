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
    StackConnection,
    VerifiedInferenceModel,
    connection_store_from_database_url,
    utc_now_iso,
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
                    else "Coding harness"
                    if k == "agent_runtime"
                    else "External agents"
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


class CreateConnectionBody(BaseModel):
    id: str
    label: str | None = None
    kind: str = "inference"
    product: str = "openai-compatible"
    preset: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None
    session_token: str | None = None
    auth_mode: str | None = None
    region: str | None = None
    model_name: str | None = None
    enabled: bool = True


class DiscoverModelsBody(BaseModel):
    product: str = "openai-compatible"
    base_url: str | None = None
    api_key: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None
    session_token: str | None = None
    auth_mode: str | None = None
    region: str | None = None
    connection_id: str | None = None


class VerifyModelBody(BaseModel):
    model_id: str
    display_name: str | None = None


@router.post("/stacks/connections/discover-models")
async def discover_provider_models(
    body: DiscoverModelsBody,
    store: ConnectionStore = Depends(get_connection_store),
    bedrock_store: BedrockProviderStore = Depends(get_bedrock_store),
    settings: Settings = Depends(get_settings),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """Discover available model IDs from provider endpoint prior to saving connection."""
    existing = store.get(body.connection_id) if body.connection_id else None

    if body.product == "bedrock":
        from agent_anystack.adapters.bedrock import BedrockAdapter
        from agent_anystack.adapters.bedrock_store import resolve_creds

        ak = body.access_key_id or (existing.meta.get("access_key_id") if existing else None)
        sk = body.secret_access_key or (existing.meta.get("secret_access_key") if existing else None)
        st = body.session_token or (existing.meta.get("session_token") if existing else None)
        apk = body.api_key or (existing.meta.get("api_key") if existing else None)
        reg = body.region or (existing.meta.get("region") if existing else "us-east-1")
        am = body.auth_mode or ("api_key" if apk else "iam")

        creds = resolve_creds(
            bedrock_store,
            env_access_key_id=settings.aws_access_key_id,
            env_secret_access_key=settings.aws_secret_access_key,
            env_session_token=settings.aws_session_token,
            env_region=settings.aws_region,
            env_api_key=settings.aws_bearer_token_bedrock,
        )
        adapter = BedrockAdapter(
            access_key_id=ak or creds.access_key_id,
            secret_access_key=sk or creds.secret_access_key,
            session_token=st or creds.session_token,
            api_key=apk or creds.api_key,
            auth_mode=am,
            region=reg,
        )
        models = await adapter.list_models()
        return {"ok": True, "models": models}
    else:
        from agent_anystack.adapters.llm import OpenAICompatibleAdapter

        base_url = body.base_url or (existing.meta.get("base_url") if existing else None) or settings.openai_compatible_base_url or "http://127.0.0.1:11434/v1"
        api_key = body.api_key or (existing.meta.get("api_key") if existing else None)

        adapter = OpenAICompatibleAdapter(base_url=base_url, api_key=api_key)
        try:
            models = await adapter.list_models()
            return {"ok": True, "models": models}
        except Exception as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/stacks/connections")
async def create_or_update_connection(
    body: CreateConnectionBody,
    store: ConnectionStore = Depends(get_connection_store),
    bedrock_store: BedrockProviderStore = Depends(get_bedrock_store),
    settings: Settings = Depends(get_settings),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """Add or update a connection card. Perform connection test BEFORE saving credentials."""
    cid = body.id.strip().lower()
    if not cid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="connection id is required")

    existing = store.get(cid)
    meta = existing.meta.copy() if existing else {}

    if body.preset:
        meta["preset"] = body.preset
    if body.base_url is not None:
        meta["base_url"] = body.base_url.strip()
    if body.region is not None:
        meta["region"] = body.region.strip()
    if body.api_key is not None and body.api_key.strip():
        meta["api_key"] = body.api_key.strip()
        meta["has_api_key"] = True
    if body.model_name is not None and body.model_name.strip():
        meta["model_name"] = body.model_name.strip()

    conn = StackConnection(
        id=cid,
        kind=body.kind if body.kind in ("inference", "agent_runtime", "external") else "inference",  # type: ignore
        product=body.product or "openai-compatible",
        label=body.label or cid,
        enabled=body.enabled,
        status=existing.status if existing else "unknown",
        last_error=existing.last_error if existing else None,
        tested_at=existing.tested_at if existing else None,
        meta=meta,
        aliases=existing.aliases if existing else [],
        registered_models=existing.registered_models if existing else [],
        verified_models=existing.verified_models if existing else [],
    )

    if conn.kind == "inference":
        model_id = (body.model_name or "").strip() or (meta.get("model_name") or "").strip()

        if conn.product == "bedrock":
            from agent_anystack.adapters.bedrock import BedrockAdapter
            from agent_anystack.adapters.bedrock_store import resolve_creds, BedrockModelEntry

            ak = body.access_key_id if body.access_key_id and body.access_key_id.strip() else None
            sk = body.secret_access_key if body.secret_access_key and body.secret_access_key.strip() else None
            st = body.session_token if body.session_token and body.session_token.strip() else None
            apk = body.api_key if body.api_key and body.api_key.strip() else None
            reg = body.region or "us-east-1"
            am = body.auth_mode or ("api_key" if apk else "iam")

            creds = resolve_creds(
                bedrock_store,
                env_access_key_id=settings.aws_access_key_id,
                env_secret_access_key=settings.aws_secret_access_key,
                env_session_token=settings.aws_session_token,
                env_region=settings.aws_region,
                env_api_key=settings.aws_bearer_token_bedrock,
            )
            adapter = BedrockAdapter(
                access_key_id=ak or creds.access_key_id,
                secret_access_key=sk or creds.secret_access_key,
                session_token=st or creds.session_token,
                api_key=apk or creds.api_key,
                auth_mode=am,
                region=reg,
            )
            if not adapter.configured():
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail="Bedrock connection failed: Credentials not configured.",
                )

            try:
                await adapter.test_credentials()
            except Exception as exc:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail=f"Bedrock credentials check failed: {exc}. Credentials were NOT saved.",
                ) from exc

            if model_id:
                try:
                    await adapter.complete_chat(
                        model=model_id,
                        messages=[{"role": "user", "content": "Reply OK"}],
                        max_tokens=8,
                    )
                except Exception as exc:
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST,
                        detail=f"Bedrock model '{model_id}' call failed: {exc}. Credentials were NOT saved.",
                    ) from exc

            bedrock_store.put_creds(
                access_key_id=ak,
                secret_access_key=sk,
                session_token=st,
                api_key=apk,
                auth_mode=am,
                region=reg,
            )
            if model_id:
                bedrock_store.upsert_model(
                    BedrockModelEntry(
                        id=model_id,
                        display_name=model_id,
                        verified_at=utc_now_iso(),
                        region=reg,
                    )
                )
                entry = VerifiedInferenceModel(
                    model_id=model_id,
                    display_name=model_id,
                    verified_at=utc_now_iso(),
                    region=reg,
                )
                rest = [m for m in conn.verified_models if m.model_id != model_id]
                rest.append(entry)
                rest.sort(key=lambda m: m.model_id)
                conn.verified_models = rest

            conn.status = "ok"
            conn.tested_at = utc_now_iso()
            conn.last_error = None

        else:
            from agent_anystack.adapters.llm import OpenAICompatibleAdapter

            base_url = meta.get("base_url") or settings.openai_compatible_base_url or "http://127.0.0.1:11434/v1"
            api_key = meta.get("api_key")
            adapter = OpenAICompatibleAdapter(base_url=base_url, api_key=api_key)

            if model_id:
                try:
                    await adapter.complete_chat(
                        model=model_id,
                        messages=[{"role": "user", "content": "Reply OK"}],
                        max_tokens=8,
                    )
                except Exception as exc:
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST,
                        detail=f"Model '{model_id}' call failed: {exc}. Connection was NOT saved.",
                    ) from exc

                entry = VerifiedInferenceModel(
                    model_id=model_id,
                    display_name=model_id,
                    verified_at=utc_now_iso(),
                    region=None,
                )
                rest = [m for m in conn.verified_models if m.model_id != model_id]
                rest.append(entry)
                rest.sort(key=lambda m: m.model_id)
                conn.verified_models = rest
            else:
                try:
                    await adapter.list_models()
                except Exception as exc:
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST,
                        detail=f"Connection test failed at {base_url}: {exc}. Connection was NOT saved.",
                    ) from exc

            conn.status = "ok"
            conn.tested_at = utc_now_iso()
            conn.last_error = None

    saved = store.upsert(conn)
    return saved.as_dict()


@router.delete("/stacks/connections/{connection_id}")
async def delete_connection_card(
    connection_id: str,
    store: ConnectionStore = Depends(get_connection_store),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    deleted = store.delete_connection(connection_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"connection not found: {connection_id}")
    return {"ok": True, "connection_id": connection_id}


@router.post("/stacks/connections/enable-ollama-local")
async def enable_ollama_local_connection(
    store: ConnectionStore = Depends(get_connection_store),
    settings: Settings = Depends(get_settings),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """One-click 'Enable as Inference' for Ollama on Local Models tab."""
    conn_id = "ollama-local"
    existing = store.get(conn_id) or store.get("ollama")
    base_url = settings.openai_compatible_base_url or "http://127.0.0.1:11434/v1"

    if existing:
        existing.enabled = True
        existing.status = "unknown"
        existing.meta["base_url"] = base_url
        existing.meta["preset"] = "ollama"
        saved = store.upsert(existing)
    else:
        conn = StackConnection(
            id=conn_id,
            kind="inference",
            product="openai-compatible",
            label=conn_id,
            enabled=True,
            status="unknown",
            meta={"base_url": base_url, "preset": "ollama"},
            aliases=["ollama"],
        )
        saved = store.upsert(conn)

    return saved.as_dict()


@router.post("/stacks/connections/{connection_id}/verify-model")
async def verify_and_add_model(
    connection_id: str,
    body: VerifyModelBody,
    store: ConnectionStore = Depends(get_connection_store),
    bedrock_store: BedrockProviderStore = Depends(get_bedrock_store),
    settings: Settings = Depends(get_settings),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """Verify model against connection endpoint and store inside card's verified_models."""
    try:
        c = store.get_required(connection_id)
    except ConnectionNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    model_id = body.model_id.strip()
    if not model_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="model_id is required")

    display_name = (body.display_name or model_id).strip() or model_id

    if c.product == "bedrock":
        from agent_anystack.adapters.bedrock import BedrockAdapter
        from agent_anystack.adapters.bedrock_store import resolve_creds

        creds = resolve_creds(
            bedrock_store,
            env_access_key_id=settings.aws_access_key_id,
            env_secret_access_key=settings.aws_secret_access_key,
            env_session_token=settings.aws_session_token,
            env_region=settings.aws_region,
            env_api_key=settings.aws_bearer_token_bedrock,
        )
        adapter = BedrockAdapter(
            access_key_id=creds.access_key_id,
            secret_access_key=creds.secret_access_key,
            session_token=creds.session_token,
            api_key=creds.api_key,
            auth_mode=creds.auth_mode,
            region=creds.region,
        )
        try:
            await adapter.complete_chat(
                model=model_id,
                messages=[{"role": "user", "content": "Reply OK"}],
                max_tokens=8,
            )
        except Exception as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"Bedrock verify failed: {exc}") from exc

        region = creds.region
    else:
        # OpenAI-compatible / Ollama / Groq / Zen / Custom
        from agent_anystack.adapters.llm import OpenAICompatibleAdapter

        base_url = c.meta.get("base_url") or settings.openai_compatible_base_url or "http://127.0.0.1:11434/v1"
        api_key = c.meta.get("api_key")
        adapter = OpenAICompatibleAdapter(base_url=base_url, api_key=api_key)
        try:
            await adapter.complete_chat(
                model=model_id,
                messages=[{"role": "user", "content": "Reply OK"}],
                max_tokens=8,
            )
        except Exception as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"Inference verify failed: {exc}") from exc

        region = None

    entry = VerifiedInferenceModel(
        model_id=model_id,
        display_name=display_name,
        verified_at=utc_now_iso(),
        region=region,
    )
    updated = store.upsert_verified_model(c.id, entry)

    # Also sync to bedrock_store if bedrock
    if c.product == "bedrock":
        from agent_anystack.adapters.bedrock_store import BedrockModelEntry
        bedrock_store.upsert_model(
            BedrockModelEntry(
                id=model_id,
                display_name=display_name,
                verified_at=entry.verified_at,
                region=region,
            )
        )

    return {"ok": True, "connection": updated.as_dict(), "verified_model": entry.as_dict()}


@router.delete("/stacks/connections/{connection_id}/verified-models/{model_id:path}")
async def delete_verified_model(
    connection_id: str,
    model_id: str,
    store: ConnectionStore = Depends(get_connection_store),
    bedrock_store: BedrockProviderStore = Depends(get_bedrock_store),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    try:
        c = store.get_required(connection_id)
        updated = store.remove_verified_model(c.id, model_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if c.product == "bedrock":
        bedrock_store.delete_model(model_id)

    return {"ok": True, "connection": updated.as_dict()}


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
            "connection_id": e.connection_id,
            "status": e.status,
            "model": e.model,
            "started_at": e.started_at,
            "ended_at": e.ended_at,
            "error": e.error,
        }
        for e in journal.recent_for_connection(
            c.id, aliases=c.aliases, stack=c.stack(), limit=20
        )
    ]
    return {
        "connection_id": c.id,
        "kind": "inference",
        "serves": [],
        "sessions": [],
        "runs": runs,
    }


class StopServeBody(BaseModel):
    cwd: str


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
                env_api_key=settings.aws_bearer_token_bedrock,
            )
            adapter = BedrockAdapter(
                access_key_id=creds.access_key_id,
                secret_access_key=creds.secret_access_key,
                session_token=creds.session_token,
                api_key=creds.api_key,
                auth_mode=creds.auth_mode,
                region=creds.region,
            )
            if not adapter.configured():
                error = "Bedrock credentials not configured"
            else:
                ident = await adapter.test_credentials()
                meta = {
                    "account": ident.get("account") or ident.get("Account"),
                    "arn": ident.get("arn") or ident.get("Arn"),
                    "auth": ident.get("auth") or creds.auth_mode,
                    "region": ident.get("region") or creds.region,
                }
                # Also test model completion if a model is specified or verified
                target_model = c.verified_models[0].model_id if c.verified_models else c.meta.get("model_name")
                if target_model:
                    try:
                        res_text = await adapter.complete_chat(
                            model=target_model,
                            messages=[{"role": "user", "content": "Reply OK"}],
                            max_tokens=8,
                        )
                        meta["model"] = target_model
                        meta["response"] = res_text[:50] if res_text else "OK"
                    except Exception as exc:
                        error = f"Bedrock model '{target_model}' call failed: {exc}"
                        ok = False
                        updated = store.set_test_result(connection_id, ok=ok, error=error, meta=meta)
                        return {"ok": ok, "error": error, "connection": updated.as_dict()}
                ok = True
        else:
            # OpenAI-compatible / Groq / Zen / Ollama / Custom
            from agent_anystack.adapters.llm import OpenAICompatibleAdapter

            base_url = c.meta.get("base_url") or settings.openai_compatible_base_url or "http://127.0.0.1:11434/v1"
            api_key = c.meta.get("api_key")
            adapter = OpenAICompatibleAdapter(base_url=base_url, api_key=api_key)

            target_model = None
            if c.verified_models:
                target_model = c.verified_models[0].model_id
            elif c.meta.get("model_name"):
                target_model = c.meta.get("model_name")
            elif c.meta.get("default_model"):
                target_model = c.meta.get("default_model")

            if not target_model:
                try:
                    discovered = await adapter.list_models()
                    if discovered:
                        target_model = discovered[0]
                except Exception:
                    pass

            if not target_model:
                error = "No model specified or found to test. Please specify a Model Name in settings or add a verified model."
                ok = False
            else:
                try:
                    res_text = await adapter.complete_chat(
                        model=target_model,
                        messages=[{"role": "user", "content": "Reply OK"}],
                        max_tokens=8,
                    )
                    ok = True
                    meta = {
                        "model": target_model,
                        "response": res_text[:50] if res_text else "OK",
                        "base_url": base_url,
                    }
                    if not any(m.model_id == target_model for m in c.verified_models):
                        entry = VerifiedInferenceModel(
                            model_id=target_model,
                            display_name=target_model,
                            verified_at=utc_now_iso(),
                        )
                        c = store.upsert_verified_model(c.id, entry)
                except Exception as exc:
                    error = f"Model '{target_model}' call failed: {exc}"
                    ok = False
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
