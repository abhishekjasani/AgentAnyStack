"""Compatibility imports for callers of the former Gold tool module."""

import os
from pathlib import Path
from typing import Any

from agent_anystack.capabilities.binding import build_tool_schema
from agent_anystack.capabilities.catalog import CapabilityCatalogService, CapabilityKind
from agent_anystack.capabilities.tools.gold import execute_gold_tool
from agent_anystack.office.gold_notes import GOLD_RULES

_office_root = Path(os.environ.get("OFFICE_REPO_PATH", "/office"))
if not (_office_root / "catalog" / "tools").is_dir():
    _office_root = next(
        (
            parent / "office"
            for parent in Path(__file__).resolve().parents
            if (parent / "office" / "catalog" / "tools").is_dir()
        ),
        _office_root,
    )
_catalog = CapabilityCatalogService(_office_root)
GOLD_TOOL_SCHEMAS: list[dict[str, Any]] = [
    build_tool_schema(item)
    for item in _catalog.list()
    if item.kind == CapabilityKind.internal_tool
]

__all__ = ["GOLD_RULES", "GOLD_TOOL_SCHEMAS", "execute_gold_tool"]