"""Sentence splitting with NLTK's Punkt model.

Punkt knows that "Mr. Smith", "e.g." and "3.5" don't end a sentence, which a punctuation regex can't. The model
(``punkt_tab``) is a small data package: :func:`ensure_punkt` downloads it once. If it can't be had (offline, a
locked-down host) we log it and fall back to a punctuation split, so a reply is never lost over this.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Callable, List, Optional

log = logging.getLogger("kitsune.text")

_FALLBACK = re.compile(r"(?<=[.!?…])\s+")
_lock = threading.Lock()
_tokenize: Optional[Callable[[str], List[str]]] = None


def _punkt() -> Callable[[str], List[str]]:
    """Return NLTK's English sentence tokenizer, downloading ``punkt_tab`` on first use."""
    import nltk
    from nltk.tokenize import sent_tokenize

    def run(text: str) -> List[str]:
        return sent_tokenize(text, language="english")

    try:
        run("Test. Test.")
    except LookupError:
        if not nltk.download("punkt_tab", quiet=True):
            raise
        run("Test. Test.")
    return run


def ensure_punkt() -> bool:
    """Load the sentence model now (call at startup so the first reply doesn't wait on a download)."""
    global _tokenize
    with _lock:
        if _tokenize is not None:
            return _tokenize is not _fallback
        try:
            _tokenize = _punkt()
            return True
        except Exception as e:  # LookupError, no network, nltk missing, ...
            log.warning("NLTK sentence model unavailable (%s: %s); splitting on punctuation", type(e).__name__, e)
            _tokenize = _fallback
            return False


def _fallback(text: str) -> List[str]:
    return _FALLBACK.split(text)


def sentences(text: str) -> List[str]:
    """Split ``text`` into sentences. Line breaks always end a sentence (the model writes one thought per line)."""
    ensure_punkt()
    assert _tokenize is not None
    out: List[str] = []
    for line in re.split(r"\n+", text.strip()):
        line = line.strip()
        if line:
            out.extend(s.strip() for s in _tokenize(line) if s.strip())
    return out
