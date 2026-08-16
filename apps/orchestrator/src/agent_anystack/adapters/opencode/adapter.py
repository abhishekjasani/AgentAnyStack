"""OpenCode harness adapter — session.chat + /event SSE (slice A)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
from opencode_ai import APIStatusError, AsyncOpencode, AsyncStream

from agent_anystack.adapters.llm import StackError
from agent_anystack.adapters.opencode.events import EventMapper, parse_model_ref
from agent_anystack.adapters.opencode.serve import ensure_serve
from agent_anystack.adapters.opencode.thinking import append_thinking

log = logging.getLogger(__name__)

DEFAULT_MODEL = "opencode/big-pickle"
CURATED_MODELS: tuple[tuple[str, str], ...] = (
    ("opencode/big-pickle", "OpenCode Zen / big-pickle (default)"),
)


def make_client(base_url: str, *, timeout: float = 300.0) -> AsyncOpencode:
    return AsyncOpencode(
        base_url=base_url.rstrip("/"),
        timeout=httpx.Timeout(timeout),
    )


async def list_opencode_models() -> list[dict[str, str]]:
    """Curated + optional `opencode models` CLI output. Ids are provider/model."""
    models: list[dict[str, str]] = [
        {"id": mid, "display_name": label} for mid, label in CURATED_MODELS
    ]
    try:
        from agent_anystack.adapters.opencode.serve import find_opencode_bin

        bin_path = find_opencode_bin()
        proc = await asyncio.create_subprocess_exec(
            bin_path,
            "models",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        if proc.returncode == 0 and stdout:
            seen = {m["id"] for m in models}
            for line in stdout.decode("utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or "/" not in line:
                    continue
                # lines like provider/model
                mid = line.split()[0] if line.split() else line
                if mid in seen:
                    continue
                seen.add(mid)
                models.append({"id": mid, "display_name": mid})
    except Exception:  # noqa: BLE001
        pass
    return models


async def _auto_permission_once(
    client: AsyncOpencode,
    session_id: str,
    permission_id: str,
) -> None:
    path = f"/session/{session_id}/permissions/{permission_id}"
    try:
        await client.post(
            path,
            cast_to=dict[str, object],
            body={"response": "once"},
        )
    except APIStatusError as exc:
        log.warning("opencode permission once failed %s: %s", path, exc)
    except Exception as exc:  # noqa: BLE001
        log.warning("opencode permission once error %s: %s", path, exc)


class OpenCodeAdapter:
    """Harness runtime for stack=opencode."""

    def __init__(
        self,
        *,
        database_url: str,
        timeout: float = 300.0,
        agent_name: str = "build",
    ) -> None:
        self.database_url = database_url
        self.timeout = timeout
        self.agent_name = agent_name

    async def run_chat(
        self,
        *,
        cwd: Path,
        model: str,
        system: str,
        user_message: str,
        run_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        serve = await ensure_serve(cwd)
        client = make_client(serve.base_url, timeout=self.timeout)
        provider_id, model_id = parse_model_ref(model or DEFAULT_MODEL)

        try:
            session = await client.session.create(
                extra_body={"title": f"aas-{run_id[:12]}"},
            )
            session_id = session.id
        except Exception as exc:  # noqa: BLE001
            raise StackError(
                f"opencode session.create failed: {exc}",
                code="opencode_session",
            ) from exc

        yield {"type": "meta_extra", "opencode_session_id": session_id, "base_url": serve.base_url}

        stop = asyncio.Event()
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        mapper = EventMapper(session_id)

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
                                await _auto_permission_once(
                                    client, session_id, str(pid)
                                )
                            continue
                        if office_ev.get("type") == "thinking":
                            append_thinking(
                                self.database_url,
                                run_id,
                                str(office_ev.get("text") or ""),
                            )
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
                        "code": "opencode_events",
                    }
                )
                stop.set()
                await queue.put(None)

        watcher = asyncio.create_task(watch())

        # Give the event stream a moment to attach before chat blocks.
        await asyncio.sleep(0.15)

        packed_user = user_message
        # OpenCode 1.x expects nested model {providerID, modelID}; flat
        # model_id/provider_id from the 0.1.0a36 SDK are ignored → build agent
        # falls back to amazon-bedrock defaults.
        chat_kwargs: dict[str, Any] = {
            "id": session_id,
            "model_id": model_id,
            "provider_id": provider_id,
            "parts": [{"type": "text", "text": packed_user}],
            "extra_body": {
                "agent": self.agent_name,
                "model": {
                    "providerID": provider_id,
                    "modelID": model_id,
                },
            },
        }
        if system.strip():
            chat_kwargs["system"] = system.strip()

        chat_task = asyncio.create_task(client.session.chat(**chat_kwargs))

        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    if chat_task.done() and stop.is_set():
                        break
                    if chat_task.done() and chat_task.exception():
                        exc = chat_task.exception()
                        yield {
                            "type": "error",
                            "message": f"opencode chat failed: {exc}",
                            "code": "opencode_chat",
                        }
                        break
                    continue
                if item is None:
                    break
                if item.get("type") == "session_idle":
                    break
                yield item
                if item.get("type") == "error":
                    break

            if not chat_task.done():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=120)
                except asyncio.TimeoutError:
                    yield {
                        "type": "error",
                        "message": "timed out waiting for opencode session idle",
                        "code": "opencode_timeout",
                    }
            else:
                try:
                    await chat_task
                except Exception as exc:  # noqa: BLE001
                    yield {
                        "type": "error",
                        "message": f"opencode chat failed: {exc}",
                        "code": "opencode_chat",
                    }
        finally:
            stop.set()
            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass
            try:
                await client.close()
            except Exception:  # noqa: BLE001
                pass
