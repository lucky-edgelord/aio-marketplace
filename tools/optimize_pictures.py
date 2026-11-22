"""Optimize pictures:  exactly ``WIDTH`` x ``WIDTH`` pixels (a centered square crop) and no bigger than ``limit`` bytes (1 MB by default).
Pillow only.

    python3 tools/optimize_pictures.py SOURCE_FOLDER DEST_FOLDER [LIMIT_KB]   (folders of category/picture, as in the reactions module)

The size never changes after that first crop and resize. To get under the size limit still pictures lose quality, and animated
GIFs lose colours and then every second (third...) frame, while the frames that stay last twice as long, so the
motion keeps its speed.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageSequence

WIDTH = 512
LIMIT = 1_000_000


def _gif_bytes(frames, durations, colors, loop) -> bytes:
    out = [f.convert("RGB").quantize(colors, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
           for f in frames]
    buf = io.BytesIO()
    out[0].save(buf, "GIF", save_all=True, append_images=out[1:], duration=durations, loop=loop, optimize=True,
                disposal=2)
    return buf.getvalue()


def _resized(im: Image.Image, width: int) -> Image.Image:
    """Centered 1:1 crop, then ``width`` x ``width``."""
    w, h = im.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    im = im.crop((left, top, left + side, top + side)) if w != h else im
    return im if side == width else im.resize((width, width), Image.LANCZOS)


def _animated(im: Image.Image, width: int, limit: int) -> bytes:
    frames, durations = [], []
    for fr in ImageSequence.Iterator(im):
        frames.append(_resized(fr.convert("RGBA"), width))
        durations.append(max(20, int(fr.info.get("duration", 80))))
    loop = im.info.get("loop", 0)
    stride, best = 1, b""
    while True:
        kept = frames[::stride]
        dur = [sum(durations[i:i + stride]) for i in range(0, len(frames), stride)]
        for colors in (128, 48):
            best = _gif_bytes(kept, dur, colors, loop)
            if len(best) <= limit:
                return best
        if len(kept) <= 8:
            return best
        # frames are about equally big, so jump straight to the stride that should fit, then fine-tune
        stride = max(stride + 1, int(stride * len(best) / limit * 0.9) + 1)


def _still(im: Image.Image, width: int, limit: int) -> tuple[bytes, str]:
    alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
    pic = _resized(im.convert("RGBA" if alpha else "RGB"), width)
    for q in (90, 82, 74, 66, 58, 50, 40):
        buf = io.BytesIO()
        if alpha:
            pic.save(buf, "WEBP", quality=q, method=4)
            ext = "webp"
        else:
            pic.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
            ext = "jpg"
        if len(buf.getvalue()) <= limit:
            break
    return buf.getvalue(), ext


def prepare(src: Path, dest: Path, width: int = WIDTH, limit: int = LIMIT) -> Path:
    """Write the sendable copy of ``src`` next to ``dest`` (same name; the suffix changes when the format does: a
    PNG becomes a JPEG, or a WebP if it has see-through parts). Returns the file written."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        if getattr(im, "n_frames", 1) > 1 and im.format == "GIF":
            data, out = _animated(im, width, limit), dest.with_suffix(".gif")
        else:
            data, ext = _still(im, width, limit)
            out = dest.with_suffix("." + ext)
    tmp = out.with_suffix(out.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(out)
    return out


def name_of(f: Path, src: Path, files) -> Path:
    """The output name. Two pictures with one name in different formats (pout.jpg, pout.png) keep their format in it."""
    rel = f.relative_to(src)
    twins = [g for g in files if g.parent == f.parent and g.stem.lower() == f.stem.lower()]
    return rel.with_name(f"{f.stem}-{f.suffix.lstrip('.').lower()}") if len(twins) > 1 else rel


def _one(args):
    f, rel, dest, limit = args
    out = prepare(f, dest / rel, limit=limit)
    return rel, f.stat().st_size, out.name, out.stat().st_size


def main() -> None:
    import sys
    from concurrent.futures import ProcessPoolExecutor
    if len(sys.argv) not in (3, 4):
        sys.exit(__doc__)
    src, dest = Path(sys.argv[1]), Path(sys.argv[2])
    limit = int(sys.argv[3]) * 1000 if len(sys.argv) == 4 else LIMIT
    files = sorted(p for p in src.rglob("*") if p.is_file() and p.suffix.lower() in (".gif", ".png", ".jpg", ".jpeg", ".webp"))
    total_in = total_out = 0
    with ProcessPoolExecutor() as pool:
        for rel, before, name, after in pool.map(_one, [(f, name_of(f, src, files), dest, limit) for f in files]):
            total_in += before
            total_out += after
            print(f"{rel}: {before // 1000} KB -> {name} {after // 1000} KB", flush=True)
    print(f"done: {total_in // 1000000} MB -> {total_out // 1000000} MB", flush=True)


if __name__ == "__main__":
    main()
