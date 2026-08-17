"""OpenCode runtime registry — serves + sessions under the Stacks connection.

Desk ``connection_id`` stays the Stacks profile (e.g. ``opencode`` / ``oc-local``).
Session ids live here only (not agent.yaml).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_anystack.adapters.opencode.serve import serve_key

log = logging.getLogger(__name__)

_last_used: dict[str, float] = {}
_busy: dict[str, int] = {}
_sessions: dict[str, "SessionRuntime"] = {}
_sweeper_task: asyncio.Task[None] | None = None
_idle_ttl_seconds: float = 1800.0


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class SessionRuntime:
    session_id: str
    agent_id: str
    user_id: str
    run_id: str
    cwd: str
    connection_id: str = "opencode"
    status: str = "active"  # active | idle | ended | killed
    started_at: str = field(default_factory=utc_now_iso)
    ended_at: str | None = None
    base_url: str = ""

    @property
    def key(self) -> str:
        return serve_key(self.connection_id, self.cwd)

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "run_id": self.run_id,
            "cwd": self.cwd,
            "connection_id": self.connection_id,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "base_url": self.base_url,
        }


def configure_idle_ttl(seconds: float) -> None:
    global _idle_ttl_seconds
    _idle_ttl_seconds = max(60.0, float(seconds))


def touch_serve(key: str) -> None:
    _last_used[key] = time.monotonic()


def begin_busy(key: str) -> None:
    _busy[key] = _busy.get(key, 0) + 1
    touch_serve(key)


def end_busy(key: str) -> None:
    _busy[key] = max(0, _busy.get(key, 0) - 1)
    touch_serve(key)


def register_session(
    *,
    session_id: str,
    agent_id: str,
    user_id: str,
    run_id: str,
    cwd: Path | str,
    connection_id: str = "opencode",
    base_url: str = "",
) -> SessionRuntime:
    key_cwd = str(Path(cwd).resolve())
    row = SessionRuntime(
        session_id=session_id,
        agent_id=agent_id,
        user_id=user_id,
        run_id=run_id,
        cwd=key_cwd,
        connection_id=connection_id,
        status="active",
        base_url=base_url,
    )
    _sessions[session_id] = row
    touch_serve(row.key)
    return row


def finish_session(session_id: str, *, status: str = "idle") -> None:
    row = _sessions.get(session_id)
    if row is None:
        return
    if row.status == "killed":
        return
    row.status = status
    row.ended_at = utc_now_iso()
    touch_serve(row.key)


def get_session(session_id: str) -> SessionRuntime | None:
    return _sessions.get(session_id)


def list_sessions(*, active_only: bool = False) -> list[SessionRuntime]:
    rows = list(_sessions.values())
    if active_only:
        rows = [r for r in rows if r.status == "active"]
    rows.sort(key=lambda r: r.started_at, reverse=True)
    return rows


def list_serves_snapshot() -> list[dict[str, Any]]:
    from agent_anystack.adapters.opencode.serve import list_live_serves

    out: list[dict[str, Any]] = []
    now = time.monotonic()
    for serve in list_live_serves():
        key = serve.key
        last = _last_used.get(key, now)
        out.append(
            {
                "connection_id": serve.connection_id,
                "cwd": str(serve.cwd.resolve()),
                "port": serve.port,
                "alive": serve.alive(),
                "busy": _busy.get(key, 0),
                "idle_seconds": max(0, int(now - last)),
                "last_used_ago_seconds": max(0, int(now - last)),
            }
        )
    return out


async def stop_serve_by_cwd(cwd: str, *, connection_id: str = "opencode") -> bool:
    from agent_anystack.adapters.opencode.serve import stop_serve

    path = Path(cwd)
    key = serve_key(connection_id, path)
    if _busy.get(key, 0) > 0:
        raise RuntimeError(f"serve is busy ({_busy[key]} active chat(s)) — wait or kill sessions first")
    await stop_serve(path, connection_id=connection_id)
    _last_used.pop(key, None)
    _busy.pop(key, None)
    for row in _sessions.values():
        if row.key == key and row.status == "active":
            row.status = "ended"
            row.ended_at = utc_now_iso()
    return True


async def kill_session(session_id: str) -> SessionRuntime:
    row = _sessions.get(session_id)
    if row is None:
        raise KeyError(f"session not found: {session_id}")
    if row.base_url:
        try:
            from agent_anystack.adapters.opencode.adapter import make_client

            client = make_client(row.base_url, timeout=30.0)
            try:
                try:
                    await client.session.abort(id=session_id)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    await client.session.delete(id=session_id)
                except Exception:  # noqa: BLE001
                    pass
            finally:
                try:
                    await client.close()
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            log.warning("kill_session API calls failed %s: %s", session_id, exc)
    row.status = "killed"
    row.ended_at = utc_now_iso()
    return row


async def stop_all_opencode_serves(*, force: bool = False) -> int:
    from agent_anystack.adapters.opencode.serve import list_live_serves, stop_serve

    n = 0
    for serve in list(list_live_serves()):
        key = serve.key
        if not force and _busy.get(key, 0) > 0:
            continue
        await stop_serve(serve.cwd, connection_id=serve.connection_id)
        _last_used.pop(key, None)
        _busy.pop(key, None)
        n += 1
    for row in _sessions.values():
        if row.status == "active":
            row.status = "ended"
            row.ended_at = utc_now_iso()
    return n


async def sweep_idle_serves() -> int:
    from agent_anystack.adapters.opencode.serve import list_live_serves, stop_serve

    now = time.monotonic()
    stopped = 0
    for serve in list(list_live_serves()):
        key = serve.key
        if _busy.get(key, 0) > 0:
            continue
        last = _last_used.get(key, now)
        if now - last < _idle_ttl_seconds:
            continue
        log.info("opencode serve idle TTL key=%s idle=%.0fs", key, now - last)
        await stop_serve(serve.cwd, connection_id=serve.connection_id)
        _last_used.pop(key, None)
        stopped += 1
    return stopped


async def _sweeper_loop() -> None:
    while True:
        try:
            await asyncio.sleep(60)
            await sweep_idle_serves()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("opencode idle sweeper error")


def ensure_sweeper_started() -> None:
    global _sweeper_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _sweeper_task is not None and not _sweeper_task.done():
        return
    _sweeper_task = loop.create_task(_sweeper_loop(), name="opencode-idle-sweeper")
