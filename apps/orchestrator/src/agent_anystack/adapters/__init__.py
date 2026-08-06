"""Stack adapters — OpenAI-compatible first; other wires as separate concrete classes later."""

from collections.abc import AsyncIterator
from typing import Protocol


class StackAdapter(Protocol):
    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
    ) -> AsyncIterator[str]:
        """Yield assistant text deltas. Raises StackError on failure."""
        ...


class StackError(Exception):
    """Adapter/connectivity/model errors (server up but model missing, etc.)."""

    def __init__(self, message: str, *, code: str = "stack_error") -> None:
        self.code = code
        super().__init__(message)
