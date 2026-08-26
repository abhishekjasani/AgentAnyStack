"""Test & register an Inference model onto an OpenCode connection."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from opencode_ai import AsyncStream

from agent_anystack.adapters.bedrock_store import BedrockProviderStore
from agent_anystack.adapters.connections import (
    ConnectionStore,
    RegisteredOpencodeModel,
    utc_now_iso,
)
from agent_anystack.adapters.llm import StackError
from agent_anystack.adapters.opencode.adapter import _auto_permission_once, make_client
from agent_anystack.adapters.opencode.events import EventMapper, parse_model_ref
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

_PING = "Reply with a single short word and nothing else."


class RegisterError(ValueError):
    def __init__(self, message: str, *, code: str = "opencode_register") -> None:
        self.code = code
        super().__init__(message)


async def _try_chat(base_url: str, provider_id: str, model_id: str, timeout: float) -> str | None:
    """Prove a real turn: ≥1 assistant token then session.idle. None = pass."""
    client = make_client(base_url, timeout=timeout)
    session_id = ""
    watcher: asyncio.Task[None] | None = None
    chat_task: asyncio.Task[Any] | None = None
    stop = asyncio.Event()
    chat_in_flight = asyncio.Event()
    try:
        session = await client.session.create(extra_body={"title": "aas-register"})
        session_id = session.id
        mapper = EventMapper(session_id)
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def watch() -> None:
            try:
                stream = await client.get(
                    "/event",
                    cast_to=dict[str, object],
                    stream=True,
                    stream_cls=AsyncStream[dict[str, object]],
                )
                async for event in stream:
                    if not isinstance(event, dict):
                        continue
                    for office_ev in mapper.map(event):
                        if office_ev.get("type") == "opencode_permission":
                            pid = office_ev.get("permission_id")
                            if pid:
                                await _auto_permission_once(client, session_id, str(pid))
                            continue
                        if (
                            office_ev.get("type") == "session_idle"
                            and not chat_in_flight.is_set()
                        ):
                            continue
                        await queue.put(office_ev)
                        if office_ev.get("type") in ("session_idle", "error"):
                            stop.set()
                            await queue.put(None)
                            return
                        if stop.is_set():
                            await queue.put(None)
                            return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                await queue.put(
                    {
                        "type": "error",
                        "message": f"opencode event stream failed: {exc}",
                    }
                )
                stop.set()
                await queue.put(None)

        watcher = asyncio.create_task(watch())
        await asyncio.sleep(0.15)
        chat_in_flight.set()
        chat_task = asyncio.create_task(
            client.session.chat(
                id=session_id,
                model_id=model_id,
                provider_id=provider_id,
                parts=[{"type": "text", "text": _PING}],
                extra_body={
                    "agent": "title",
                    "model": {"providerID": provider_id, "modelID": model_id},
                },
            )
        )

        got_token = False
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(15.0, float(timeout))
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                if got_token:
                    return "timed out waiting for session idle after tokens"
                return "timed out with no assistant tokens from OpenCode"
            try:
                item = await asyncio.wait_for(queue.get(), timeout=min(1.0, remaining))
            except asyncio.TimeoutError:
                if chat_task.done() and chat_task.exception():
                    return f"opencode chat failed: {chat_task.exception()}"
                continue
            if item is None:
                break
            kind = item.get("type")
            if kind == "token" and str(item.get("text") or "").strip():
                got_token = True
            elif kind == "error":
                return str(item.get("message") or "opencode error")
            elif kind == "session_idle":
                if got_token:
                    return None
                return "session idle with no assistant tokens"

        if chat_task.done() and chat_task.exception():
            return f"opencode chat failed: {chat_task.exception()}"
        if got_token and stop.is_set():
            return None
        if got_token:
            return "tokens received but session did not go idle"
        return "no assistant tokens received"
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    finally:
        stop.set()
        if watcher is not None:
            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass
        if chat_task is not None and not chat_task.done():
            chat_task.cancel()
            try:
                await chat_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
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
    if inf.status == "error":
        detail = inf.last_error or "Inference Test is in error"
        raise RegisterError(
            f"Inference '{inf.id}' last Test failed ({detail}) — "
            "fix credentials and Test that connection first"
        )

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
            "inference_connection_id": match["inference_connection_id"],
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
        env_api_key=settings.aws_bearer_token_bedrock,
        store=store,
        default_context_limit=settings.opencode_default_context_limit,
        default_output_limit=settings.opencode_default_output_limit,
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

    pairs = candidate_pairs(
        match["inference_product"],
        match["model_id"],
        inference_connection_id=inf.id,
    )
    for p in await _cli_pairs(match["model_id"]):
        if p not in pairs:
            pairs.append(p)

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
