from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from agent_anystack.domain.agent import AgentConfig
from agent_anystack.capabilities.registry import has_handler

DEFAULT_GOLD_TOOLS = [
    "gold.read",
    "gold.append",
    "gold.delete",
    "gold.clear",
]


class CapabilityKind(str, Enum):
    internal_tool = "internal_tool"
    mcp = "mcp"
    external_tool = "external_tool"
    skill = "skill"


class CapabilityCatalogItem(BaseModel):
    """A single org capability in the central catalog."""

    id: str
    kind: CapabilityKind
    name: str
    description: str | None = None
    default_inherit: bool = False
    approval_mode: Literal["always", "never", "autonomy"] = "never"
    risk_class: str | None = None
    secret_ref: str | None = None
    tags: list[str] = Field(default_factory=list)
    handler: str | None = None
    tool_name: str | None = None
    parameters: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_internal_tool(self) -> CapabilityCatalogItem:
        if self.kind == CapabilityKind.internal_tool:
            if not self.handler or not self.tool_name or self.parameters is None:
                raise ValueError(
                    "internal_tool capabilities require handler, tool_name, and parameters"
                )
            if not has_handler(self.handler):
                raise ValueError(f"unknown capability handler: {self.handler}")
        return self


class CapabilityCatalogService:
    """Load org capability descriptors from the office repository."""

    def __init__(self, office_root: Path) -> None:
        self._items: dict[str, CapabilityCatalogItem] = {}
        self._load_tools(office_root / "catalog" / "tools")

    def _load_tools(self, tools_dir: Path) -> None:
        if not tools_dir.is_dir():
            return

        for descriptor_path in sorted(tools_dir.glob("*.yaml")):
            data = yaml.safe_load(descriptor_path.read_text(encoding="utf-8")) or {}
            item = CapabilityCatalogItem.model_validate(data)
            self._items[item.id] = item

    def register(self, item: CapabilityCatalogItem) -> CapabilityCatalogItem:
        self._items[item.id] = item
        return item

    def get(self, item_id: str) -> CapabilityCatalogItem | None:
        return self._items.get(item_id)

    def list(self) -> list[CapabilityCatalogItem]:
        return list(self._items.values())

    def resolve_for_agent(self, agent: AgentConfig) -> list[str]:
        """Return effective capability ids for the current desk, scoped to registrations.

        Built-in gold tools default-inherit for agent desks. Higher-level approval/risk logic
        is intentionally kept out of this first release.
        """
        effective: set[str] = set()

        for item_id in DEFAULT_GOLD_TOOLS:
            if self._items.get(item_id) is not None:
                effective.add(item_id)

        for item_id in agent.registrations.mcp:
            if self.get(item_id) is not None:
                effective.add(item_id)

        for item_id in agent.registrations.skills:
            if self.get(item_id) is not None:
                effective.add(item_id)

        for item_id in agent.registrations.apis:
            if self.get(item_id) is not None:
                effective.add(item_id)

        for item_id in getattr(agent.registrations, "tools", []):
            if self.get(item_id) is not None:
                effective.add(item_id)

        return sorted(effective)
