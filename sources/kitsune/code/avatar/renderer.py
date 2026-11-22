"""Neku's video pipeline, ported (``FGKBot.avatar_waifu`` and helpers in ``fgk_neku.py``).

Neku:
1. got ``[{"text", "audio"}]`` segments from Inworld,
2. ``merge_base64_mp3s_sox``: wrote each segment, timed it with ffprobe, built SRT entries, joined them with sox,
3. ``audio_analysis``: volume class per 1/16 s,
4. ``create_grid_video``: ``grid[class][i % 32]`` frames with OpenCV, then muxed the audio with ffmpeg,
5. ``add_vid_subs``: burned ``subs.srt`` in with ffmpeg's ``subtitles`` filter,
6. replied with just the video.

Improvements:
* every render gets its own temp directory (Neku shared ``crockpot/`` and ``rm crockpot/*``, so two users talking at
  once overwrote each other's files),
* steps 4 and 5 are one ffmpeg pass (frames piped in, audio muxed, subtitles burned): one encode instead of three,
  and no OpenCV,
* segments are joined with sox when it's installed, otherwise with ffmpeg,
* subtitles have a readable style for phones, and everything runs off the event loop.
"""

from __future__ import annotations

import asyncio
import os
import random
import shutil
import subprocess
import tempfile
from datetime import timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from ..errors import RenderError
from ..moods import Mood
from .lipsync import FPS, SMOOTH_FPS, audio_analysis, blink_track, load_audio, mouth_track
from .sprites import LOOP, SpriteBank
from .subtitles import SrtEntry, escape_filter_path, get_duration_ffprobe, write_srt_file

#: libass style for the burned-in subtitles (sizes are in a 288-line script space, so they scale with the video)
SUBTITLE_STYLE = (
    "FontName=DejaVu Sans,FontSize=17,Bold=0,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
    "BackColour=&H80000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=16"
)

Segment = Dict[str, bytes | str]  # {"text": str, "audio": bytes}: what Inworld gave Neku


def _run(cmd: List[str]) -> None:
    try:
        p = subprocess.run(cmd, capture_output=True)
    except FileNotFoundError as e:
        raise RenderError(f"{cmd[0]} is not installed") from e
    if p.returncode != 0:
        raise RenderError(f"{cmd[0]} failed: {p.stderr.decode(errors='replace')[-400:]}")


def merge_mp3s(segments: Sequence[Segment], output_file: str, srt_file_path: str, tmp_dir: str) -> List[SrtEntry]:
    """Neku's ``merge_base64_mp3s_sox``: one file per segment, ffprobe-timed SRT, joined into ``output_file``."""
    paths: List[str] = []
    entries: List[SrtEntry] = []
    current_time = timedelta()
    for i, seg in enumerate(segments):
        path = os.path.join(tmp_dir, f"segment_{i}.mp3")
        with open(path, "wb") as f:
            f.write(seg["audio"])  # type: ignore[arg-type]
        paths.append(path)
        end_time = current_time + timedelta(seconds=get_duration_ffprobe(path))
        entries.append((i + 1, current_time, end_time, str(seg["text"])))
        current_time = end_time
    if len(paths) == 1:
        _run(["ffmpeg", "-v", "error", "-y", "-i", paths[0], output_file])
    elif shutil.which("sox"):
        _run(["sox", *paths, output_file])
    else:
        inputs = [arg for p in paths for arg in ("-i", p)]
        graph = "".join(f"[{i}:a]" for i in range(len(paths))) + f"concat=n={len(paths)}:v=0:a=1[a]"
        _run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-map", "[a]", output_file])
    write_srt_file(entries, srt_file_path)
    return entries


class AvatarRenderer:
    def __init__(
        self,
        sprites: SpriteBank,
        *,
        crf: int = 23,
        preset: str = "veryfast",
        subtitle_style: str = SUBTITLE_STYLE,
        thresholds: Optional[Tuple[float, float]] = None,
        lipsync: str = "smooth",
    ) -> None:
        self.sprites = sprites
        self.crf = crf
        self.preset = preset
        self.subtitle_style = subtitle_style
        self.thresholds = thresholds
        self.lipsync = lipsync  # "smooth" (24 fps open/closed + random blinks) or "neku" (16 fps, 3 classes)

    def frames_for(self, y, mood: Mood, seed: Optional[int] = None) -> Tuple[list, int]:
        """The frame list and fps for a voice track, by lip-sync style."""
        if self.lipsync == "neku":
            grid = self.sprites.grid(mood)
            return [grid[a][i % LOOP] for i, a in enumerate(audio_analysis(y, thresholds=self.thresholds))], FPS
        f = self.sprites.frames(mood)
        mouth = mouth_track(y)
        blinks = blink_track(len(mouth), rng=random.Random(seed))
        return [f[f"{'blink' if b else 'open'}_{'talk' if m else 'closed'}"] for m, b in zip(mouth, blinks)], SMOOTH_FPS

    def create_grid_video(
        self, frames: Sequence, fps: int, audio_file: str, output_file: str, srt_file: Optional[str] = None
    ) -> None:
        """Neku's ``create_grid_video`` + audio mux + ``add_vid_subs``, in one ffmpeg pass."""
        size = frames[0].shape[1]
        vf: List[str] = []
        if srt_file:
            style = f":force_style='{self.subtitle_style}'" if self.subtitle_style else ""
            vf = ["-vf", f"subtitles='{escape_filter_path(srt_file)}'{style}"]
        cmd = [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{size}x{size}",
            "-r",
            str(fps),
            "-i",
            "pipe:0",
            "-i",
            audio_file,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            *vf,
            "-c:v",
            "libx264",
            "-preset",
            self.preset,
            "-crf",
            str(self.crf),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-shortest",
            "-movflags",
            "+faststart",
            output_file,
        ]
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError as e:
            raise RenderError("ffmpeg is not installed") from e
        assert proc.stdin is not None and proc.stderr is not None
        try:
            for frame in frames:
                proc.stdin.write(frame.tobytes())
            proc.stdin.close()
        except BrokenPipeError:
            pass
        err = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0:
            raise RenderError(f"ffmpeg failed: {err[-400:]}")

    def avatar_video(self, segments: Sequence[Segment], mood: Mood, *, subtitles: bool = True) -> bytes:
        """The video half of Neku's ``avatar_waifu``: segments in, finished MP4 bytes out."""
        if not segments:
            raise RenderError("nothing to say")
        with tempfile.TemporaryDirectory(prefix="kitsune-") as crockpot:
            merged = os.path.join(crockpot, "merged.wav")
            srt = os.path.join(crockpot, "subs.srt")
            merge_mp3s(segments, merged, srt, crockpot)
            with open(merged, "rb") as f:
                frames, fps = self.frames_for(load_audio(f.read()), mood)
            out = os.path.join(crockpot, "kitsune.mp4")
            self.create_grid_video(frames, fps, merged, out, srt if subtitles else None)
            with open(out, "rb") as f:
                return f.read()

    async def avatar_video_async(self, segments: Sequence[Segment], mood: Mood, *, subtitles: bool = True) -> bytes:
        return await asyncio.to_thread(self.avatar_video, segments, mood, subtitles=subtitles)
