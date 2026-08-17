"""OpenCode serve process supervision — one process per workspace cwd."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import socket
from dataclasses import dataclass
from pathlib import Path

import httpx

from agent_anystack.adapters.llm import StackError

log = logging.getLogger(__name__)

# workdir resolved path → live serve
_serves: dict[str, "OpenCodeServe"] = {}
_lock = asyncio.Lock()


def find_opencode_bin() -> str:
    env = (os.environ.get("OPENCODE_BIN") or "").strip()
    if env and Path(env).is_file():
        return env
    found = shutil.which("opencode")
    if found:
        return found
    # curl installer default location inside container/home
    for candidate in (
        Path("/root/.opencode/bin/opencode"),
        Path.home() / ".opencode" / "bin" / "opencode",
        Path("/usr/local/bin/opencode"),
    ):
        if candidate.is_file():
            return str(candidate)
    raise StackError(
        "opencode CLI not found — install into the orchestrator image "
        "(or set OPENCODE_BIN).",
        code="opencode_bin_missing",
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class OpenCodeServe:
    cwd: Path
    port: int
    process: asyncio.subprocess.Process
    bin_path: str

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def alive(self) -> bool:
        return self.process.returncode is None


def list_live_serves() -> list[OpenCodeServe]:
    return [s for s in _serves.values() if s.alive()]


async def _wait_healthy(base_url: str, *, timeout: float = 45.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    last_err = ""
    async with httpx.AsyncClient(timeout=2.0) as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                # Any HTTP response means the server is listening.
                resp = await client.get(f"{base_url}/session")
                if resp.status_code < 500:
                    return
                last_err = f"status {resp.status_code}"
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
            await asyncio.sleep(0.35)
    raise StackError(
        f"opencode serve did not become ready at {base_url}: {last_err}",
        code="opencode_serve_timeout",
    )


async def ensure_serve(cwd: Path) -> OpenCodeServe:
    """Start or reuse opencode serve bound to cwd."""
    from agent_anystack.adapters.opencode.runtime import (
        ensure_sweeper_started,
        touch_serve,
    )

    ensure_sweeper_started()
    root = cwd.resolve()
    if not root.is_dir():
        raise StackError(
            f"workspace path is not a directory: {root}",
            code="opencode_bad_cwd",
        )
    key = str(root)
    async with _lock:
        existing = _serves.get(key)
        if existing and existing.alive():
            touch_serve(root)
            return existing
        if existing:
            _serves.pop(key, None)

        bin_path = find_opencode_bin()
        port = _free_port()
        proc = await asyncio.create_subprocess_exec(
            bin_path,
            "serve",
            "--hostname",
            "127.0.0.1",
            "--port",
            str(port),
            cwd=str(root),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "OPENCODE_CLIENT": "agent-anystack"},
        )
        serve = OpenCodeServe(cwd=root, port=port, process=proc, bin_path=bin_path)
        try:
            await _wait_healthy(serve.base_url)
        except Exception:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            err_tail = ""
            if proc.stderr:
                try:
                    err_tail = (await proc.stderr.read())[-800:].decode(
                        "utf-8", errors="replace"
                    )
                except Exception:  # noqa: BLE001
                    pass
            raise StackError(
                f"failed to start opencode serve in {root}: {err_tail or 'no stderr'}",
                code="opencode_serve_failed",
            ) from None
        _serves[key] = serve
        touch_serve(root)
        log.info("opencode serve ready cwd=%s port=%s", root, port)
        return serve


async def stop_serve(cwd: Path) -> None:
    key = str(cwd.resolve())
    async with _lock:
        serve = _serves.pop(key, None)
    if serve is None:
        return
    if serve.process.returncode is None:
        serve.process.terminate()
        try:
            await asyncio.wait_for(serve.process.wait(), timeout=5)
        except asyncio.TimeoutError:
            serve.process.kill()
            await serve.process.wait()
    log.info("opencode serve stopped cwd=%s", key)
