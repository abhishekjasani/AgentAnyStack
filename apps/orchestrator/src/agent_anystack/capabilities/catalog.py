from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from agent_anystack.domain.agent import AgentConfig

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


class CapabilityCatalogService:
    """Simple catalog registry for desk-scoped capability resolution."""

    def __init__(self) -> None:
        self._items: dict[str, CapabilityCatalogItem] = {}
        self._seed_default_gold_tools()

    def _seed_default_gold_tools(self) -> None:
        for tool_name in DEFAULT_GOLD_TOOLS:
            self._items[tool_name] = CapabilityCatalogItem(
                id=tool_name,
                kind=CapabilityKind.internal_tool,
                name=tool_name,
                default_inherit=True,
                approval_mode="never",
                risk_class="read_draft",
            )

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
