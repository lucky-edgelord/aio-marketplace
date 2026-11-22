"""Kitsune's SQLite store: per-user context, rolling memory summaries, and reply/feedback logs.

* ``turns``: every message of every conversation, keyed by user. Compacted turns are kept (``compacted = 1``)
  so the full history stays available as logs; only uncompacted turns are sent to the model.
* ``memories``: one rolling summary per user, rewritten each time their older turns are compacted.
* ``replies`` and ``feedback``: each talking-video reply (message id, prompt, text, mood) and the 👍/👎 votes on it.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..providers.llm import ChatMessage

SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
    channel TEXT, at REAL NOT NULL, compacted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS turns_by_user ON turns (user, compacted, id);
CREATE TABLE IF NOT EXISTS memories (
    user TEXT PRIMARY KEY, summary TEXT NOT NULL, turns_compacted INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS replies (
    message_id TEXT PRIMARY KEY, user TEXT NOT NULL, channel TEXT, prompt TEXT NOT NULL, reply TEXT NOT NULL,
    mood TEXT, at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    message_id TEXT NOT NULL, rater TEXT NOT NULL, rating INTEGER NOT NULL, at REAL NOT NULL,
    PRIMARY KEY (message_id, rater)
);
"""


@dataclass
class Context:
    """What the model sees for one user: their memory summary plus their recent, uncompacted turns."""

    summary: str
    turns: List[ChatMessage]

    @property
    def exchanges(self) -> int:
        return sum(1 for t in self.turns if t["role"] == "user")


class ConversationStore:
    def __init__(self, path: str) -> None:
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        with self._lock:
            self._migrate()
            self._db.executescript(SCHEMA)
            self._db.commit()

    def _migrate(self) -> None:
        """0.3 stored turns per (chat, user) without ids; carry them over as per-user turns."""
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(turns)")}
        if cols and "compacted" not in cols:
            self._db.execute("ALTER TABLE turns RENAME TO turns_v03")
            self._db.executescript(SCHEMA)
            self._db.execute(
                "INSERT INTO turns (user, role, content, channel, at) "
                "SELECT user, role, content, chat, at FROM turns_v03 ORDER BY at, rowid"
            )
            self._db.execute("DROP TABLE turns_v03")

    # -- context ----------------------------------------------------------------------------------------------
    def context(self, user: str) -> Context:
        with self._lock:
            row = self._db.execute("SELECT summary FROM memories WHERE user=?", (user,)).fetchone()
            rows = self._db.execute(
                "SELECT role, content FROM turns WHERE user=? AND compacted=0 ORDER BY id", (user,)
            ).fetchall()
        return Context(row[0] if row else "", [{"role": r, "content": c} for r, c in rows])

    def append(self, user: str, *messages: ChatMessage, channel: Optional[str] = None) -> None:
        now = time.time()
        with self._lock:
            self._db.executemany(
                "INSERT INTO turns (user, role, content, channel, at) VALUES (?,?,?,?,?)",
                [(user, m["role"], m["content"], channel, now) for m in messages],
            )
            self._db.commit()

    def uncompacted(self, user: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, role, content FROM turns WHERE user=? AND compacted=0 ORDER BY id", (user,)
            ).fetchall()
        return [{"id": i, "role": r, "content": c} for i, r, c in rows]

    def compact(self, user: str, summary: str, up_to_id: int) -> int:
        """Store the new summary and mark turns up to ``up_to_id`` as compacted. Returns how many were compacted."""
        with self._lock:
            n = self._db.execute(
                "UPDATE turns SET compacted=1 WHERE user=? AND compacted=0 AND id<=?", (user, up_to_id)
            ).rowcount
            self._db.execute(
                "INSERT INTO memories (user, summary, turns_compacted, updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(user) DO UPDATE SET summary=excluded.summary, "
                "turns_compacted=memories.turns_compacted+excluded.turns_compacted, updated_at=excluded.updated_at",
                (user, summary, n, time.time()),
            )
            self._db.commit()
        return n

    def memory(self, user: str) -> str:
        return self.context(user).summary

    def forget(self, user: str) -> int:
        """Clear a user's context and memory (their reply/feedback logs are kept)."""
        with self._lock:
            n = self._db.execute("DELETE FROM turns WHERE user=?", (user,)).rowcount
            n += self._db.execute("DELETE FROM memories WHERE user=?", (user,)).rowcount
            self._db.commit()
        return n

    # -- reply and feedback logs ---------------------------------------------------------------------------------
    def log_reply(
        self, message_id: str, user: str, prompt: str, reply: str, mood: str, channel: Optional[str] = None
    ) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO replies VALUES (?,?,?,?,?,?,?)",
                (message_id, user, channel, prompt, reply, mood, time.time()),
            )
            self._db.commit()

    def reply_text(self, message_id: str) -> Optional[str]:
        """What Kitsune said in a logged reply (for when someone replies to it)."""
        with self._lock:
            row = self._db.execute("SELECT reply FROM replies WHERE message_id=?", (message_id,)).fetchone()
        return row[0] if row else None

    def is_reply(self, message_id: str) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM replies WHERE message_id=?", (message_id,)).fetchone() is not None

    def rate(self, message_id: str, rater: str, rating: int) -> bool:
        """Record a 👍 (+1) or 👎 (-1). Only for logged replies; a rater's latest vote wins."""
        if not self.is_reply(message_id):
            return False
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO feedback VALUES (?,?,?,?)", (message_id, rater, rating, time.time())
            )
            self._db.commit()
        return True

    def unrate(self, message_id: str, rater: str, rating: int) -> None:
        with self._lock:
            self._db.execute(
                "DELETE FROM feedback WHERE message_id=? AND rater=? AND rating=?", (message_id, rater, rating)
            )
            self._db.commit()

    def feedback(self) -> List[Dict[str, Any]]:
        """Every rated reply, newest first (for exporting training/eval logs)."""
        with self._lock:
            rows = self._db.execute(
                "SELECT r.message_id, r.user, r.prompt, r.reply, r.mood, f.rater, f.rating, f.at "
                "FROM feedback f JOIN replies r USING (message_id) ORDER BY f.at DESC"
            ).fetchall()
        keys = ("message_id", "user", "prompt", "reply", "mood", "rater", "rating", "at")
        return [dict(zip(keys, row)) for row in rows]

    def close(self) -> None:
        with self._lock:
            self._db.close()
