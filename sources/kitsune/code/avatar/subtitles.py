"""Neku's subtitle helpers: ffprobe durations, SRT timestamps and the SRT writer."""

from __future__ import annotations

import json
import subprocess
from datetime import timedelta
from typing import Iterable, List, Tuple

from ..errors import RenderError
from ..text import sentences

SrtEntry = Tuple[int, timedelta, timedelta, str]  # (index, start, end, text), as Neku built them


def split_lines(text: str, max_chars: int = 80) -> List[str]:
    """Split a reply into spoken lines (Inworld delivered sentences this way): NLTK sentences, long ones broken up."""
    lines: List[str] = []
    for sentence in sentences(text):
        while len(sentence) > max_chars:
            cut = max(sentence.rfind(", ", 0, max_chars), sentence.rfind(" ", 0, max_chars))
            cut = cut if cut > max_chars // 3 else max_chars
            lines.append(sentence[: cut + 1].strip())
            sentence = sentence[cut + 1 :].strip()
        if sentence:
            lines.append(sentence)
    return lines


def get_duration_ffprobe(path: str) -> float:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path]
        )
        return float(json.loads(out)["format"]["duration"])
    except (subprocess.CalledProcessError, KeyError, ValueError, FileNotFoundError) as e:
        raise RenderError(f"ffprobe couldn't read {path}: {e}") from e


def format_timedelta(td: timedelta) -> str:
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = td.microseconds // 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def srt_text(entries: Iterable[SrtEntry]) -> str:
    return "".join(f"{i}\n{format_timedelta(a)} --> {format_timedelta(b)}\n{text}\n\n" for i, a, b, text in entries)


def write_srt_file(entries: Iterable[SrtEntry], srt_file_path: str) -> None:
    with open(srt_file_path, "w", encoding="utf-8") as f:
        f.write(srt_text(entries))


def escape_filter_path(path: str) -> str:
    """Quote a path for ffmpeg's ``subtitles=`` filter."""
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
