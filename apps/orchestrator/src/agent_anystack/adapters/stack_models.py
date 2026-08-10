"""Unified stack model catalog — list selectable models per stack.

Stack-specific stores (Ollama / Bedrock) stay internal; Office UI uses one shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_anystack.adapters.bedrock_store import BedrockProviderStore
from agent_anystack.adapters.ollama_models import OllamaModelManager, OllamaModelsError

# Desk chat stacks that have a working adapter today.
CHAT_STACKS = frozenset({"openai-compatible", "bedrock"})

# All stack ids exposed in Create/Configure (some not yet chat-ready).
KNOWN_STACKS: tuple[dict[str, Any], ...] = (
    {
        "id": "openai-compatible",
        "label": "openai-compatible (Ollama)",
        "chat": True,
        "model_source": "ollama_installed",
    },
    {
        "id": "bedrock",
        "label": "bedrock (AWS)",
        "chat": True,
        "model_source": "bedrock_verified",
    },
    {
        "id": "cursor",
        "label": "cursor",
        "chat": False,
        "model_source": "none",
    },
    {
        "id": "claude",
        "label": "claude",
        "chat": False,
        "model_source": "none",
    },
)


@dataclass(frozen=True)
class StackModelEntry:
    id: str
    display_name: str
    ready: bool = True
    source: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "ready": self.ready,
            "source": self.source,
            "meta": self.meta,
        }


@dataclass
class StackModelsResult:
    stack: str
    selectable: bool
    hint: str
    models: list[StackModelEntry]

    def as_dict(self) -> dict[str, Any]:
        return {
            "stack": self.stack,
            "selectable": self.selectable,
            "hint": self.hint,
            "models": [m.as_dict() for m in self.models],
        }


async def list_models_for_stack(
    stack: str,
    *,
    ollama: OllamaModelManager | None = None,
    bedrock_store: BedrockProviderStore | None = None,
) -> StackModelsResult:
    """Return selectable models for Create/Configure. Unknown stacks → empty + hint."""
    sid = (stack or "").strip()
    known = {s["id"]: s for s in KNOWN_STACKS}
    if sid not in known:
        return StackModelsResult(
            stack=sid,
            selectable=False,
            hint=f"Unknown stack '{sid}'.",
            models=[],
        )

    if sid == "openai-compatible":
        return await _list_ollama(ollama)
    if sid == "bedrock":
        return _list_bedrock(bedrock_store)
    return StackModelsResult(
        stack=sid,
        selectable=False,
        hint=f"Stack '{sid}' is not available for desk chat yet.",
        models=[],
    )


async def _list_ollama(ollama: OllamaModelManager | None) -> StackModelsResult:
    if ollama is None:
        return StackModelsResult(
            stack="openai-compatible",
            selectable=False,
            hint="Ollama model manager not configured.",
            models=[],
        )
    reachable = await ollama.ping()
    if not reachable:
        return StackModelsResult(
            stack="openai-compatible",
            selectable=False,
            hint="Ollama not reachable — pull models under Stacks first.",
            models=[],
        )
    try:
        rows = await ollama.list_installed()
    except OllamaModelsError as exc:
        return StackModelsResult(
            stack="openai-compatible",
            selectable=False,
            hint=str(exc),
            models=[],
        )
    models = [
        StackModelEntry(
            id=m.name,
            display_name=m.name,
            ready=True,
            source="ollama_installed",
            meta={"size": m.size, "digest": m.digest},
        )
        for m in rows
        if m.name
    ]
    models.sort(key=lambda m: m.id)
    if not models:
        return StackModelsResult(
            stack="openai-compatible",
            selectable=False,
            hint="No models pulled — open Stacks and pull one first.",
            models=[],
        )
    return StackModelsResult(
        stack="openai-compatible",
        selectable=True,
        hint=f"{len(models)} pulled model(s) available",
        models=models,
    )


def _list_bedrock(store: BedrockProviderStore | None) -> StackModelsResult:
    if store is None:
        return StackModelsResult(
            stack="bedrock",
            selectable=False,
            hint="Bedrock store not configured.",
            models=[],
        )
    entries = store.list_models()
    models = [
        StackModelEntry(
            id=e.id,
            display_name=e.display_name or e.id,
            ready=True,
            source="bedrock_verified",
            meta={"verified_at": e.verified_at, "region": e.region},
        )
        for e in entries
    ]
    if not models:
        return StackModelsResult(
            stack="bedrock",
            selectable=False,
            hint="Verify a model on Stacks → Bedrock first.",
            models=[],
        )
    return StackModelsResult(
        stack="bedrock",
        selectable=True,
        hint=f"{len(models)} verified Bedrock model(s)",
        models=models,
    )
