"""NovelAI text-to-speech (TTS v2)."""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx

from ...errors import SpeechError

API = "https://text.novelai.net"  # TTS moved here from api.novelai.net on 2026-11-20
MAX_CHARS = 1000  # NovelAI cuts longer text server-side


class NovelAISpeech:
    def __init__(
        self,
        token: str,
        *,
        voice_seed: str = "Aurae",
        timeout: float = 120.0,
        retries: int = 3,
        backoff: float = 1.0,
        max_concurrent: int = 2,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        if not token:
            raise SpeechError("a NovelAI token is required for speech")
        self.voice_seed = voice_seed
        self.retries = max(1, retries)
        self.backoff = backoff
        self._slots = asyncio.Semaphore(max_concurrent)  # NovelAI errors out on bursts of parallel requests
        self._http = httpx.AsyncClient(
            base_url=API, timeout=timeout, transport=transport, headers={"Authorization": f"Bearer {token}"}
        )

    async def synthesize(self, text: str) -> bytes:
        body = {"text": text[:MAX_CHARS], "seed": self.voice_seed, "voice": -1, "opus": False, "version": "v2"}
        last = ""
        async with self._slots:
            for attempt in range(self.retries):
                if attempt:
                    await asyncio.sleep(self.backoff * 2 ** (attempt - 1))
                try:
                    r = await self._http.post("/ai/generate-voice", json=body)
                except httpx.HTTPError as e:
                    last = f"can't reach NovelAI: {e}"
                    continue
                if r.status_code < 400:
                    return r.content
                last = f"NovelAI TTS returned {r.status_code}: {r.text[:200]}"
                if r.status_code not in (429, 500, 502, 503, 504):
                    break  # auth / bad request: retrying won't help
        raise SpeechError(last)

    async def aclose(self) -> None:
        await self._http.aclose()
