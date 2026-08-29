"""Build OpenCode provider config + env from Inference connections (hard wire)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agent_anystack.adapters.bedrock_store import BedrockProviderStore, bedrock_data_dir
from agent_anystack.adapters.connections import (
    INFERENCE_PRESETS,
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


def candidate_pairs(
    product: str,
    model_id: str,
    inference_connection_id: str = "",
) -> list[tuple[str, str]]:
    """Ordered (provider_id, model_id) guesses for OpenCode session.chat."""
    mid = (model_id or "").strip()
    product = (product or "").strip()
    cid = (inference_connection_id or "").strip()
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
        if cid and cid not in ("bedrock", "bed-prod"):
            add(cid, mid)
        if "/" in mid:
            add("amazon-bedrock", mid.split("/", 1)[1])
    elif product in ("ollama", "openai-compatible"):
        if cid:
            add(cid, mid)
        if product == "ollama" or cid in ("ollama", "ollama-local"):
            add("ollama", mid)
        add("openai-compatible", mid)
        if "/" in mid:
            p, m = mid.split("/", 1)
            add(p, m)
    else:
        if cid:
            add(cid, mid)
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


def _model_limits(
    *,
    row: RegisteredOpencodeModel | dict[str, Any],
    conn: StackConnection | None = None,
    default_context: int | None = None,
    default_output: int | None = None,
) -> dict[str, int] | None:
    row_meta: dict[str, Any] = {}
    if isinstance(row, dict) and isinstance(row.get("meta"), dict):
        row_meta = row["meta"]
    conn_meta = conn.meta if conn else {}

    # 1. Row/model level limit
    if isinstance(row_meta.get("limit"), dict):
        lim = row_meta["limit"]
        if "context" in lim and "output" in lim:
            return {"context": int(lim["context"]), "output": int(lim["output"])}
    ctx = row_meta.get("context_limit") or row_meta.get("max_context")
    out = row_meta.get("output_limit") or row_meta.get("max_output") or row_meta.get("max_tokens")

    # 2. Connection level limit
    if ctx is None:
        if isinstance(conn_meta.get("limit"), dict):
            lim = conn_meta["limit"]
            if "context" in lim and "output" in lim:
                return {"context": int(lim["context"]), "output": int(lim["output"])}
        ctx = conn_meta.get("context_limit") or conn_meta.get("max_context")
    if out is None:
        out = conn_meta.get("output_limit") or conn_meta.get("max_output") or conn_meta.get("max_tokens")

    # 3. Preset specific defaults (e.g. Groq, Mistral, OpenRouter, DeepSeek, Together)
    preset = (conn_meta.get("preset") or "").lower() if conn_meta else ""
    preset_info = INFERENCE_PRESETS.get(preset)
    if preset_info:
        if out is None and preset_info.get("default_output_limit") is not None:
            out = preset_info["default_output_limit"]
        if ctx is None and preset_info.get("default_context_limit") is not None:
            ctx = preset_info["default_context_limit"]

    # 4. Settings default limits
    if ctx is None:
        ctx = default_context
    if out is None:
        out = default_output

    if ctx is not None and out is not None:
        return {"context": int(ctx), "output": int(out)}
    if ctx is not None:
        return {"context": int(ctx), "output": int(ctx)}
    if out is not None:
        return {"context": int(out), "output": int(out)}
    return None


def _provider_block_openai_compatible(
    *,
    name: str = "OpenAI",
    base_url: str = "",
    api_key: str | None = None,
    models: list[dict[str, Any]],
) -> dict[str, Any]:
    model_map: dict[str, Any] = {}
    for m in models:
        mid = m["id"]
        entry: dict[str, Any] = {"name": m.get("name") or mid}
        if m.get("limit"):
            entry["limit"] = m["limit"]
        model_map[mid] = entry
    url = (base_url or "http://127.0.0.1:11434/v1").rstrip("/")
    if not url.endswith("/v1") and not url.endswith("/v1beta1") and "/v1" not in url:
        url = f"{url}/v1"
    options: dict[str, Any] = {"baseURL": url}
    if api_key:
        options["apiKey"] = api_key
    return {
        "npm": "@ai-sdk/openai-compatible",
        "name": name,
        "options": options,
        "models": model_map,
    }


def _provider_block_ollama(
    *,
    base_url: str,
    models: list[dict[str, Any]],
) -> dict[str, Any]:
    return _provider_block_openai_compatible(
        name="Ollama",
        base_url=base_url or "http://127.0.0.1:11434/v1",
        models=models,
    )


def build_opencode_config(
    *,
    models: list[RegisteredOpencodeModel | dict[str, Any]],
    ollama_base_url: str,
    bedrock_region: str,
    connections: list[StackConnection] | None = None,
    store: ConnectionStore | None = None,
    default_context_limit: int | None = None,
    default_output_limit: int | None = None,
) -> dict[str, Any]:
    """opencode.json provider map covering registered + candidate models."""
    conn_map: dict[str, StackConnection] = {}
    if connections:
        for c in connections:
            conn_map[c.id] = c
            for a in c.aliases:
                conn_map[a] = c
    elif store:
        for c in store.list():
            conn_map[c.id] = c
            for a in c.aliases:
                conn_map[a] = c

    bedrock_models: list[tuple[str, str]] = []
    ollama_models: list[dict[str, Any]] = []
    custom_providers: dict[str, dict[str, Any]] = {}

    for row in models:
        if isinstance(row, RegisteredOpencodeModel):
            product = row.inference_product
            mid = row.model_id or row.inference_model_id
            name = row.display_name
            inf_conn_id = row.inference_connection_id
            prov_id = row.provider_id
        else:
            product = str(row.get("inference_product") or "")
            mid = str(row.get("model_id") or row.get("inference_model_id") or "")
            name = str(row.get("display_name") or mid)
            inf_conn_id = str(row.get("inference_connection_id") or "")
            prov_id = str(row.get("provider_id") or "")

        if not mid:
            continue

        conn = conn_map.get(inf_conn_id) or conn_map.get(product)
        if conn and not product:
            product = conn.product

        limits = _model_limits(
            row=row,
            conn=conn,
            default_context=default_context_limit,
            default_output=default_output_limit,
        )
        model_entry: dict[str, Any] = {"id": mid, "name": name}
        if limits:
            model_entry["limit"] = limits

        if product == "bedrock":
            bedrock_models.append((mid, name))
        elif product == "ollama" or (
            product == "openai-compatible"
            and (inf_conn_id in ("ollama", "ollama-local") or not inf_conn_id)
        ):
            ollama_models.append(model_entry)
        elif product == "openai-compatible" or inf_conn_id:
            pkey = prov_id or inf_conn_id or "openai-compatible"
            pname = (conn.label if conn else "") or pkey
            p_preset = (conn.meta.get("preset") or "").lower() if conn else ""
            p_base_url = (
                (conn.meta.get("base_url") if conn else "")
                or (INFERENCE_PRESETS.get(p_preset, {}).get("base_url") if p_preset else "")
                or ollama_base_url
            )
            p_api_key = conn.meta.get("api_key") if conn else None

            if pkey not in custom_providers:
                custom_providers[pkey] = {
                    "name": pname,
                    "base_url": p_base_url,
                    "api_key": p_api_key,
                    "models": [],
                }
            custom_providers[pkey]["models"].append(model_entry)
        else:
            ollama_models.append(model_entry)

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
    for pkey, pdata in custom_providers.items():
        provider[pkey] = _provider_block_openai_compatible(
            name=pdata["name"],
            base_url=pdata["base_url"],
            api_key=pdata["api_key"],
            models=pdata["models"],
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
    store: ConnectionStore | None = None,
    default_context_limit: int | None = None,
    default_output_limit: int | None = None,
) -> tuple[Path, dict[str, str], str]:
    """Write OPENCODE_CONFIG and return (config_path, extra_env, hash)."""
    conn_store = store or ConnectionStore(bedrock_data_dir(database_url))
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
        store=conn_store,
        default_context_limit=default_context_limit,
        default_output_limit=default_output_limit,
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
    seen: set[tuple[str, str]] = set()

    for c in store.list():
        if c.kind != "inference" or not c.enabled:
            continue

        # 1. Models stored directly in connection's verified_models
        for vm in c.verified_models:
            key = (c.id, vm.model_id)
            if key not in seen:
                seen.add(key)
                out.append(
                    {
                        "inference_connection_id": c.id,
                        "inference_product": c.product,
                        "model_id": vm.model_id,
                        "display_name": vm.display_name or vm.model_id,
                        "meta": {
                            "verified_at": vm.verified_at,
                            "region": vm.region,
                        },
                    }
                )

        # 2. Bedrock store catalog fallback ONLY for legacy bedrock connection with no verified_models
        if c.product == "bedrock" and not c.verified_models and c.id == "bedrock":
            for m in bedrock.list_models():
                key = (c.id, m.id)
                if key not in seen:
                    seen.add(key)
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

        # 3. Installed Ollama models fallback for ollama connection
        elif c.product in ("ollama", "openai-compatible") and ollama is not None:
            if c.id in ("ollama", "ollama-local") or c.meta.get("preset") == "ollama" or c.product == "ollama":
                try:
                    reachable = await ollama.ping()
                    if reachable:
                        rows = await ollama.list_installed()
                        for row in rows:
                            if not row.name:
                                continue
                            key = (c.id, row.name)
                            if key not in seen:
                                seen.add(key)
                                out.append(
                                    {
                                        "inference_connection_id": c.id,
                                        "inference_product": c.product,
                                        "model_id": row.name,
                                        "display_name": row.name,
                                        "meta": {},
                                    }
                                )
                except OllamaModelsError:
                    pass

    return out
