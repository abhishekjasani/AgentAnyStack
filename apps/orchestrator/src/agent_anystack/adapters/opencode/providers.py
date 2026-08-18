"""Build OpenCode provider config + env from Inference connections (hard wire)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agent_anystack.adapters.bedrock_store import BedrockProviderStore, bedrock_data_dir
from agent_anystack.adapters.connections import (
    ConnectionStore,
    RegisteredOpencodeModel,
    StackConnection,
)
from agent_anystack.adapters.ollama_models import OllamaModelManager, OllamaModelsError


def opencode_data_dir(database_url: str) -> Path:
    root = bedrock_data_dir(database_url)
    path = root / "opencode"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path_for(database_url: str, connection_id: str) -> Path:
    d = opencode_data_dir(database_url) / connection_id
    d.mkdir(parents=True, exist_ok=True)
    return d / "opencode.json"


def scratch_cwd_for(database_url: str, connection_id: str) -> Path:
    d = opencode_data_dir(database_url) / connection_id / "ws"
    d.mkdir(parents=True, exist_ok=True)
    (d / ".keep").write_text("", encoding="utf-8")
    return d


def config_hash(payload: dict[str, Any], extra_env: dict[str, str]) -> str:
    blob = json.dumps({"cfg": payload, "env": extra_env}, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def candidate_pairs(product: str, model_id: str) -> list[tuple[str, str]]:
    """Ordered (provider_id, model_id) guesses for OpenCode session.chat."""
    mid = (model_id or "").strip()
    product = (product or "").strip()
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []

    def add(p: str, m: str) -> None:
        key = (p, m)
        if not p or not m or key in seen:
            return
        seen.add(key)
        out.append(key)

    if product == "bedrock":
        add("amazon-bedrock", mid)
        add("bedrock", mid)
        if "/" in mid:
            add("amazon-bedrock", mid.split("/", 1)[1])
    elif product == "ollama":
        add("ollama", mid)
        add("openai-compatible", mid)
    else:
        add("opencode", mid)
        if "/" in mid:
            p, m = mid.split("/", 1)
            add(p, m)
    return out


def _provider_block_bedrock(
    *,
    region: str,
    models: list[tuple[str, str]],
) -> dict[str, Any]:
    model_map: dict[str, Any] = {}
    for mid, name in models:
        model_map[mid] = {"name": name or mid}
    return {
        "options": {"region": region or "us-east-1"},
        "models": model_map,
    }


def _provider_block_ollama(
    *,
    base_url: str,
    models: list[tuple[str, str]],
) -> dict[str, Any]:
    model_map: dict[str, Any] = {}
    for mid, name in models:
        model_map[mid] = {"name": name or mid}
    url = (base_url or "http://127.0.0.1:11434/v1").rstrip("/")
    if not url.endswith("/v1"):
        url = f"{url}/v1"
    return {
        "npm": "@ai-sdk/openai-compatible",
        "name": "Ollama",
        "options": {"baseURL": url},
        "models": model_map,
    }


def build_opencode_config(
    *,
    models: list[RegisteredOpencodeModel | dict[str, Any]],
    ollama_base_url: str,
    bedrock_region: str,
) -> dict[str, Any]:
    """opencode.json provider map covering registered + candidate models."""
    bedrock_models: list[tuple[str, str]] = []
    ollama_models: list[tuple[str, str]] = []
    for row in models:
        if isinstance(row, RegisteredOpencodeModel):
            product = row.inference_product
            mid = row.model_id or row.inference_model_id
            name = row.display_name
        else:
            product = str(row.get("inference_product") or "")
            mid = str(row.get("model_id") or row.get("inference_model_id") or "")
            name = str(row.get("display_name") or mid)
        if not mid:
            continue
        if product == "bedrock":
            bedrock_models.append((mid, name))
        elif product == "ollama":
            ollama_models.append((mid, name))
    provider: dict[str, Any] = {}
    if bedrock_models:
        provider["amazon-bedrock"] = _provider_block_bedrock(
            region=bedrock_region,
            models=bedrock_models,
        )
    if ollama_models:
        provider["ollama"] = _provider_block_ollama(
            base_url=ollama_base_url,
            models=ollama_models,
        )
    return {
        "$schema": "https://opencode.ai/config.json",
        "provider": provider,
    }


def write_opencode_config(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def bedrock_env(
    store: BedrockProviderStore,
    *,
    env_access_key_id: str = "",
    env_secret_access_key: str = "",
    env_session_token: str = "",
    env_region: str = "us-east-1",
    env_api_key: str = "",
) -> dict[str, str]:
    from agent_anystack.adapters.bedrock_store import resolve_creds

    creds = resolve_creds(
        store,
        env_access_key_id=env_access_key_id,
        env_secret_access_key=env_secret_access_key,
        env_session_token=env_session_token,
        env_region=env_region,
        env_api_key=env_api_key,
    )
    out: dict[str, str] = {}
    if creds.uses_api_key():
        out["AWS_BEARER_TOKEN_BEDROCK"] = creds.api_key
    else:
        if creds.access_key_id:
            out["AWS_ACCESS_KEY_ID"] = creds.access_key_id
        if creds.secret_access_key:
            out["AWS_SECRET_ACCESS_KEY"] = creds.secret_access_key
        if creds.session_token:
            out["AWS_SESSION_TOKEN"] = creds.session_token
    if creds.region:
        out["AWS_REGION"] = creds.region
        out["AWS_DEFAULT_REGION"] = creds.region
    return out


def prepare_inject(
    *,
    database_url: str,
    connection: StackConnection,
    extra_models: list[dict[str, Any]] | None = None,
    ollama_base_url: str,
    env_access_key_id: str = "",
    env_secret_access_key: str = "",
    env_session_token: str = "",
    env_region: str = "us-east-1",
    env_api_key: str = "",
) -> tuple[Path, dict[str, str], str]:
    """Write OPENCODE_CONFIG and return (config_path, extra_env, hash)."""
    bedrock = BedrockProviderStore(bedrock_data_dir(database_url))
    rows: list[RegisteredOpencodeModel | dict[str, Any]] = list(
        connection.registered_models
    )
    rows.extend(extra_models or [])
    region = bedrock.load_creds().region or env_region or "us-east-1"
    payload = build_opencode_config(
        models=rows,
        ollama_base_url=ollama_base_url,
        bedrock_region=region,
    )
    path = config_path_for(database_url, connection.id)
    write_opencode_config(path, payload)
    extra_env: dict[str, str] = {}
    needs_bedrock = any(
        (m.inference_product if isinstance(m, RegisteredOpencodeModel) else m.get("inference_product"))
        == "bedrock"
        for m in rows
    )
    if needs_bedrock:
        extra_env.update(
            bedrock_env(
                bedrock,
                env_access_key_id=env_access_key_id,
                env_secret_access_key=env_secret_access_key,
                env_session_token=env_session_token,
                env_region=env_region,
                env_api_key=env_api_key,
            )
        )
    extra_env["OPENCODE_CONFIG"] = str(path)
    return path, extra_env, config_hash(payload, extra_env)


async def list_inference_candidates(
    store: ConnectionStore,
    *,
    bedrock: BedrockProviderStore,
    ollama: OllamaModelManager | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in store.list():
        if c.kind != "inference" or not c.enabled:
            continue
        if c.product == "bedrock":
            for m in bedrock.list_models():
                out.append(
                    {
                        "inference_connection_id": c.id,
                        "inference_product": "bedrock",
                        "model_id": m.id,
                        "display_name": m.display_name or m.id,
                        "meta": {
                            "verified_at": m.verified_at,
                            "region": m.region,
                        },
                    }
                )
        elif c.product == "ollama":
            if ollama is None:
                continue
            try:
                reachable = await ollama.ping()
                if not reachable:
                    continue
                rows = await ollama.list_installed()
            except OllamaModelsError:
                continue
            for row in rows:
                if not row.name:
                    continue
                out.append(
                    {
                        "inference_connection_id": c.id,
                        "inference_product": "ollama",
                        "model_id": row.name,
                        "display_name": row.name,
                        "meta": {},
                    }
                )
    return out
