"""A light mood guesser with no model to download: looks for feeling words in her reply.

Used when the ``emotion`` extra (transformers + torch) isn't installed. It only has to pick one of her five faces, so
a handful of words per mood is enough; anything it doesn't recognise looks neutral.
"""

from __future__ import annotations

import re
from typing import Dict, List

from ...moods import Mood

WORDS: Dict[Mood, List[str]] = {
    Mood.HAPPY: ["haha", "hehe", "love it", "awesome", "great", "amazing", "yay", "fun", "nice", "glad", "excited",
                 "wonderful", "best", "congrats", "thank", "happy", "cool", "perfect", "good one", "lol"],
    Mood.MAD: ["angry", "mad", "annoying", "annoyed", "hate", "spoiler", "ugh", "terrible", "worst", "stupid",
               "bad take", "seriously", "don't you dare", "furious", "grr", "rude"],
    Mood.SAD: ["sad", "sorry", "cancelled", "canceled", "miss", "cry", "lonely", "unfortunately", "sigh", "ended",
               "heartbroken", "tragic", "depressing", "scared", "afraid", "worried"],
    Mood.SHY: ["blush", "flustered", "embarrass", "stop it", "you're too nice", "you are too nice", "cute", "sweet",
               "compliment", "shy", "flattering", "my face", "love you", "aww"],
}
_PATTERNS = {m: [re.compile(r"(?<!\w)" + re.escape(w), re.I) for w in ws] for m, ws in WORDS.items()}


def guess(text: str) -> Mood:
    """The mood with the most feeling words in ``text`` (neutral when none, or on a tie between moods)."""
    scores = {m: sum(1 for p in pats if p.search(text)) for m, pats in _PATTERNS.items()}
    best = max(scores.values())
    top = [m for m, n in scores.items() if n == best]
    return top[0] if best and len(top) == 1 else Mood.NEUTRAL


class KeywordEmotion:
    async def detect(self, text: str) -> Mood:
        return guess(text or "")
