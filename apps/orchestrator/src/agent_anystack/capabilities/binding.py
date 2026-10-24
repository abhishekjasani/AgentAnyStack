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
    tool_name: str
    kind: CapabilityKind
    item: CapabilityCatalogItem
    operation: str | None
    schema: dict[str, Any]


def build_tool_schema(item: CapabilityCatalogItem) -> dict[str, Any]:
    if not item.tool_name or item.parameters is None:
        raise ValueError(f"capability {item.id} has no callable tool schema")
    return {
        "type": "function",
        "function": {
            "name": item.tool_name,
            "description": item.description or item.name,
            "parameters": item.parameters,
        },
    }


def _build_api_tool_schema(item: CapabilityCatalogItem, operation: ApiOperation) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": operation.tool_name,
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
            if not item.tool_name:
                raise ValueError(f"capability {item.id} has no tool_name")
            if item.tool_name in bindings:
                raise ValueError(f"duplicate capability tool_name: {item.tool_name}")
            bindings[item.tool_name] = CapabilityBinding(
                tool_name=item.tool_name,
                kind=item.kind,
                item=item,
                operation=None,
                schema=build_tool_schema(item),
            )
        elif item.kind == CapabilityKind.api:
            for operation in item.operations:
                if operation.tool_name in bindings:
                    raise ValueError(
                        f"duplicate capability tool_name: {operation.tool_name}"
                    )
                bindings[operation.tool_name] = CapabilityBinding(
                    tool_name=operation.tool_name,
                    kind=item.kind,
                    item=item,
                    operation=operation.tool_name,
                    schema=_build_api_tool_schema(item, operation),
                )
    return bindings