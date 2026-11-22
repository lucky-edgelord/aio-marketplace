"""Each person's scene (place, expression, the pages of her last line), the conversation, and which messages are
screens. SQLite."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS scenes (key TEXT PRIMARY KEY, place TEXT NOT NULL, mood TEXT NOT NULL,
    pages TEXT NOT NULL DEFAULT '[]', page INTEGER NOT NULL DEFAULT 0, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL, role TEXT NOT NULL,
    content TEXT NOT NULL, at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS history_key ON history (key, id);
CREATE TABLE IF NOT EXISTS screens (message_id TEXT PRIMARY KEY, key TEXT NOT NULL, kind TEXT NOT NULL,
    user TEXT NOT NULL, at REAL NOT NULL);
"""


class Store:
    def __init__(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.lock = threading.Lock()

    def q(self, sql: str, args: tuple = ()):
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def scene(self, key: str, place: str, mood: str = "smile") -> dict:
        r = self.q("SELECT place, mood, pages, page FROM scenes WHERE key=?", (key,))
        if not r:
            return {"place": place, "mood": mood, "pages": [], "page": 0}
        return {"place": r[0][0], "mood": r[0][1], "pages": json.loads(r[0][2]), "page": r[0][3]}

    def save_scene(self, key: str, s: dict) -> None:
        self.q("INSERT OR REPLACE INTO scenes (key, place, mood, pages, page, at) VALUES (?,?,?,?,?,?)",
               (key, s["place"], s["mood"], json.dumps(s["pages"]), int(s["page"]), time.time()))

    def add(self, key: str, role: str, content: str, keep: int) -> None:
        self.q("INSERT INTO history (key, role, content, at) VALUES (?,?,?,?)", (key, role, content, time.time()))
        self.q("DELETE FROM history WHERE key=? AND id NOT IN (SELECT id FROM history WHERE key=? ORDER BY id DESC "
               "LIMIT ?)", (key, key, keep))

    def history(self, key: str) -> list[dict]:
        return [{"role": r, "content": c} for r, c in
                self.q("SELECT role, content FROM history WHERE key=? ORDER BY id", (key,))]

    def forget(self, key: str) -> None:
        self.q("DELETE FROM history WHERE key=?", (key,))
        self.q("DELETE FROM scenes WHERE key=?", (key,))

    def mark(self, message_id: str, key: str, kind: str, user: str) -> None:
        self.q("INSERT OR REPLACE INTO screens (message_id, key, kind, user, at) VALUES (?,?,?,?,?)",
               (message_id, key, kind, user, time.time()))
        self.q("DELETE FROM screens WHERE at < ?", (time.time() - 30 * 86400,))

    def screen(self, message_id: str) -> dict | None:
        r = self.q("SELECT key, kind, user FROM screens WHERE message_id=?", (message_id,))
        return {"key": r[0][0], "kind": r[0][1], "user": r[0][2]} if r else None

    def counts(self) -> dict:
        return {"people": self.q("SELECT COUNT(*) FROM scenes")[0][0],
                "lines": self.q("SELECT COUNT(*) FROM history WHERE role='assistant'")[0][0]}

    def close(self) -> None:
        with self.lock:
            self.db.close()
