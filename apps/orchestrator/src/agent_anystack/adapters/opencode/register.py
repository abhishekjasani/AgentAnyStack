"""Test & register an Inference model onto an OpenCode connection."""

from __future__ import annotations

import logging
from typing import Any

from agent_anystack.adapters.bedrock_store import BedrockProviderStore
from agent_anystack.adapters.connections import (
    ConnectionStore,
    RegisteredOpencodeModel,
    utc_now_iso,
)
from agent_anystack.adapters.llm import StackError
from agent_anystack.adapters.opencode.adapter import make_client
from agent_anystack.adapters.opencode.events import parse_model_ref
from agent_anystack.adapters.opencode.providers import (
    candidate_pairs,
    list_inference_candidates,
    prepare_inject,
    scratch_cwd_for,
)
from agent_anystack.adapters.opencode.serve import (
    ensure_serve,
    find_opencode_bin,
    restart_serves_for_connection,
)
from agent_anystack.config import Settings

log = logging.getLogger(__name__)

_PING = "Reply with the single word pong and nothing else."


class RegisterError(ValueError):
    def __init__(self, message: str, *, code: str = "opencode_register") -> None:
        self.code = code
        super().__init__(message)


async def _try_chat(base_url: str, provider_id: str, model_id: str, timeout: float) -> str | None:
    client = make_client(base_url, timeout=timeout)
    session_id = ""
    try:
        session = await client.session.create(extra_body={"title": "aas-register"})
        session_id = session.id
        await client.session.chat(
            id=session_id,
            model_id=model_id,
            provider_id=provider_id,
            parts=[{"type": "text", "text": _PING}],
            extra_body={
                "agent": "build",
                "model": {"providerID": provider_id, "modelID": model_id},
            },
        )
        return None
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    finally:
        if session_id:
            try:
                await client.session.delete(id=session_id)
            except Exception:  # noqa: BLE001
                pass
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass


async def _cli_pairs(model_id: str) -> list[tuple[str, str]]:
    extra: list[tuple[str, str]] = []
    try:
        import asyncio

        bin_path = find_opencode_bin()
        proc = await asyncio.create_subprocess_exec(
            bin_path,
            "models",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        if proc.returncode != 0 or not stdout:
            return extra
        needle = model_id.lower()
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            token = line.strip().split()[0] if line.strip() else ""
            if "/" not in token:
                continue
            if needle not in token.lower() and needle not in line.lower():
                continue
            extra.append(parse_model_ref(token))
    except Exception:  # noqa: BLE001
        return extra
    return extra


async def register_inference_model(
    *,
    store: ConnectionStore,
    connection_id: str,
    inference_connection_id: str,
    inference_model_id: str,
    settings: Settings,
    bedrock: BedrockProviderStore,
    timeout: float = 90.0,
) -> dict[str, Any]:
    oc = store.get_required(connection_id)
    if oc.product != "opencode":
        raise RegisterError("Test & register only applies to OpenCode connections")

    inf = store.get_required(inference_connection_id)
    if inf.kind != "inference":
        raise RegisterError(f"'{inference_connection_id}' is not an Inference connection")
    if not inf.enabled:
        raise RegisterError(f"Inference connection '{inf.id}' is disabled")

    from agent_anystack.adapters.ollama_models import OllamaModelManager

    ollama = OllamaModelManager(
        settings.openai_compatible_base_url,
        timeout=settings.ollama_pull_timeout,
    )
    candidates = await list_inference_candidates(store, bedrock=bedrock, ollama=ollama)
    match = next(
        (
            row
            for row in candidates
            if row["inference_connection_id"] == inf.id
            and row["model_id"] == inference_model_id
        ),
        None,
    )
    if match is None:
        raise RegisterError(
            f"model '{inference_model_id}' is not on Inference catalog for '{inf.id}' "
            "— Verify & add (Bedrock) or pull (Ollama) first"
        )

    extra = [
        {
            "inference_product": match["inference_product"],
            "inference_model_id": match["model_id"],
            "model_id": match["model_id"],
            "display_name": match["display_name"],
        }
    ]
    _cfg, extra_env, cfg_hash = prepare_inject(
        database_url=settings.database_url,
        connection=oc,
        extra_models=extra,
        ollama_base_url=settings.openai_compatible_base_url,
        env_access_key_id=settings.aws_access_key_id,
        env_secret_access_key=settings.aws_secret_access_key,
        env_session_token=settings.aws_session_token,
        env_region=settings.aws_region,
    )
    cwd = scratch_cwd_for(settings.database_url, oc.id)
    try:
        serve = await ensure_serve(
            cwd,
            connection_id=oc.id,
            extra_env=extra_env,
            config_hash=cfg_hash,
        )
    except StackError as exc:
        raise RegisterError(str(exc), code=exc.code) from exc

    pairs = candidate_pairs(match["inference_product"], match["model_id"])
    for p in await _cli_pairs(match["model_id"]):
        if p not in pairs:
            pairs.insert(0, p)

    last_err = "no candidate pairs"
    for provider_id, model_id in pairs:
        log.info(
            "opencode register try connection=%s provider=%s model=%s",
            oc.id,
            provider_id,
            model_id,
        )
        err = await _try_chat(serve.base_url, provider_id, model_id, timeout)
        if err is None:
            entry = RegisteredOpencodeModel(
                inference_connection_id=inf.id,
                inference_model_id=match["model_id"],
                display_name=str(match["display_name"] or match["model_id"]),
                provider_id=provider_id,
                model_id=model_id,
                ref=f"{provider_id}/{model_id}",
                tested_at=utc_now_iso(),
                inference_product=str(match["inference_product"]),
            )
            updated = store.upsert_registered_model(oc.id, entry)
            await restart_serves_for_connection(oc.id)
            return {
                "ok": True,
                "model": entry.as_dict(),
                "tried": [{"provider_id": a, "model_id": b} for a, b in pairs],
                "connection": updated.as_dict(),
            }
        last_err = err

    raise RegisterError(
        f"OpenCode could not run '{inference_model_id}' "
        f"(last error: {last_err})"
    )
