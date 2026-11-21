"""Vectoria's voice and face: SAM speaks each line, her sprite lip-syncs to it, then a VHS pass and C64 subtitles.

Ported from the standalone Vectoria bot (itself a port of Neku's ``avatar_waifu``), without numpy or NLTK: everything
here is Pillow (already part of Vectiq), the standard library, ffmpeg and SAM.

SAM (https://github.com/s-macke/SAM) has no licence file, so it is never bundled: :func:`build_sam` clones and
compiles it on the bot's computer when an owner asks (``!vecvoice`` or the dashboard), like Vectoria's installer did.
"""

from __future__ import annotations

import base64
import io
import json
import math
import os
import random
import re
import shutil
import subprocess
import tempfile
from array import array
from datetime import timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
FRAME_NAMES = ("open_closed", "open_talk", "blink_closed", "blink_talk")
SAMPLE_RATE = 22050
FPS = 24
AUDIO_KBPS = 40  # SAM is 22 kHz mono: it needs very little
SAM_REPO = "https://github.com/s-macke/SAM"

#: libass style for the burned-in subtitles: pale phosphor green on a black outline, like a C64 screen
SUBTITLE_STYLE = (
    "FontName=Press Start 2P,FontSize=12,Bold=0,PrimaryColour=&H00C8FFD2,OutlineColour=&H00000000,"
    "BackColour=&H80000000,BorderStyle=1,Outline=1.2,Shadow=0,Alignment=2,MarginV=12,Spacing=0.3"
)


class RenderError(Exception):
    """The voice or the video couldn't be made (the reply falls back to text)."""


def _run(cmd: list, **kw) -> subprocess.CompletedProcess:
    try:
        p = subprocess.run(cmd, capture_output=True, **kw)
    except FileNotFoundError as e:
        raise RenderError(f"{cmd[0]} is not installed") from e
    except subprocess.TimeoutExpired as e:
        raise RenderError(f"{cmd[0]} took too long") from e
    if p.returncode != 0:
        raise RenderError(f"{Path(cmd[0]).name} failed: {p.stderr.decode(errors='replace')[-400:]}")
    return p


# -- text -----------------------------------------------------------------------------------------------------------
_SENTENCE = re.compile(r"(?<=[.!?…])\s+")
_ABBREV = re.compile(r"(\b(e\.g|i\.e|etc|vs|mr|mrs|ms|dr|st|no|approx)\.|\b[A-Za-z]\.)$", re.I)


def sentences(text: str) -> list:
    """Sentences, one thought per line: a line break always ends one. "e.g.", "Mr." and the like don't."""
    out = []
    for line in re.split(r"\n+", text.strip()):
        parts = []
        for piece in _SENTENCE.split(line.strip()):
            if parts and _ABBREV.search(parts[-1]):
                parts[-1] += " " + piece
            elif piece.strip():
                parts.append(piece.strip())
        out += parts
    return out


def trim_spoken(text: str, max_sentences: int = 3, max_chars: int = 240) -> str:
    """Short enough for a short video: the first sentences, within ``max_chars``."""
    out, used = [], 0
    for s in sentences(text):
        if len(out) >= max_sentences or (out and used + len(s) > max_chars):
            break
        out.append(s)
        used += len(s) + 1
    spoken = " ".join(out) or text.strip()
    if len(spoken) > max_chars:
        cut = max(spoken.rfind(", ", 0, max_chars), spoken.rfind(" ", 0, max_chars))
        spoken = spoken[: cut if cut > max_chars // 3 else max_chars].rstrip(" ,;:") + "."
    return spoken


def split_lines(text: str, max_chars: int = 80) -> list:
    """Spoken lines (one subtitle each): sentences, with long ones broken at a comma or a space."""
    lines = []
    for s in sentences(text):
        while len(s) > max_chars:
            cut = max(s.rfind(", ", 0, max_chars), s.rfind(" ", 0, max_chars))
            cut = cut if cut > max_chars // 3 else max_chars
            lines.append(s[: cut + 1].strip())
            s = s[cut + 1:].strip()
        if s:
            lines.append(s)
    return lines


# -- the voice: SAM -------------------------------------------------------------------------------------------------
_SAY = [
    (r"```.*?```", " "), (r"https?://\S+", "link"), (r"`+", ""), (r"[*_#>~|]+", ""),
    (r"\bwebxdc\b", "web ex dee cee"), (r"\bxdc\b", "ex dee cee"), (r"\bnpub\b", "en pub"), (r"\bnsec\b", "en sec"),
    (r"\bsdk\b", "ess dee kay"), (r"\bapi\b", "ay pee eye"), (r"\bjs\b", "jay ess"), (r"\bnostr\b", "nostur"),
    (r"&", " and "), (r"@", " at "), (r"%", " percent "), (r"\+", " plus "), (r"=+", " equals "), (r"[/\\]", " "),
    (r"[‘’]", "'"), (r"[“”]", '"'), (r"[–—]", ", "), (r"…", "..."),
]


def sayable(text: str, limit: int = 250) -> str:
    """SAM reads plain ASCII only, 254 characters at most."""
    for pattern, repl in _SAY:
        text = re.sub(pattern, repl, text, flags=re.I | re.S)
    text = re.sub(r"[^A-Za-z0-9 .,?!'\-:;]", " ", text.encode("ascii", "ignore").decode("ascii"))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        cut = max(text.rfind(". ", 0, limit), text.rfind(", ", 0, limit), text.rfind(" ", 0, limit))
        text = text[: cut if cut > limit // 3 else limit].rstrip(" ,;:")
    return text


def sam_home(data_dir: str) -> Path:
    return Path(data_dir) / "vectoria" / "SAM"


def find_sam(configured: str, data_dir: str) -> str | None:
    """The SAM binary: the configured path, the one built in the data folder, ``$SAM_BIN``, or ``sam`` on PATH."""
    for c in (configured, str(sam_home(data_dir) / "sam"), os.environ.get("SAM_BIN", "")):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return shutil.which("sam")


def build_sam(data_dir: str) -> str:
    """Blocking: clone SAM and compile it into ``<data>/vectoria/SAM/sam`` (needs git and a C compiler)."""
    home = sam_home(data_dir)
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        raise RenderError("no C compiler (on a Mac: xcode-select --install; on Linux: install gcc)")
    if (home / ".git").is_dir():
        subprocess.run(["git", "-C", str(home), "pull", "--ff-only", "-q"], capture_output=True, timeout=120)
    else:
        shutil.rmtree(home, ignore_errors=True)
        home.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "-q", "--depth", "1", SAM_REPO, str(home)], timeout=180)
    sources = sorted(str(p) for p in (home / "src").glob("*.c"))
    # -fcommon: SAM defines globals in headers; modern compilers default to -fno-common. No SDL needed for -wav.
    _run([cc, "-O2", "-fcommon", "-w", "-o", str(home / "sam"), *sources], timeout=300)
    speak(str(home / "sam"), "Vectoria is alive.", {})
    return str(home / "sam")


def speak(binary: str, text: str, voice: dict) -> bytes:
    """Blocking: one line through SAM, as 8-bit mono 22050 Hz WAV bytes."""
    said = sayable(text)
    if not any(ch.isalnum() for ch in said):
        raise RenderError(f"nothing speakable in {text!r}")
    with tempfile.TemporaryDirectory(prefix="vectoria-sam-") as d:
        out = os.path.join(d, "line.wav")
        _run([binary, "-pitch", str(voice.get("pitch", 40)), "-speed", str(voice.get("speed", 72)),
              "-mouth", str(voice.get("mouth", 150)), "-throat", str(voice.get("throat", 155)), "-wav", out, said],
             timeout=30)
        if not os.path.isfile(out) or os.path.getsize(out) < 100:
            raise RenderError("SAM made no sound")
        return Path(out).read_bytes()


# -- lip-sync ---------------------------------------------------------------------------------------------------------
def load_audio(path: str) -> array:
    """Any audio ffmpeg reads -> mono 16-bit samples at 22050 Hz."""
    p = _run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1"])
    samples = array("h")
    samples.frombytes(p.stdout[: len(p.stdout) // 2 * 2])
    return samples


def frame_rms(samples: array, fps: int = FPS) -> list:
    step = int(SAMPLE_RATE / fps)
    out = []
    for i in range(0, max(1, len(samples)), step):
        chunk = samples[i:i + step]
        out.append(math.sqrt(sum(x * x for x in chunk) / step) / 32768.0 if chunk else 0.0)
    return out


def mouth_track(samples: array, fps: int = FPS, *, hold: int = 2, flap_every: int = 7,
                sensitivity: float = 0.35, floor: float = 0.003) -> list:
    """Mouth open where the voice is loud relative to its own peaks; held a little, and flapping in long runs."""
    rms = frame_rms(samples, fps)
    peak = sorted(rms)[int(0.9 * (len(rms) - 1))] if rms else 0.0
    out, run = [], 0
    for level in rms:
        want = level > max(floor, peak * sensitivity)
        if out and want != out[-1] and run < hold:
            want = out[-1]
        run = run + 1 if out and want == out[-1] else 1
        out.append(want)
    open_run = 0
    for i, is_open in enumerate(out):
        open_run = open_run + 1 if is_open else 0
        if open_run and open_run % flap_every == 0:
            out[i] = False
    return out


def blink_track(frames: int, fps: int = FPS, rng: random.Random | None = None) -> list:
    rng = rng or random.Random()
    out = [False] * frames
    t = int(rng.uniform(1.0, 2.5) * fps)
    while t < frames:
        for i in range(t, min(frames, t + 3)):
            out[i] = True
        t += int(rng.uniform(2.5, 5.0) * fps)
    return out


# -- her face --------------------------------------------------------------------------------------------------------
_ASSETS: dict = {}


def assets() -> dict:
    if not _ASSETS:
        _ASSETS.update(json.loads((HERE / "assets.json").read_text(encoding="utf-8")))
    return _ASSETS


def font_dir(data_dir: str) -> str:
    """Press Start 2P (SIL OFL, unmodified, with its licence), written next to her other files once."""
    d = Path(data_dir) / "vectoria" / "fonts"
    ttf = d / "PressStart2P-Regular.ttf"
    if not ttf.is_file():
        d.mkdir(parents=True, exist_ok=True)
        ttf.write_bytes(base64.b64decode(assets()["font"]))
        shutil.copyfile(HERE / "OFL.txt", d / "OFL.txt")
    return str(d)


def backdrop(size: int) -> Image.Image:
    """A dark backdrop with a soft green glow behind her."""
    bg = Image.new("RGB", (size, size), (10, 14, 13))
    glow = Image.new("L", (size, size), 0)
    ImageDraw.Draw(glow).ellipse((-size * 0.15, size * 0.1, size * 1.15, size * 1.25), fill=140)
    glow = glow.filter(ImageFilter.GaussianBlur(max(1, size // 5)))
    return Image.composite(Image.new("RGB", (size, size), (16, 70, 40)), bg, glow)


_FRAMES: dict = {}


def frames(size: int, vhs: bool, strength: float) -> dict:
    """The four sprite frames composited at ``size`` (raw RGB bytes), with the still VHS look baked in once."""
    key = (size, vhs, round(strength, 2))
    if key not in _FRAMES:
        bg = backdrop(size).convert("RGBA")
        out = {}
        for name in FRAME_NAMES:
            sprite = Image.open(io.BytesIO(base64.b64decode(assets()["sprites"][name]))).convert("RGBA")
            canvas = bg.copy()
            canvas.alpha_composite(sprite.resize((size, size), Image.LANCZOS))
            raw = canvas.convert("RGB").tobytes()
            out[name] = style_frame(raw, size, strength) if vhs and strength > 0 else raw
        _FRAMES.clear()  # only one size is in use at a time
        _FRAMES[key] = out
    return _FRAMES[key]


def still_png(size: int = 512) -> bytes:
    bg = backdrop(size).convert("RGBA")
    sprite = Image.open(io.BytesIO(base64.b64decode(assets()["sprites"]["open_closed"]))).convert("RGBA")
    bg.alpha_composite(sprite.resize((size, size), Image.LANCZOS))
    buf = io.BytesIO()
    bg.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


# -- the VHS look ----------------------------------------------------------------------------------------------------
def rate_args(duration: float, max_kb: int, crf: int = 31) -> list:
    """x264 settings that keep the whole file under ``max_kb`` (0 = quality target only)."""
    if max_kb <= 0 or duration <= 0:
        return ["-crf", str(crf)]
    kbps = max(30, int(max_kb * 8 / duration - AUDIO_KBPS * 1.05))
    return ["-crf", str(crf), "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k"]


def style_frame(raw: bytes, size: int, strength: float) -> bytes:
    """The still part of the VHS look on one frame: soft blur, colour bleed, RGB shift, scanlines, vignette."""
    s = max(0.0, min(strength, 2.0))
    shift, chroma = max(1, round(size / 170 * s)), max(1, round(size / 128 * s))
    period, thick = max(4, round(size / 85)), max(2, round(size / 170))
    dark = round(255 * (1 - 0.32 * min(s, 1.5)))
    mask = Image.new("L", (size, size), 255)
    draw = ImageDraw.Draw(mask)
    for y in range(0, size, period):
        draw.rectangle((0, y, size, y + thick - 1), fill=dark)
    graph = (f"[0:v]gblur=sigma={0.5 + 0.5 * min(s, 1.5):.2f}:steps=1,format=yuv444p,"
             f"chromashift=crh={chroma}:cbh=-{chroma},format=gbrp,rgbashift=rh=-{shift}:bh={shift}[c];"
             "[c][1:v]blend=all_mode=multiply,vignette=angle=PI/5,"
             "eq=contrast=1.08:saturation=1.18:brightness=0.01,format=rgb24[v]")
    with tempfile.TemporaryDirectory(prefix="vectoria-style-") as d:
        mask_path = os.path.join(d, "scan.png")
        mask.save(mask_path)
        p = _run(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size}x{size}",
                  "-i", "pipe:0", "-loop", "1", "-i", mask_path, "-filter_complex", graph, "-map", "[v]",
                  "-frames:v", "1", "-f", "rawvideo", "pipe:1"], input=raw)
    if len(p.stdout) != size * size * 3:
        raise RenderError("the VHS look couldn't be applied")
    return p.stdout


def moving_graph(size: int, strength: float, subtitles: str | None) -> str:
    """What moves, in the encoding pass: a tracking band that drifts and tears, tape noise, then the subtitles."""
    s = max(0.0, min(strength, 2.0))
    band = round(size * 0.05)
    amp = round(size / 70 * s)
    top = f"clip(mod(t*{size * 0.27:.1f}\\,{size + band})-{band}\\,0\\,{size - band})"
    return ";".join([
        "[0:v]split[a][b]",
        f"[b]crop=iw:{band}:0:'{top}'[band]",
        f"[a][band]overlay=x='{amp}*sin(t*37)':y='{top}':eval=frame,format=yuv420p,noise=alls={round(9 * s)}:allf=t+u"
        + (f",{subtitles}" if subtitles else "") + "[v]",
    ])


def _escape(path: str) -> str:
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _srt_time(t: timedelta) -> str:
    total = int(t.total_seconds())
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d},{t.microseconds // 1000:03d}"


def duration(path: str) -> float:
    p = _run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path])
    try:
        return float(json.loads(p.stdout)["format"]["duration"])
    except (KeyError, ValueError) as e:
        raise RenderError(f"ffprobe couldn't time {path}") from e


# -- the clip ---------------------------------------------------------------------------------------------------------
def ready(sam: str | None) -> str:
    """Why a video can't be made right now ("" when it can)."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        return "ffmpeg isn't installed on the bot's computer"
    if not sam:
        return "her voice (SAM) isn't built yet"
    return ""


def render(text: str, *, sam: str, data_dir: str, opts: dict) -> bytes:
    """Blocking: the finished MP4 for ``text`` (already short)."""
    size = max(128, min(int(opts.get("video_size", 512)), 512)) // 2 * 2
    vhs, strength = bool(opts.get("vhs", True)), float(opts.get("vhs_strength", 1.0))
    lines = split_lines(text) or [text]
    with tempfile.TemporaryDirectory(prefix="vectoria-") as d:
        paths, srt, t = [], [], timedelta()
        for i, line in enumerate(lines):
            if not any(ch.isalnum() for ch in sayable(line)):
                continue
            path = os.path.join(d, f"line{i}.wav")
            Path(path).write_bytes(speak(sam, line, opts))
            end = t + timedelta(seconds=duration(path))
            srt.append(f"{len(srt) + 1}\n{_srt_time(t)} --> {_srt_time(end)}\n{line.upper()}\n")
            paths.append(path)
            t = end
        if not paths:
            raise RenderError("nothing to say")
        voice = os.path.join(d, "voice.wav")
        inputs = [a for p in paths for a in ("-i", p)]
        join = "".join(f"[{i}:a]" for i in range(len(paths))) + f"concat=n={len(paths)}:v=0:a=1[a]"
        _run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", join, "-map", "[a]", voice])
        subs_path = os.path.join(d, "subs.srt")
        Path(subs_path).write_text("\n".join(srt), encoding="utf-8")

        mouth = mouth_track(load_audio(voice))
        blinks = blink_track(len(mouth))
        faces = frames(size, vhs, strength)
        seq = [faces[f"{'blink' if b else 'open'}_{'talk' if m else 'closed'}"] for m, b in zip(mouth, blinks)]

        subs = None
        if opts.get("subtitles", True):
            subs = (f"subtitles='{_escape(subs_path)}':fontsdir='{_escape(font_dir(data_dir))}'"
                    f":force_style='{SUBTITLE_STYLE}'")
        if vhs and strength > 0:
            maps = ["-filter_complex", moving_graph(size, strength, subs), "-map", "[v]", "-map", "1:a:0",
                    "-af", "highpass=f=90,lowpass=f=6500,acompressor=threshold=0.25:ratio=3,volume=1.4"]
        else:
            maps = ["-map", "0:v:0", "-map", "1:a:0", *(["-vf", subs] if subs else [])]
        out = os.path.join(d, "vectoria.mp4")
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size}x{size}",
               "-r", str(FPS), "-i", "pipe:0", "-i", voice, *maps, "-c:v", "libx264", "-preset", "veryfast",
               *rate_args(duration(voice), int(opts.get("max_kb", 450))), "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-ac", "1", "-b:a", f"{AUDIO_KBPS}k", "-shortest", "-movflags", "+faststart", out]
        _run(cmd, input=b"".join(seq), timeout=300)
        return Path(out).read_bytes()
