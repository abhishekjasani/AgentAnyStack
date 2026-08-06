"""Stack adapters — re-export from llm (single module for concrete classes)."""

from agent_anystack.adapters.llm import (
    OpenAICompatibleAdapter,
    StackAdapter,
    StackError,
)

__all__ = ["OpenAICompatibleAdapter", "StackAdapter", "StackError"]
