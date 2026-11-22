from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SpeechSynthesizer(Protocol):
    async def synthesize(self, text: str) -> bytes:
        """Return encoded audio (any format ffmpeg reads). Raise :class:`kitsune.errors.SpeechError` on failure."""

    async def aclose(self) -> None: ...
