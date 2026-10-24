from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_anystack.capabilities.catalog import (
    ApiOperation,
    CapabilityCatalogItem,
    CapabilityCatalogService,
    CapabilityKind,
)
from agent_anystack.domain.agent import AgentConfig


@dataclass(frozen=True)
class CapabilityBinding:
    callable_name: str
    kind: CapabilityKind
    item: CapabilityCatalogItem
    operation: str | None
    schema: dict[str, Any]


def build_tool_schema(item: CapabilityCatalogItem) -> dict[str, Any]:
    if not item.callable_name or item.parameters is None:
        raise ValueError(f"capability {item.id} has no callable tool schema")
    return {
        "type": "function",
        "function": {
            "name": item.callable_name,
            "description": item.description or item.name,
            "parameters": item.parameters,
        },
    }


def _build_api_tool_schema(item: CapabilityCatalogItem, operation: ApiOperation) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": operation.callable_name,
            "description": operation.description,
            "parameters": operation.parameters,
        },
    }


def build_bindings(
    catalog: CapabilityCatalogService,
    agent: AgentConfig,
) -> dict[str, CapabilityBinding]:
    bindings: dict[str, CapabilityBinding] = {}
    for item_id in catalog.resolve_for_agent(agent):
        item = catalog.get(item_id)
        if item is None:
            continue
        if item.kind == CapabilityKind.internal_tool:
            if not item.callable_name:
                raise ValueError(f"capability {item.id} has no callable_name")
            if item.callable_name in bindings:
                raise ValueError(f"duplicate capability callable_name: {item.callable_name}")
            bindings[item.callable_name] = CapabilityBinding(
                callable_name=item.callable_name,
                kind=item.kind,
                item=item,
                operation=None,
                schema=build_tool_schema(item),
            )
        elif item.kind == CapabilityKind.api:
            for operation in item.operations:
                if operation.callable_name in bindings:
                    raise ValueError(
                        f"duplicate capability callable_name: {operation.callable_name}"
                    )
                bindings[operation.callable_name] = CapabilityBinding(
                    callable_name=operation.callable_name,
                    kind=item.kind,
                    item=item,
                    operation=operation.callable_name,
                    schema=_build_api_tool_schema(item, operation),
                )
    return bindings