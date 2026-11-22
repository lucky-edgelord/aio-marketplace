"""DistilBERT emotion classification (Hugging Face ``transformers``).

The default model labels text as sadness, joy, love, anger, fear or surprise; those map onto Kitsune's five moods,
and low-confidence results become neutral. Needs the ``emotion`` extra; without it every reply is neutral.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from ...moods import Mood

log = logging.getLogger(__name__)

DEFAULT_MODEL = "bhadresh-savani/distilbert-base-uncased-emotion"

LABEL_TO_MOOD: Dict[str, Mood] = {
    "joy": Mood.HAPPY,
    "surprise": Mood.HAPPY,
    "love": Mood.SHY,
    "anger": Mood.MAD,
    "sadness": Mood.SAD,
    "fear": Mood.SAD,
}


def label_to_mood(label: str, score: float, threshold: float = 0.45) -> Mood:
    if score < threshold:
        return Mood.NEUTRAL
    return LABEL_TO_MOOD.get(label.lower(), Mood.NEUTRAL)


class DistilBertEmotion:
    def __init__(self, model: str = DEFAULT_MODEL, *, threshold: float = 0.45, pipeline: Any = None) -> None:
        self.model = model
        self.threshold = threshold
        self._pipe: Optional[Any] = pipeline
        self._unavailable = False

    def _load(self) -> Optional[Any]:
        if self._pipe is None and not self._unavailable:
            try:
                from transformers import pipeline

                self._pipe = pipeline("text-classification", model=self.model, top_k=None)
                log.info("loaded emotion model %s", self.model)
            except Exception as e:
                log.warning("emotion model unavailable (%s); Kitsune will look neutral", e)
                self._unavailable = True
        return self._pipe

    def warm_up(self) -> None:
        self._load()

    def detect_sync(self, text: str) -> Mood:
        pipe = self._load()
        if pipe is None or not text.strip():
            return Mood.NEUTRAL
        try:
            scores = pipe(text[:512])
        except Exception as e:
            log.warning("emotion classification failed: %s", e)
            return Mood.NEUTRAL
        if scores and isinstance(scores[0], list):
            scores = scores[0]
        best = max(scores, key=lambda s: s["score"])
        return label_to_mood(best["label"], float(best["score"]), self.threshold)

    async def detect(self, text: str) -> Mood:
        return await asyncio.to_thread(self.detect_sync, text)
