"""Neku's frame grid, built from the Fox Mafia sprites.

Neku loaded three looping videos (``vids/0.mp4`` closed, ``1.mp4`` half, ``2.mp4`` open) into ``self.grid`` and
picked ``grid[volume_class][i % 32]``. Here each mood's sprites build the same 3 x 32 grid: row 0 has the mouth
closed, rows 1 and 2 talking, and every row blinks once per loop (two seconds at 16 fps).

Sprites live in ``<sprites_dir>/<mood>/{open,blink}_{closed,talk}.png``.
"""

from __future__ import annotations

import io
import os
from typing import Dict, List

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from ..moods import Mood

FRAME_NAMES = ("open_closed", "open_talk", "blink_closed", "blink_talk")
ROWS = 3  # Neku's volume classes
LOOP = 32  # frames per row, as in Neku (i % 32)
BLINK_AT = range(24, 27)  # loop positions where her eyes are shut

Grid = List[List[np.ndarray]]


def backdrop(size: int) -> Image.Image:
    """A dark backdrop with a soft red glow behind her (her colours)."""
    bg = Image.new("RGB", (size, size), (18, 16, 22))
    glow = Image.new("L", (size, size), 0)
    ImageDraw.Draw(glow).ellipse((-size * 0.2, size * 0.05, size * 1.2, size * 1.3), fill=150)
    glow = glow.filter(ImageFilter.GaussianBlur(max(1, size // 5)))
    return Image.composite(Image.new("RGB", (size, size), (120, 22, 34)), bg, glow)


def square_crop(im: Image.Image, top_fraction: float = 0.02) -> Image.Image:
    """Square crop on the head and shoulders of a portrait sprite."""
    w, h = im.size
    side = min(w, h)
    top = min(round(h * top_fraction), h - side)
    left = (w - side) // 2
    return im.crop((left, top, left + side, top + side))


def _open(folder: str, name: str) -> Image.Image:
    """``<name>.png``, or ``<name>.webp`` (the module ships its sprites as WebP to stay small)."""
    for ext in ("png", "webp"):
        path = os.path.join(folder, f"{name}.{ext}")
        if os.path.isfile(path):
            return Image.open(path)
    raise FileNotFoundError(os.path.join(folder, f"{name}.png"))


class SpriteBank:
    def __init__(self, sprites_dir: str, size: int = 512) -> None:
        self.sprites_dir = sprites_dir
        self.size = size - size % 2
        self._frames: Dict[Mood, Dict[str, np.ndarray]] = {}
        self._grids: Dict[Mood, Grid] = {}

    def moods(self) -> List[Mood]:
        return [m for m in Mood if os.path.isdir(os.path.join(self.sprites_dir, m.value))]

    def frames(self, mood: Mood) -> Dict[str, np.ndarray]:
        """The four composited frames of a mood, by name."""
        if mood not in self._frames:
            folder = os.path.join(self.sprites_dir, mood.value)
            if not os.path.isdir(folder):
                if mood is Mood.NEUTRAL:
                    raise FileNotFoundError(f"no sprites in {self.sprites_dir!r}")
                return self.frames(Mood.NEUTRAL)
            bg = backdrop(self.size).convert("RGBA")
            out = {}
            for name in FRAME_NAMES:
                im = _open(folder, name).convert("RGBA")
                im = square_crop(im).resize((self.size, self.size), Image.LANCZOS)
                canvas = bg.copy()
                canvas.alpha_composite(im)
                out[name] = np.asarray(canvas.convert("RGB"))
            self._frames[mood] = out
        return self._frames[mood]

    def grid(self, mood: Mood) -> Grid:
        """``grid[volume_class][i % LOOP]``, exactly how Neku indexed its videos."""
        if mood not in self._grids:
            f = self.frames(mood)
            rows: Grid = []
            for row in range(ROWS):
                mouth = "closed" if row == 0 else "talk"
                rows.append([f[f"{'blink' if i in BLINK_AT else 'open'}_{mouth}"] for i in range(LOOP)])
            self._grids[mood] = rows
        return self._grids[mood]

    def still_png(self, mood: Mood) -> bytes:
        buf = io.BytesIO()
        Image.fromarray(self.frames(mood)["open_closed"]).save(buf, format="PNG")
        return buf.getvalue()
