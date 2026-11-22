"""Draw visual-novel screens in memory: place, expression, dialogue box with paged text, status line and the map."""

from __future__ import annotations

import io
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 720, 540
SPRITE_AT = (108, 0)
TEXT_BOX = (150, 336, 668, 506)          # inside the chat overlay, right of the small portrait
LINE_GAP = 1.22

PLACES = {
    "bridge": "an old iron bridge in a park, under pink autumn trees",
    "swing": "a wooden swing at the edge of the park, among tall bushes",
    "grove": "a quiet grove of tall red trees",
    "path": "a leafy path in the park that leads into the woods",
    "greenhouse": "a warm greenhouse full of plants",
    "house": "outside a cosy little house",
    "table": "a small table, sitting across from each other",
}
MOODS = ["normal", "smile", "smile_2", "delighted", "laugh", "smug", "shocked", "sad", "annoyed", "angry", "sleepy"]


class Art:
    """The module's pictures and font, loaded once and kept in memory."""

    def __init__(self, root: Path):
        self.root = Path(root)

    @lru_cache(maxsize=64)
    def get(self, rel: str) -> Image.Image:
        for ext in (".webp", ".png", ".jpg"):
            p = self.root / f"{rel}{ext}"
            if p.is_file():
                im = Image.open(p)
                im.load()
                return im.convert("RGBA")
        raise FileNotFoundError(rel)

    @lru_cache(maxsize=16)
    def font(self, size: int) -> ImageFont.FreeTypeFont:
        for p in (self.root / "OpenSansEmoji.ttf", Path("DejaVuSans.ttf")):
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                pass
        return ImageFont.load_default(size)

    @lru_cache(maxsize=96)
    def stage(self, place: str, mood: str) -> Image.Image:
        """Background, character and dialogue box composited once per place and expression."""
        base = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        base.alpha_composite(self.get(f"backgrounds/{place}").resize((W, H)))
        base.alpha_composite(self.get(f"sprites/{mood}"), SPRITE_AT)
        base.alpha_composite(self.get("ui/chat"))
        return base


def wrap(draw, text: str, font, width: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        line = ""
        for word in para.split():
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=font) <= width or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return [ln for ln in lines if ln.strip()]


def paginate(text: str, art: Art, size: int = 24) -> list[str]:
    """Split ``text`` into pages that each fit the dialogue box."""
    font = art.font(size)
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    x0, y0, x1, y1 = TEXT_BOX
    per = max(1, int((y1 - y0 - 26 - 22) // (size * LINE_GAP)))
    lines = wrap(probe, clean(text), font, x1 - x0)
    return ["\n".join(lines[i:i + per]) for i in range(0, len(lines), per)] or ["…"]


def clean(text: str) -> str:
    text = re.sub(r"[*_`#>]+", "", text or "")          # markdown would show as symbols on the picture
    return re.sub(r"[ \t]+", " ", text).strip()


def screen(art: Art, place: str, mood: str, page: str, status: str, page_no: int = 1, pages: int = 1,
           speaker: str = "") -> bytes:
    im = art.stage(place, mood).copy()
    d = ImageDraw.Draw(im)
    f = art.font(24)
    x0, y0, x1, y1 = TEXT_BOX
    if speaker:
        d.text((x0, y0 - 2), speaker, font=art.font(20), fill=(255, 196, 214))
        y0 += 26
    for i, line in enumerate(page.split("\n")):
        d.text((x0, y0 + i * 24 * LINE_GAP), line, font=f, fill="white")
    if pages > 1:
        tag = f"{page_no}/{pages}"
        tw = d.textlength(tag, font=art.font(18))
        d.text((x1 - tw, y1 - 4), tag, font=art.font(18), fill=(220, 220, 230))
    sf = art.font(22)
    tw = d.textlength(status, font=sf)
    d.text(((W - tw) / 2, 24), status, font=sf, fill="white")
    return encode(im)


def map_screen(art: Art, here: str, status: str) -> bytes:
    """Every place as a numbered thumbnail over the current scene."""
    im = art.get(f"backgrounds/{here}").resize((W, H)).copy()
    im.alpha_composite(Image.new("RGBA", (W, H), (10, 10, 20, 170)))
    d = ImageDraw.Draw(im)
    names = list(PLACES)
    cols, tw, th, gap = 4, 150, 112, 18
    rows = (len(names) + cols - 1) // cols
    top = 80 + (H - 80 - rows * (th + 34) - (rows - 1) * gap) // 2
    for i, name in enumerate(names):
        r, c = divmod(i, cols)
        n_in_row = min(cols, len(names) - r * cols)
        left = (W - n_in_row * tw - (n_in_row - 1) * gap) // 2
        x, y = left + c * (tw + gap), top + r * (th + 34 + gap)
        thumb = art.get(f"backgrounds/{name}").resize((tw, th))
        mask = Image.new("L", (tw, th), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, tw - 1, th - 1], 12, fill=255)
        im.paste(thumb, (x, y), mask)
        d.rounded_rectangle([x, y, x + tw - 1, y + th - 1], 12,
                            outline=(255, 196, 214) if name == here else (255, 255, 255), width=4 if name == here else 2)
        num = str(i + 1)
        nf = art.font(46)
        d.text((x + (tw - d.textlength(num, font=nf)) / 2, y + 22), num, font=nf, fill="white",
               stroke_width=3, stroke_fill=(0, 0, 0))
        lf = art.font(19)
        label = name.capitalize()
        d.text((x + (tw - d.textlength(label, font=lf)) / 2, y + th + 4), label, font=lf, fill="white")
    sf = art.font(22)
    w = d.textlength(status, font=sf)
    d.text(((W - w) / 2, 24), status, font=sf, fill="white")
    return encode(im)


def encode(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=87, optimize=True)
    return buf.getvalue()
