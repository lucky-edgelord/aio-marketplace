from __future__ import annotations

from typing import Protocol, runtime_checkable

from ...moods import Mood


@runtime_checkable
class EmotionDetector(Protocol):
    async def detect(self, text: str) -> Mood:
        """Pick the mood that fits ``text``. Should never raise: fall back to ``Mood.NEUTRAL``."""
