from __future__ import annotations

from enum import Enum
from pathlib import Path
import re
from typing import Any, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

from agent_anystack.domain.agent import AgentConfig
from agent_anystack.capabilities.apis.auth import has_auth_handler
from agent_anystack.capabilities.registry import has_handler


class CapabilityKind(str, Enum):
    internal_tool = "internal_tool"
    mcp = "mcp"
    api = "api"
    skill = "skill"


class ApiRequestMapping(BaseModel):
    path: dict[str, str] = Field(default_factory=dict)
    query: dict[str, str] = Field(default_factory=dict)
    body: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)


class ApiOperation(BaseModel):
    callable_name: str = Field(
        validation_alias=AliasChoices("callable_name", "tool_name")
    )
    description: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str
    parameters: dict[str, Any]
    request: ApiRequestMapping = Field(default_factory=ApiRequestMapping)
    idempotency_key_header: str | None = None

    @field_validator("idempotency_key_header")
    @classmethod
    def validate_idempotency_header(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.strip()
            or "\r" in value
            or "\n" in value
            or ":" in value
        ):
            raise ValueError("idempotency_key_header must be a valid HTTP header name")
        return value

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if not value.startswith("/") or value.startswith("//"):
            raise ValueError("API operation path must be a root-relative path")
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("API operation path cannot override host, query, or fragment")
        return value

    @model_validator(mode="after")
    def validate_path_mappings(self) -> ApiOperation:
        import re

        placeholders = set(re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", self.path))
        if placeholders != set(self.request.path):
            raise ValueError("API request.path must map every path placeholder exactly once")
        return self


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
    callable_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callable_name", "tool_name"),
    )
    parameters: dict[str, Any] | None = None
    base_url: str | None = None
    server_url: str | None = None
    auth: dict[str, Any] = Field(default_factory=lambda: {"type": "none"})
    headers: dict[str, str] = Field(default_factory=dict)
    operations: list[ApiOperation] = Field(default_factory=list)
    content: str | None = None
    requires: list[str] = Field(default_factory=list)

    @field_validator("kind", mode="before")
    @classmethod
    def normalize_legacy_kind(cls, value: Any) -> Any:
        return CapabilityKind.api.value if value == "external_tool" else value

    @model_validator(mode="after")
    def validate_internal_tool(self) -> CapabilityCatalogItem:
        if self.kind == CapabilityKind.internal_tool:
            if not self.handler or not self.callable_name or self.parameters is None:
                raise ValueError(
                    "internal_tool capabilities require handler, callable_name, and parameters"
                )
            if not has_handler(self.handler):
                raise ValueError(f"unknown capability handler: {self.handler}")
        if self.kind == CapabilityKind.api:
            parsed = urlsplit(self.base_url or "")
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("api capabilities require a valid absolute HTTP(S) base_url")
            auth_type = str(self.auth.get("type") or "none")
            if not has_auth_handler(auth_type):
                raise ValueError(f"unknown API auth type: {auth_type}")
            _validate_user_oauth_config(self.auth)
            if not self.operations:
                raise ValueError("api capabilities require at least one operation")
            names = [operation.callable_name for operation in self.operations]
            if len(names) != len(set(names)):
                raise ValueError(f"duplicate API operation callable_name in capability {self.id}")
        if self.kind == CapabilityKind.mcp:
            parsed = urlsplit(self.server_url or "")
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("mcp capabilities require an absolute HTTP(S) server_url")
            auth_type = str(self.auth.get("type") or "none")
            if auth_type not in {"none", "api_key", "bearer", "basic", "oauth2_user"}:
                raise ValueError(f"unsupported MCP auth type: {auth_type}")
            _validate_user_oauth_config(self.auth)
        if self.kind == CapabilityKind.skill and not (self.content or "").strip():
            raise ValueError("skill capabilities require non-empty content")
        return self


def _validate_user_oauth_config(auth: dict[str, Any]) -> None:
    if auth.get("type") != "oauth2_user":
        return
    for field_name in ("authorization_url", "token_url", "client_id", "redirect_uri"):
        if not str(auth.get(field_name) or "").strip():
            raise ValueError(f"oauth2_user auth requires {field_name}")


class CapabilityCatalogService:
    """Load org capability descriptors from the office repository."""

    def __init__(self, office_root: Path) -> None:
        self.office_root = office_root
        self._items: dict[str, CapabilityCatalogItem] = {}
        catalog_dir = office_root / "catalog"
        for directory, expected_kind in (
            ("tools", CapabilityKind.internal_tool),
            ("mcp", CapabilityKind.mcp),
            ("skills", CapabilityKind.skill),
            ("apis", CapabilityKind.api),
        ):
            self._load_directory(catalog_dir / directory, expected_kind)

    def _load_directory(self, directory: Path, expected_kind: CapabilityKind) -> None:
        if not directory.is_dir():
            return

        for descriptor_path in sorted(directory.glob("*.yaml")):
            data = yaml.safe_load(descriptor_path.read_text(encoding="utf-8")) or {}
            item = CapabilityCatalogItem.model_validate(data)
            if item.kind != expected_kind:
                raise ValueError(
                    f"capability {item.id} in catalog/{directory.name} has kind "
                    f"{item.kind.value}; expected {expected_kind.value}"
                )
            self._items[item.id] = item

    def register(self, item: CapabilityCatalogItem) -> CapabilityCatalogItem:
        self._items[item.id] = item
        return item

    def save(self, item: CapabilityCatalogItem, *, create_only: bool = False) -> CapabilityCatalogItem:
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,127}", item.id):
            raise ValueError("capability id must use lowercase letters, digits, '.', '_' or '-' ")
        if create_only and item.id in self._items:
            raise FileExistsError(f"capability already exists: {item.id}")
        previous = self._items.get(item.id)
        if previous is not None and previous.kind != item.kind:
            raise ValueError("capability kind is immutable")
        directory_by_kind = {
            CapabilityKind.internal_tool: "tools",
            CapabilityKind.mcp: "mcp",
            CapabilityKind.skill: "skills",
            CapabilityKind.api: "apis",
        }
        directory = self.office_root / "catalog" / directory_by_kind[item.kind]
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{item.id}.yaml"
        payload = yaml.safe_dump(
            item.model_dump(mode="json", exclude_none=True),
            sort_keys=False,
            allow_unicode=True,
        )
        temp = target.with_suffix(".yaml.tmp")
        temp.write_text(payload, encoding="utf-8")
        temp.replace(target)
        self._items[item.id] = item
        return item

    def delete(self, item_id: str) -> bool:
        item = self._items.get(item_id)
        if item is None:
            return False
        if item.default_inherit:
            raise ValueError("default-inherited capabilities cannot be deleted")
        directory_by_kind = {
            CapabilityKind.internal_tool: "tools",
            CapabilityKind.mcp: "mcp",
            CapabilityKind.skill: "skills",
            CapabilityKind.api: "apis",
        }
        target = self.office_root / "catalog" / directory_by_kind[item.kind] / f"{item_id}.yaml"
        target.unlink(missing_ok=True)
        del self._items[item_id]
        return True

    def get(self, item_id: str) -> CapabilityCatalogItem | None:
        return self._items.get(item_id)

    def list(self) -> list[CapabilityCatalogItem]:
        return list(self._items.values())

    def default_inherited_ids(
        self,
        *,
        kind: CapabilityKind | None = None,
        tag: str | None = None,
    ) -> list[str]:
        return sorted(
            item.id
            for item in self._items.values()
            if item.default_inherit
            and (kind is None or item.kind == kind)
            and (tag is None or tag in item.tags)
        )

    def resolve_for_agent(self, agent: AgentConfig) -> list[str]:
        """Return effective capability ids for the current desk, scoped to registrations.

        Any catalog entry marked default_inherit is available to every desk. Explicit
        registrations remain category-checked and desk-scoped.
        """
        effective: set[str] = set(self.default_inherited_ids())

        registrations = agent.capability_registrations
        expected_kinds = {
            "tools": CapabilityKind.internal_tool,
            "mcp": CapabilityKind.mcp,
            "skills": CapabilityKind.skill,
            "apis": CapabilityKind.api,
        }
        for registration_name, expected_kind in expected_kinds.items():
            for item_id in getattr(registrations, registration_name):
                item = self.get(item_id)
                if item is not None and item.kind == expected_kind:
                    effective.add(item_id)

        return sorted(effective)
