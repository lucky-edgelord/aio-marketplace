from __future__ import annotations

from typing import Dict, List, Protocol, runtime_checkable

ChatMessage = Dict[str, str]  # {"role": "system"|"user"|"assistant", "content": "..."}


@runtime_checkable
class ChatModel(Protocol):
    async def chat(self, messages: List[ChatMessage]) -> str:
        """Return the assistant's reply to ``messages``. Raise :class:`kitsune.errors.ChatError` on failure."""

    async def aclose(self) -> None: ...
