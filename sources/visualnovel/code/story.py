"""What she says and how she looks saying it: the system prompt, the mood tag, and a keyword fallback."""

from __future__ import annotations

import re

from .scene import MOODS, PLACES

TAG = re.compile(r"^\s*\[(\w+)\]\s*", re.I)
KEYWORDS = {
    "laugh": ["haha", "hehe", "lol", "funny", "laugh"],
    "delighted": ["yay", "amazing", "wonderful", "love it", "so happy", "!!"],
    "smug": ["obviously", "of course", "told you", "hmph", "smug"],
    "shocked": ["what?!", "wait", "really?", "no way", "whoa", "surprise"],
    "sad": ["sorry", "sad", "miss", "lonely", "cry", "unfortunately"],
    "annoyed": ["ugh", "seriously", "annoying", "whatever", "sigh"],
    "angry": ["angry", "how dare", "stop it", "furious", "idiot"],
    "sleepy": ["sleepy", "tired", "yawn", "bed", "late"],
    "smile_2": ["blush", "embarrass", "senpai", "cute"],
    "smile": ["happy", "glad", "nice", "thank", "sure", "of course"],
}


def system_prompt(name: str, persona: str, place: str, user: str) -> str:
    return (
        f"{persona.strip()}\n\n"
        f"You are {name}, a character in a visual novel. You are talking with {user}. "
        f"Right now you are both at {PLACES.get(place, place)}.\n"
        "Stay in character. Reply in 1 to 4 short sentences of natural speech, no lists, no markdown, "
        "no stage directions in asterisks.\n"
        "Start every reply with your expression in square brackets, one of: " + ", ".join(f"[{m}]" for m in MOODS)
        + ". For example: [smile] It's nice out here, isn't it?"
    )


def split_mood(reply: str) -> tuple[str, str]:
    """(mood, text without the tag). Falls back to keywords when the model forgot the tag."""
    m = TAG.match(reply or "")
    if m and m.group(1).lower() in MOODS:
        return m.group(1).lower(), reply[m.end():].strip()
    text = TAG.sub("", reply or "").strip()
    return guess(text), text


def guess(text: str) -> str:
    low = (text or "").lower()
    best, hits = "normal", 0
    for mood, words in KEYWORDS.items():
        n = sum(low.count(w) for w in words)
        if n > hits:
            best, hits = mood, n
    return best


def place_from(text: str) -> str | None:
    """A place named (or numbered) in ``text``."""
    t = (text or "").strip().lower()
    names = list(PLACES)
    if t.isdigit() and 1 <= int(t) <= len(names):
        return names[int(t) - 1]
    for n in names:
        if n in t:
            return n
    return None
