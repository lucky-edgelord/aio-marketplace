"""Vectoria's mind: an Ollama model with web search and fetch, her notes, and a memory of each person.

Ported from the standalone Vectoria bot. Only the standard library is used (urllib, sqlite3), so the module needs
nothing installed beyond Vectiq itself.

Context: every person has their own conversation with her, shared by both modes. The model sees her persona, the
instructions for the mode (text or video), what she remembers about the person, and their recent turns. After
``compact_after`` exchanges the older ones are summarised into that memory in the background.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
log = logging.getLogger("vectiq.vectoria")

MODES = {
    "video": (
        "How you answer now: your reply is spoken aloud by a retro synthesizer voice and shown as subtitles in a "
        "short video, so keep it SHORT: two plain sentences, three at the very most, under about 40 words in total. "
        "No markdown, no lists, no emoji, no code blocks, no stage directions. Spell out the key idea in words, for "
        "example say \"call sendUpdate with a payload\" instead of reading code. If someone needs actual code, say "
        "in a sentence what it does and tell them to ask with {prefix}vec for the snippet as text."
    ),
    "text": (
        "How you answer now: your reply is posted as a chat message. Be clear and to the point: usually a few "
        "sentences, at most about 150 words unless they ask for more. Markdown is fine, and put code in fenced code "
        "blocks, short and correct. No stage directions."
    ),
}

COMPACT_PROMPT = """You maintain Vectoria's long-term memory of one person she chats with.
Rewrite the memory below so it also covers the new conversation. Keep: the person's name and how they like to be
addressed, what they are building (bots, Mini Apps, languages, SDKs), their skill level, problems they hit and
how they were solved, promises Vectoria made, and anything unresolved. Drop small talk. Write in third person
about "{name}", as short notes, at most 150 words. Reply with the memory only.

Current memory:
{summary}

New conversation:
{transcript}"""

TOOLS = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Search the web for current information, docs, GitHub repos or API references.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "web_fetch",
        "description": "Fetch one web page by URL and return its text (use after web_search, or for a given link).",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
]

_THINK = re.compile(r"<think>.*?</think>", re.S)


class ChatError(Exception):
    """The model couldn't be reached or answered with an error."""


def post_json(url: str, body: dict, key: str = "", timeout: float = 180) -> dict:
    """Blocking JSON POST (urllib honours HTTPS_PROXY and the system's certificates)."""
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - the owner sets the address
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise ChatError(f"{url} returned {e.code}: {e.read()[:200].decode(errors='replace')}") from e
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise ChatError(f"can't reach {url}: {e}") from e


# -- settings -------------------------------------------------------------------------------------------------------
@dataclass
class Settings:
    host: str
    model: str
    key: str
    web: bool
    notes: bool
    compact_after: int
    keep_recent: int
    max_tool_steps: int = 4

    @classmethod
    def read(cls, cfg: dict) -> Settings:
        key_env = str(cfg.get("api_key_env") or "OLLAMA_API_KEY")
        return cls(
            host=str(cfg.get("ollama_host") or "https://ollama.com").rstrip("/"),
            model=str(cfg.get("model") or "gpt-oss:120b"),
            key=os.environ.get(key_env, ""),
            web=bool(cfg.get("web_tools", True)),
            notes=bool(cfg.get("knowledge", True)),
            compact_after=max(1, int(cfg.get("compact_after", 8))),
            keep_recent=max(0, int(cfg.get("keep_recent", 2))),
        )


# -- her notes ------------------------------------------------------------------------------------------------------
STOP = set(
    "a an and are as at be but by can do does for from has have how i if in is it its me my of on or so that the "
    "their then there this to up use using was we what when where which who why will with you your about would "
    "could should please tell explain".split()
)
WORD = re.compile(r"[A-Za-z0-9_]+")
CAMEL = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")


def _stem(w: str) -> str:
    for end in ("ing", "ed", "es", "s"):
        if w.endswith(end) and len(w) - len(end) >= 3:
            return w[: -len(end)]
    return w


def words(text: str) -> set:
    """Search words: lowercased, plurals and -ed/-ing dropped, and camelCase names also split ("sendUpdate" also
    gives "send" and "update"), so "send an update" finds the notes on sendUpdate."""
    out = set()
    for tok in WORD.findall(text):
        parts = {tok.lower(), *(p.lower() for p in CAMEL.findall(tok)), *tok.lower().split("_")}
        out |= {_stem(p) for p in parts if p and p not in STOP and len(p) > 1}
    return out


class Notes:
    """Her notes on the Vector SDKs and WebXDC (``kb_*.md``), split at ``# headings`` and found by keyword."""

    def __init__(self, folder: Path = HERE) -> None:
        self.chunks = []
        for path in sorted(folder.glob("kb_*.md")):
            for block in re.split(r"(?m)^# ", path.read_text(encoding="utf-8")):
                title, _, body = block.strip().partition("\n")
                if title:
                    self.chunks.append((title.strip(), body.strip(), words(title + " " + body), words(title)))

    def context(self, question: str, k: int = 3, max_chars: int = 3500) -> str:
        q = words(question)
        scored = sorted(((len(q & w) + 2 * len(q & tw), t, b) for t, b, w, tw in self.chunks), key=lambda s: -s[0])
        out, used = [], 0
        for score, title, body in scored[:k]:
            if score < 2:
                break
            piece = f"[{title}]\n{body}"[: max(0, max_chars - used)]
            if piece:
                out.append(piece)
                used += len(piece)
        return "\n\n".join(out)


# -- memory ---------------------------------------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
    channel TEXT, at REAL NOT NULL, compacted INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS turns_by_user ON turns (user, compacted, id);
CREATE TABLE IF NOT EXISTS memories (user TEXT PRIMARY KEY, summary TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS replies (
    message_id TEXT PRIMARY KEY, user TEXT NOT NULL, channel TEXT, prompt TEXT NOT NULL, reply TEXT NOT NULL,
    mode TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS feedback (
    message_id TEXT NOT NULL, rater TEXT NOT NULL, rating INTEGER NOT NULL, at REAL NOT NULL,
    PRIMARY KEY (message_id, rater));
"""


class Store:
    """Per-person turns and memory, plus her replies and the 👍/👎 on them. Thread-safe."""

    def __init__(self, path: str) -> None:
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def _q(self, sql: str, args: tuple = (), *, write: bool = False, many: bool = False):
        with self._lock:
            cur = self._db.executemany(sql, args) if many else self._db.execute(sql, args)
            rows = cur.fetchall()
            if write:
                self._db.commit()
            return rows, cur.rowcount

    def context(self, user: str) -> tuple[str, list]:
        memo = self._q("SELECT summary FROM memories WHERE user=?", (user,))[0]
        turns = self._q("SELECT role, content FROM turns WHERE user=? AND compacted=0 ORDER BY id", (user,))[0]
        return (memo[0][0] if memo else ""), [{"role": r, "content": c} for r, c in turns]

    def append(self, user: str, question: str, answer: str, channel: str | None) -> None:
        now = time.time()
        self._q("INSERT INTO turns (user, role, content, channel, at) VALUES (?,?,?,?,?)",
                [(user, "user", question, channel, now), (user, "assistant", answer, channel, now)],
                write=True, many=True)

    def uncompacted(self, user: str) -> list:
        rows = self._q("SELECT id, role, content FROM turns WHERE user=? AND compacted=0 ORDER BY id", (user,))[0]
        return [{"id": i, "role": r, "content": c} for i, r, c in rows]

    def compact(self, user: str, summary: str, up_to_id: int) -> int:
        n = self._q("UPDATE turns SET compacted=1 WHERE user=? AND compacted=0 AND id<=?", (user, up_to_id),
                    write=True)[1]
        self._q("INSERT INTO memories VALUES (?,?,?) ON CONFLICT(user) DO UPDATE SET summary=excluded.summary, "
                "updated_at=excluded.updated_at", (user, summary, time.time()), write=True)
        return n

    def memory(self, user: str) -> str:
        return self.context(user)[0]

    def forget(self, user: str) -> int:
        n = self._q("DELETE FROM turns WHERE user=?", (user,), write=True)[1]
        return n + self._q("DELETE FROM memories WHERE user=?", (user,), write=True)[1]

    def forget_all(self) -> None:
        self._q("DELETE FROM turns", write=True)
        self._q("DELETE FROM memories", write=True)

    def log_reply(self, message_id: str, user: str, prompt: str, reply: str, mode: str, channel: str | None) -> None:
        self._q("INSERT OR REPLACE INTO replies VALUES (?,?,?,?,?,?,?)",
                (message_id, user, channel, prompt, reply, mode, time.time()), write=True)

    def reply_mode(self, message_id: str) -> str | None:
        rows = self._q("SELECT mode FROM replies WHERE message_id=?", (message_id,))[0]
        return rows[0][0] if rows else None

    def rate(self, message_id: str, rater: str, rating: int) -> bool:
        if self.reply_mode(message_id) is None:
            return False
        self._q("INSERT OR REPLACE INTO feedback VALUES (?,?,?,?)", (message_id, rater, rating, time.time()),
                write=True)
        return True

    def unrate(self, message_id: str, rater: str, rating: int) -> None:
        self._q("DELETE FROM feedback WHERE message_id=? AND rater=? AND rating=?", (message_id, rater, rating),
                write=True)

    def stats(self) -> dict:
        one = lambda sql: self._q(sql)[0][0][0]  # noqa: E731
        return {
            "people": one("SELECT COUNT(DISTINCT user) FROM turns"),
            "text": one("SELECT COUNT(*) FROM replies WHERE mode='text'"),
            "video": one("SELECT COUNT(*) FROM replies WHERE mode='video'"),
            "up": one("SELECT COUNT(*) FROM feedback WHERE rating>0"),
            "down": one("SELECT COUNT(*) FROM feedback WHERE rating<0"),
        }

    def recent(self, n: int = 8) -> list:
        rows = self._q("SELECT r.prompt, r.mode, r.at, COALESCE(SUM(f.rating), 0) FROM replies r LEFT JOIN feedback f "
                       "USING (message_id) GROUP BY r.message_id ORDER BY r.at DESC LIMIT ?", (n,))[0]
        return [{"prompt": p, "mode": m, "at": a, "score": s} for p, m, a, s in rows]

    def close(self) -> None:
        with self._lock:
            self._db.close()


# -- thinking -------------------------------------------------------------------------------------------------------
class Brain:
    def __init__(self, store: Store, persona: str | None = None, notes: Notes | None = None) -> None:
        self.store = store
        self.persona = persona if persona is not None else (HERE / "persona.md").read_text(encoding="utf-8").strip()
        self.notes = notes if notes is not None else Notes()
        self._locks: dict = {}
        self._compacting: set = set()
        self._background: set = set()

    def lock(self, user: str) -> asyncio.Lock:
        return self._locks.setdefault(user, asyncio.Lock())

    def system_prompt(self, mode: str, name: str, memory: str, notes: str, community: str, prefix: str) -> str:
        prompt = self.persona.replace("{community}", community or "this Vector community")
        prompt += "\n\n" + MODES[mode].replace("{prefix}", prefix) + f"\n\nYou are talking with {name}."
        if notes:
            prompt += f"\n\nNotes (trusted facts relevant to this question):\n{notes}"
        if memory:
            prompt += f"\n\nWhat you remember about {name} from earlier conversations:\n{memory}"
        return prompt

    async def chat(self, s: Settings, messages: list, tools: bool) -> str:
        convo = list(messages)
        use = TOOLS if (tools and s.web and s.key) else None
        for step in range(s.max_tool_steps + 1):
            body = {"model": s.model, "messages": convo, "stream": False}
            if use and step < s.max_tool_steps:  # the last round has no tools, so she answers with what she found
                body["tools"] = use
            msg = (await asyncio.to_thread(post_json, f"{s.host}/api/chat", body, s.key)).get("message") or {}
            calls = msg.get("tool_calls") or []
            if not calls or "tools" not in body:
                return _THINK.sub("", str(msg.get("content") or "")).strip()
            convo.append({"role": "assistant", "content": msg.get("content", ""), "tool_calls": calls})
            for call in calls:
                fn = call.get("function") or {}
                convo.append({"role": "tool", "tool_name": fn.get("name", ""),
                              "content": await self.tool(s, str(fn.get("name", "")), fn.get("arguments") or {})})
        return ""

    async def tool(self, s: Settings, name: str, args) -> str:
        """Ollama's hosted web_search / web_fetch (the same API key). Failures go back to the model as text."""
        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except ValueError:
                args = {}
        try:
            if name == "web_search":
                hits = (await asyncio.to_thread(post_json, "https://ollama.com/api/web_search",
                                                {"query": str(args.get("query", "")), "max_results": 5}, s.key, 30)
                        ).get("results", [])
                return "\n\n".join(f"{h.get('title', '')}\n{h.get('url', '')}\n{str(h.get('content', ''))[:1000]}"
                                   for h in hits[:5]) or "no results"
            if name == "web_fetch":
                d = await asyncio.to_thread(post_json, "https://ollama.com/api/web_fetch",
                                            {"url": str(args.get("url", ""))}, s.key, 30)
                return f"{d.get('title', '')}\n{str(d.get('content', ''))[:5000]}".strip() or "empty page"
        except ChatError as e:
            return f"tool error: {e}"
        return f"unknown tool {name}"

    async def answer(self, s: Settings, *, user: str, name: str, text: str, mode: str, channel: str | None = None,
                     community: str = "", prefix: str = "!") -> str:
        async with self.lock(user):  # one exchange at a time per person keeps their context in order
            memory, turns = self.store.context(user)
            notes = self.notes.context(text) if s.notes else ""
            messages = [{"role": "system", "content": self.system_prompt(mode, name, memory, notes, community, prefix)},
                        *turns, {"role": "user", "content": text}]
            reply = await self.chat(s, messages, tools=True)
            if reply:
                self.store.append(user, text, reply, channel)
        if reply:
            self.schedule_compaction(s, user, name)
        return reply

    def schedule_compaction(self, s: Settings, user: str, name: str) -> None:
        exchanges = sum(1 for t in self.store.uncompacted(user) if t["role"] == "user")
        if user in self._compacting or exchanges < s.compact_after:
            return
        task = asyncio.ensure_future(self.compact(s, user, name))
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def compact(self, s: Settings, user: str, name: str) -> bool:
        """Summarise all but the last ``keep_recent`` exchanges into the person's memory."""
        if user in self._compacting:
            return False
        self._compacting.add(user)
        try:
            async with self.lock(user):
                turns = self.store.uncompacted(user)
                asks = [i for i, t in enumerate(turns) if t["role"] == "user"]
                keep = min(s.keep_recent, s.compact_after - 1)
                if len(asks) < s.compact_after:
                    return False
                old = turns[: asks[len(asks) - keep] if keep else len(turns)]
                if not old:
                    return False
                transcript = "\n".join(f"{name if t['role'] == 'user' else 'Vectoria'}: {t['content']}" for t in old)
                prompt = COMPACT_PROMPT.format(name=name, summary=self.store.memory(user) or "(nothing yet)",
                                               transcript=transcript)
                try:
                    summary = await self.chat(s, [{"role": "user", "content": prompt}], tools=False)
                except ChatError as e:
                    log.warning("Vectoria couldn't compact %s's context: %s", user, e)
                    return False
                if not summary.strip():
                    return False
                self.store.compact(user, summary.strip(), old[-1]["id"])
                return True
        finally:
            self._compacting.discard(user)

    async def drain(self) -> None:
        if self._background:
            await asyncio.gather(*list(self._background), return_exceptions=True)
