"""Ollama-native model management — only place allowed to call /api/pull|tags|delete.

Inference stays on OpenAI-compatible /v1 (adapters/llm.py).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

# Curated quick-start tags (LOCAL_MODEL_STACK.md). Pull allowlisted only.
CURATED_CATALOG: tuple[dict[str, str], ...] = (
    {
        "id": "llama3.2:3b",
        "label": "llama3.2:3b",
        "grade": "demo",
        "size_hint": "~2 GB",
        "note": "Chat / summarize only",
    },
    {
        "id": "llama3.2",
        "label": "llama3.2",
        "grade": "demo",
        "size_hint": "~2 GB",
        "note": "Default create-agent model",
    },
    {
        "id": "qwen2.5:7b",
        "label": "qwen2.5:7b",
        "grade": "agent",
        "size_hint": "~4.7 GB",
        "note": "Better general agent",
    },
    {
        "id": "qwen2.5-coder:7b",
        "label": "qwen2.5-coder:7b",
        "grade": "agent",
        "size_hint": "~4.7 GB",
        "note": "Developer-style roles",
    },
)

_CURATED_IDS = frozenset(e["id"] for e in CURATED_CATALOG)


@dataclass
class InstalledModel:
    name: str
    size: int | None = None
    digest: str | None = None


class OllamaModelsError(Exception):
    def __init__(self, message: str, *, code: str = "ollama_models_error") -> None:
        self.code = code
        super().__init__(message)


def ollama_native_base(openai_compatible_base_url: str) -> str:
    """http://host:11434/v1 → http://host:11434 (Ollama native root)."""
    url = openai_compatible_base_url.rstrip("/")
    if url.endswith("/v1"):
        url = url[: -len("/v1")]
    return url.rstrip("/") or url


def assert_curated(name: str) -> str:
    tag = name.strip()
    if tag not in _CURATED_IDS:
        raise OllamaModelsError(
            f"model '{tag}' is not in the curated catalog",
            code="not_curated",
        )
    return tag


class OllamaModelManager:
    """List / pull / delete via Ollama native HTTP API."""

    def __init__(self, openai_compatible_base_url: str, timeout: float = 600.0) -> None:
        self.native_base = ollama_native_base(openai_compatible_base_url)
        self.timeout = timeout

    async def ping(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.native_base}/api/tags")
                return resp.status_code < 500
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    async def list_installed(self) -> list[InstalledModel]:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(f"{self.native_base}/api/tags")
        except httpx.ConnectError as exc:
            raise OllamaModelsError(
                f"Cannot reach Ollama at {self.native_base}. "
                "Start with: docker compose --profile ollama up -d",
                code="unreachable",
            ) from exc
        except httpx.TimeoutException as exc:
            raise OllamaModelsError(
                f"Ollama timed out at {self.native_base}",
                code="timeout",
            ) from exc
        if resp.status_code >= 400:
            raise OllamaModelsError(
                f"Ollama tags error ({resp.status_code}): {resp.text[:300]}",
                code="http",
            )
        data = resp.json()
        out: list[InstalledModel] = []
        for row in data.get("models") or []:
            out.append(
                InstalledModel(
                    name=str(row.get("name") or ""),
                    size=row.get("size"),
                    digest=row.get("digest"),
                )
            )
        return [m for m in out if m.name]

    async def pull_stream(self, name: str) -> AsyncIterator[dict[str, Any]]:
        """Yield progress dicts from Ollama NDJSON pull stream."""
        tag = assert_curated(name)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.native_base}/api/pull",
                    json={"name": tag, "stream": True},
                ) as resp:
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode("utf-8", errors="replace")
                        raise OllamaModelsError(
                            f"Ollama pull failed ({resp.status_code}): {body[:400]}",
                            code="pull_http",
                        )
                    async for line in resp.aiter_lines():
                        line = (line or "").strip()
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if err := chunk.get("error"):
                            raise OllamaModelsError(str(err), code="pull_error")
                        status = str(chunk.get("status") or "")
                        completed = chunk.get("completed")
                        total = chunk.get("total")
                        pct: float | None = None
                        if (
                            isinstance(completed, (int, float))
                            and isinstance(total, (int, float))
                            and total > 0
                        ):
                            pct = round(100.0 * float(completed) / float(total), 1)
                        yield {
                            "status": status,
                            "completed": completed,
                            "total": total,
                            "percent": pct,
                            "digest": chunk.get("digest"),
                        }
        except httpx.ConnectError as exc:
            raise OllamaModelsError(
                f"Cannot reach Ollama at {self.native_base}",
                code="unreachable",
            ) from exc
        except httpx.TimeoutException as exc:
            raise OllamaModelsError(
                f"Ollama pull timed out for {tag}",
                code="timeout",
            ) from exc

    async def unload(self, name: str) -> dict[str, Any]:
        """Unload model from Ollama memory/VRAM via keep_alive: 0 (weights stay on disk)."""
        tag = assert_curated(name)
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self.native_base}/api/generate",
                    json={
                        "model": tag,
                        "prompt": "",
                        "stream": False,
                        "keep_alive": 0,
                    },
                )
        except httpx.ConnectError as exc:
            raise OllamaModelsError(
                f"Cannot reach Ollama at {self.native_base}",
                code="unreachable",
            ) from exc
        except httpx.TimeoutException as exc:
            raise OllamaModelsError(
                f"Ollama unload timed out for {tag}",
                code="timeout",
            ) from exc
        if resp.status_code >= 400:
            raise OllamaModelsError(
                f"Ollama unload failed ({resp.status_code}): {resp.text[:300]}",
                code="unload_http",
            )
        data: dict[str, Any] = {}
        try:
            data = resp.json()
        except json.JSONDecodeError:
            data = {}
        return {
            "name": tag,
            "done_reason": data.get("done_reason") or "unload",
        }

    async def delete(self, name: str) -> None:
        tag = assert_curated(name)
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.request(
                    "DELETE",
                    f"{self.native_base}/api/delete",
                    json={"name": tag},
                )
        except httpx.ConnectError as exc:
            raise OllamaModelsError(
                f"Cannot reach Ollama at {self.native_base}",
                code="unreachable",
            ) from exc
        except httpx.TimeoutException as exc:
            raise OllamaModelsError("Ollama delete timed out", code="timeout") from exc
        if resp.status_code >= 400:
            raise OllamaModelsError(
                f"Ollama delete failed ({resp.status_code}): {resp.text[:300]}",
                code="delete_http",
            )
