"""Reaction rules: what triggers a picture, how likely, and which one. Pure Python, nothing here talks to Vector.

A rule line (the "Triggers" setting, one per line)::

    happy: yay, hooray, good news
    sad@80: rip, f in chat        # @80 = this rule fires 80% of the time (default: the module's chance)
    any: lol, lmao                # "any" picks a random category

Phrases match whole words (or whole phrases), ignoring case. A line may start with # to switch it off.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

CATALOG = json.loads((Path(__file__).with_name("catalog.json")).read_text("utf-8"))
CATEGORIES = list(CATALOG)

# What "a category is mentioned" means in the general mode: the category's own name and a few close words.
RELATED = {
    "angry": ["angry", "mad", "furious", "annoyed", "rage", "pissed", "irritated", "grr", "pout", "hate this"],
    "calm-down": ["calm down", "relax", "chill", "just kidding", "jk", "joking", "kidding", "it's a joke"],
    "confused": ["confused", "confusing", "huh", "what?", "i don't get it", "dont get it", "no idea", "shrug",
                 "what do you mean", "wdym", "idk"],
    "dance": ["dance", "dancing", "party", "celebrate", "celebration", "let's go", "lets go", "boogie", "groove"],
    "embarrassed-nervous": ["embarrassed", "nervous", "awkward", "blush", "blushing", "sweating", "shy",
                            "oops", "my bad", "cringe", "anxious", "yikes"],
    "happy": ["happy", "yay", "hooray", "awesome", "great news", "love it", "so good", "cute", "aww", "wonderful",
              "congrats", "congratulations", "excited"],
    "lunch-break-time": ["lunch", "break time", "snack", "dinner", "hungry", "food", "coffee break", "eating",
                         "donut", "donuts", "brb food", "time to eat"],
    "misc": ["secret", "shh", "shhh", "psst", "sus", "peek", "flex", "pathetic", "tell me more"],
    "no": ["no", "nope", "nah", "never", "no way", "hell no", "absolutely not", "denied", "stop", "don't"],
    "pre-exercise": ["good luck", "gl", "you got this", "you can do it", "go for it", "workout", "exercise",
                     "gym", "wish me luck", "fighting"],
    "sad": ["sad", "cry", "crying", "tears", "depressed", "unhappy", "miss you", "heartbroken", "sob", "rip",
            "bad day", "lonely"],
    "smug": ["smug", "told you so", "i told you", "called it", "easy", "too easy", "gotcha", "easy win", "heh",
             "as expected", "obviously"],
    "surprised": ["surprised", "shocked", "wow", "omg", "no way", "what the", "wtf", "unbelievable", "whoa",
                  "can't believe", "cant believe", "oh my god"],
    "thinking": ["thinking", "hmm", "hmmm", "let me think", "i wonder", "pondering", "interesting",
                 "thoughts?", "good question", "let's see", "maybe"],
    "yes": ["yes", "yep", "yeah", "sure", "okay", "ok", "of course", "agreed", "thumbs up", "sounds good",
            "deal", "roger", "will do", "affirmative"],
}


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def phrase_re(phrase: str, whole_words: bool = True) -> re.Pattern | None:
    phrase = norm(phrase)
    if not phrase:
        return None
    body = r"\s+".join(re.escape(p) for p in phrase.split(" "))
    if whole_words:
        body = rf"(?<![\w]){body}(?![\w])"
    return re.compile(body, re.IGNORECASE)


@dataclass
class Rule:
    category: str                      # a category, or "any"
    phrases: list[str]
    chance: float | None = None       # percent; None = the module's setting
    line: int = 0
    patterns: list[re.Pattern] = field(default_factory=list)

    def matches(self, text: str) -> str | None:
        for phrase, pat in zip(self.phrases, self.patterns):
            if pat.search(text):
                return phrase
        return None


def resolve_category(name: str) -> str | None:
    """A category from what someone typed: exact, without dashes, or a unique prefix ("emb" -> embarrassed-nervous)."""
    n = norm(name).replace(" ", "-").replace("_", "-")
    if n in ("any", "random", "*"):
        return "any"
    if n in CATALOG:
        return n
    flat = n.replace("-", "")
    hits = [c for c in CATEGORIES if c.replace("-", "") == flat] or [c for c in CATEGORIES if c.startswith(n)]
    return hits[0] if len(hits) == 1 else None


def parse_rules(text: str, whole_words: bool = True) -> tuple[list[Rule], list[str]]:
    """Rules and a list of problems, one per bad line (a bad line is skipped, the others still work)."""
    rules, problems = [], []
    for no, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        head, sep, tail = line.partition(":")
        if not sep or not tail.strip():
            problems.append(f"line {no}: expected “category: word, phrase”")
            continue
        chance = None
        m = re.fullmatch(r"\s*([^@]+?)\s*@\s*(\d+(?:\.\d+)?)\s*%?\s*", head)
        if m:
            head, chance = m.group(1), min(100.0, float(m.group(2)))
        category = resolve_category(head)
        if category is None:
            problems.append(f"line {no}: no category called “{head.strip()}”")
            continue
        phrases = [norm(p) for p in re.split(r"[,;\n]", tail) if norm(p)]
        pats = [phrase_re(p, whole_words) for p in phrases]
        rules.append(Rule(category, phrases, chance, no, [p for p in pats if p]))
    return rules, problems


def add_phrase(text: str, category: str, phrase: str) -> str:
    """The rules text with ``phrase`` added under ``category`` (a new line when the category has none)."""
    lines = (text or "").splitlines()
    for i, raw in enumerate(lines):
        head, sep, tail = raw.partition(":")
        if sep and not raw.strip().startswith("#"):
            h = re.sub(r"@.*", "", head)
            if resolve_category(h) == category:
                have = [norm(p) for p in re.split(r"[,;]", tail)]
                if norm(phrase) not in have:
                    lines[i] = raw.rstrip().rstrip(",") + ", " + norm(phrase)
                return "\n".join(lines)
    lines.append(f"{category}: {norm(phrase)}")
    return "\n".join(lines)


def remove_phrase(text: str, category: str, phrase: str) -> tuple[str, bool]:
    lines, done = (text or "").splitlines(), False
    out = []
    for raw in lines:
        head, sep, tail = raw.partition(":")
        if sep and not raw.strip().startswith("#") and resolve_category(re.sub(r"@.*", "", head)) == category:
            items = [p.strip() for p in re.split(r"[,;]", tail) if p.strip()]
            keep = [p for p in items if norm(p) != norm(phrase)]
            if len(keep) != len(items):
                done = True
            if not keep:
                continue
            raw = head + ": " + ", ".join(keep)
        out.append(raw)
    return "\n".join(out), done


@dataclass
class Pick:
    category: str
    why: str                   # the word or phrase that did it
    source: str                # "words" or "category"
    chance: float


class Matcher:
    """Turns settings into rules once, then answers "does this message trigger something?"."""

    MODES = ("words", "category", "both")

    def __init__(self, rules_text: str, mode: str = "both", categories=None, whole_words: bool = True,
                 chance: float = 30, category_chance: float = 15, rng: random.Random | None = None):
        self.mode = mode if mode in self.MODES else "both"
        self.rng = rng or random.Random()
        self.chance = float(chance)
        self.category_chance = float(category_chance)
        wanted = [resolve_category(c) for c in (categories or [])]
        self.allowed = {c for c in wanted if c and c != "any"} or set(CATEGORIES)
        self.rules, self.problems = parse_rules(rules_text, whole_words)
        self.related = {c: [p for p in (phrase_re(w, whole_words) for w in [c.replace("-", " "), *RELATED.get(c, [])])
                            if p]
                        for c in CATEGORIES}

    def candidates(self, text: str) -> list[tuple[str, str, str, float]]:
        """Everything the message would trigger: (category, why, source, chance), before any dice are thrown."""
        text = norm(text)
        found = []
        if not text:
            return found
        if self.mode in ("words", "both"):
            for r in self.rules:
                why = r.matches(text)
                if why:
                    cat = r.category
                    found.append((cat, why, "words", self.chance if r.chance is None else r.chance))
        if self.mode in ("category", "both"):
            for cat, pats in self.related.items():
                if cat not in self.allowed:
                    continue
                for p in pats:
                    m = p.search(text)
                    if m:
                        found.append((cat, m.group(0), "category", self.category_chance))
                        break
        return found

    def pick(self, text: str) -> Pick | None:
        """One reaction (or None). Your own trigger words beat the general mode; each candidate gets its own roll."""
        cands = self.candidates(text)
        cands.sort(key=lambda c: c[2] != "words")          # custom words first
        for cat, why, source, chance in cands:
            if cat == "any":
                cat = self.rng.choice(sorted(self.allowed))
            elif cat not in self.allowed and source == "category":
                continue
            if chance >= 100 or self.rng.random() * 100 < chance:
                return Pick(cat, why, source, chance)
        return None


def choose_file(category: str, recent: list[str], rng: random.Random | None = None, names=None) -> str | None:
    """A picture of the category that wasn't used lately."""
    rng = rng or random
    pool = list(names if names is not None else CATALOG.get(category, []))
    if not pool:
        return None
    fresh = [n for n in pool if n not in recent] or pool
    return rng.choice(fresh)
