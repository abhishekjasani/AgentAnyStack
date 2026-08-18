"""Bedrock stack — write-only creds + verified model catalog (Stacks UI)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from agent_anystack.adapters.bedrock import BedrockAdapter
from agent_anystack.adapters.bedrock_store import (
    BedrockModelEntry,
    BedrockProviderStore,
    bedrock_data_dir,
    resolve_creds,
    utc_now_iso,
    validate_inference_id,
)
from agent_anystack.adapters.llm import StackError
from agent_anystack.api.deps import get_user_id
from agent_anystack.config import Settings, get_settings

router = APIRouter(tags=["bedrock"])


class BedrockCredsPut(BaseModel):
    """Write-only. Omit or blank secrets to leave stored; session_token sent when set."""

    access_key_id: str | None = Field(default=None, max_length=128)
    secret_access_key: str | None = Field(default=None, max_length=256)
    session_token: str | None = Field(default=None, max_length=4096)
    api_key: str | None = Field(default=None, max_length=8192)
    auth_mode: str | None = Field(default=None, max_length=16)
    region: str | None = Field(default=None, max_length=64)


class BedrockModelAdd(BaseModel):
    inference_id: str = Field(..., min_length=1, max_length=200)
    display_name: str | None = Field(default=None, max_length=128)


def get_bedrock_store(settings: Settings = Depends(get_settings)) -> BedrockProviderStore:
    return BedrockProviderStore(bedrock_data_dir(settings.database_url))


def _adapter_from_store(
    store: BedrockProviderStore,
    settings: Settings,
) -> BedrockAdapter:
    creds = resolve_creds(
        store,
        env_access_key_id=settings.aws_access_key_id,
        env_secret_access_key=settings.aws_secret_access_key,
        env_session_token=settings.aws_session_token,
        env_region=settings.aws_region,
        env_api_key=settings.aws_bearer_token_bedrock,
    )
    return BedrockAdapter(
        access_key_id=creds.access_key_id,
        secret_access_key=creds.secret_access_key,
        session_token=creds.session_token,
        api_key=creds.api_key,
        auth_mode=creds.auth_mode,
        region=creds.region,
        timeout=min(120.0, settings.openai_compatible_timeout),
    )


@router.get("/stacks/bedrock")
async def bedrock_status(
    store: BedrockProviderStore = Depends(get_bedrock_store),
    settings: Settings = Depends(get_settings),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """Status only — never returns access_key_id, secret, or api_key."""
    status_body = store.status()
    # Env fallback counts as configured for operators who skip UI put.
    if not status_body["configured"]:
        env_iam = bool(
            (settings.aws_access_key_id or "").strip()
            and (settings.aws_secret_access_key or "").strip()
        )
        env_api = bool((settings.aws_bearer_token_bedrock or "").strip())
        if env_api:
            status_body = {
                **status_body,
                "configured": True,
                "auth_mode": "api_key",
                "region": (settings.aws_region or "us-east-1").strip() or "us-east-1",
                "access_key_hint": None,
                "has_session_token": False,
                "has_api_key": True,
                "api_key_hint": None,
                "source": "env",
            }
        elif env_iam:
            status_body = {
                **status_body,
                "configured": True,
                "auth_mode": "iam",
                "region": (settings.aws_region or "us-east-1").strip() or "us-east-1",
                "access_key_hint": None,
                "has_session_token": bool(
                    (settings.aws_session_token or "").strip()
                ),
                "has_api_key": False,
                "api_key_hint": None,
                "source": "env",
            }
        else:
            status_body = {**status_body, "source": "none"}
    else:
        status_body = {**status_body, "source": "store"}
    return status_body


@router.put("/stacks/bedrock")
async def bedrock_put_creds(
    body: BedrockCredsPut,
    store: BedrockProviderStore = Depends(get_bedrock_store),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """Write-only credential upsert. Response is status only (no secrets)."""
    try:
        # Treat blank strings as "omit" so UI can leave fields empty on rotate region-only.
        ak = body.access_key_id
        sk = body.secret_access_key
        st = body.session_token
        api = body.api_key
        if ak is not None and not ak.strip():
            ak = None
        if sk is not None and not sk.strip():
            sk = None
        if api is not None and not api.strip():
            api = None
        # session_token: omit from body = leave; non-empty = set; explicit "" clears
        return store.put_creds(
            access_key_id=ak,
            secret_access_key=sk,
            session_token=st,
            api_key=api,
            auth_mode=body.auth_mode,
            region=body.region,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/stacks/bedrock/test")
async def bedrock_test(
    store: BedrockProviderStore = Depends(get_bedrock_store),
    settings: Settings = Depends(get_settings),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """Creds-only probe: STS for IAM, Bedrock runtime for API key (no catalog model)."""
    adapter = _adapter_from_store(store, settings)
    if not adapter.configured():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Bedrock not configured — PUT IAM keys or a Bedrock API key first (or set AWS_* / AWS_BEARER_TOKEN_BEDROCK env).",
        )
    try:
        ident = await adapter.test_credentials()
    except StackError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail={"ok": False, "message": str(exc), "code": exc.code},
        ) from exc
    return {"ok": True, **ident}


@router.post("/stacks/bedrock/models", status_code=status.HTTP_201_CREATED)
async def bedrock_add_model(
    body: BedrockModelAdd,
    store: BedrockProviderStore = Depends(get_bedrock_store),
    settings: Settings = Depends(get_settings),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """Verify inference id with Converse, then add to catalog."""
    try:
        inference_id = validate_inference_id(body.inference_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    adapter = _adapter_from_store(store, settings)
    if not adapter.configured():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Configure Bedrock credentials before verifying a model.",
        )
    try:
        await adapter.complete_chat(
            model=inference_id,
            messages=[{"role": "user", "content": "Reply with OK only."}],
            temperature=0.0,
            max_tokens=8,
        )
    except StackError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail={
                "ok": False,
                "message": f"verify failed: {exc}",
                "code": exc.code,
            },
        ) from exc

    entry = BedrockModelEntry(
        id=inference_id,
        display_name=(body.display_name or inference_id).strip() or inference_id,
        verified_at=utc_now_iso(),
        region=adapter.region,
    )
    store.upsert_model(entry)
    return entry.as_dict()


@router.delete(
    "/stacks/bedrock/models/{model_id:path}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def bedrock_delete_model(
    model_id: str,
    store: BedrockProviderStore = Depends(get_bedrock_store),
    _user_id: str = Depends(get_user_id),
) -> None:
    if not store.delete_model(model_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"not in catalog: {model_id}")
