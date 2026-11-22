"""Ollama chat (a local server, or https://ollama.com with an API key)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from ...errors import ChatError
from .base import ChatMessage


class OllamaChat:
    def __init__(
        self,
        host: str,
        model: str,
        *,
        api_key: str = "",
        options: Optional[Dict[str, Any]] = None,
        timeout: float = 120.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.options = options or {}
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.AsyncClient(base_url=self.host, timeout=timeout, headers=headers, transport=transport)

    async def chat(self, messages: List[ChatMessage]) -> str:
        body: Dict[str, Any] = {"model": self.model, "messages": messages, "stream": False}
        if self.options:
            body["options"] = self.options
        try:
            r = await self._http.post("/api/chat", json=body)
        except httpx.HTTPError as e:
            raise ChatError(f"can't reach Ollama at {self.host}: {e}") from e
        if r.status_code != 200:
            raise ChatError(f"Ollama returned {r.status_code}: {r.text[:200]}")
        return str((r.json().get("message") or {}).get("content", "")).strip()

    async def aclose(self) -> None:
        await self._http.aclose()
