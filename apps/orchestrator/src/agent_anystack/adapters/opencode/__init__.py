"""OpenCode harness package."""

from agent_anystack.adapters.opencode.adapter import (
    CURATED_MODELS,
    DEFAULT_MODEL,
    OpenCodeAdapter,
    list_opencode_models,
)
from agent_anystack.adapters.opencode.events import parse_model_ref
from agent_anystack.adapters.opencode.thinking import read_thinking

__all__ = [
    "CURATED_MODELS",
    "DEFAULT_MODEL",
    "OpenCodeAdapter",
    "list_opencode_models",
    "parse_model_ref",
    "read_thinking",
]
