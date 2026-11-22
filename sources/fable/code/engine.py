"""Fable's rules, in plain Python: the characters, the rolls, the odds. Nothing here talks to Vector.

Rules ported from Fable (github.com/ker0olos/fable, MIT): stars from 1 to 5 with the pull odds 50/30/15/4/1,
stealing chances by rating, and merging five characters of one rating into one of the next. The Mudae-style parts
(an hourly roll allowance, one claim per cooldown) are this module's.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

ODDS = {1: 50, 2: 30, 3: 15, 4: 4, 5: 1}
STEAL_BASE = {1: 50, 2: 25, 3: 15, 4: 3, 5: 1}
VALUE = {1: 10, 2: 25, 3: 60, 4: 150, 5: 400}        # coins you get when a character is released
MERGE_COST = 5                                         # characters of one rating make one of the next
SHOP = {"reset": 150, "guarantee3": 300, "guarantee4": 900, "guarantee5": 2500}
STAR, EMPTY = "★", "☆"


def stars(n: int) -> str:
    return STAR * n + EMPTY * (5 - n)


@dataclass(frozen=True)
class Char:
    id: int
    name: str
    series: str
    pic: str
    stars: int

    def key(self) -> str:
        return norm(self.name)


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


class Catalog:
    """Every character in ``characters.json`` (built by tools/build_fable_data.py)."""

    def __init__(self, path: Path | None = None, rows: list | None = None, host: str = "") -> None:
        if rows is None:
            data = json.loads((path or Path(__file__).with_name("characters.json")).read_text("utf-8"))
            rows, host = data["rows"], data["host"]
        self.host = host
        self.chars = [Char(*r) for r in rows]
        self.by_id = {c.id: c for c in self.chars}
        self.by_stars: dict[int, list[Char]] = {s: [] for s in ODDS}
        for c in self.chars:
            self.by_stars[c.stars].append(c)
        self._index = [(norm(c.name), norm(c.series), c) for c in self.chars]

    def url(self, c: Char) -> str:
        return self.host + c.pic

    def find(self, query: str, limit: int = 8) -> list[Char]:
        """Characters matching ``query``: exact name first, then names starting with it, then every word found."""
        q = norm(query)
        if not q:
            return []
        words = q.split()
        scored = []
        for name, series, c in self._index:
            if name == q:
                score = 0
            elif name.startswith(q):
                score = 1
            elif all(w in name.split() or w in name for w in words):
                score = 2
            elif all(w in f"{name} {series}" for w in words):
                score = 3
            else:
                continue
            scored.append((score, -c.stars, name, c))
        scored.sort(key=lambda t: t[:3])
        return [c for *_, c in scored[:limit]]

    def roll_stars(self, rng: random.Random, at_least: int = 1) -> int:
        """A rating by the pull odds; ``at_least`` is a guarantee (the odds of the ratings from there up)."""
        options = {s: w for s, w in ODDS.items() if s >= at_least}
        return rng.choices(list(options), weights=list(options.values()))[0]

    def pick(self, rng: random.Random, stars_: int, taken: set | None = None) -> Char | None:
        """A random character of that rating, not one in ``taken`` unless every one is."""
        pool = self.by_stars.get(stars_) or []
        free = [c for c in pool if not taken or c.id not in taken]
        return rng.choice(free or pool) if (free or pool) else None


def steal_chance(stars_: int, inactive_days: float) -> int:
    """Percent: the rating's base chance, plus a bonus when the owner hasn't been around, at most 90."""
    chance = STEAL_BASE.get(stars_, 0)
    chance += 90 if inactive_days > 30 else 50 if inactive_days >= 14 else 25 if inactive_days >= 7 else 0
    return min(chance, 90)


def window(now: float, started: float, hours: float = 1.0) -> tuple[bool, float]:
    """(is a new allowance window due, seconds until the current one ends)."""
    length = hours * 3600
    if not started or now - started >= length:
        return True, 0.0
    return False, started + length - now


def wait(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, m = divmod(seconds // 60, 60)
    return f"{h}h {m:02d}m" if h else (f"{m}m {seconds % 60:02d}s" if m else f"{seconds}s")


def merge_group(owned: list[Char], target: int, protected: set | None = None) -> list[Char] | None:
    """The five characters to give up for a ``target``-star one: the lowest-liked of the rating below."""
    pool = [c for c in owned if c.stars == target - 1 and not (protected and c.id in protected)]
    pool.sort(key=lambda c: (c.name))
    return pool[:MERGE_COST] if len(pool) >= MERGE_COST and 2 <= target <= 5 else None
