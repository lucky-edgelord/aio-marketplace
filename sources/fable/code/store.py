"""Fable's saves: who owns which character in each community, rolls left, coins, wishes and the party. SQLite."""

from __future__ import annotations

import os
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    guild TEXT NOT NULL, user TEXT NOT NULL, name TEXT NOT NULL DEFAULT '',
    window_start REAL NOT NULL DEFAULT 0, rolls_used INTEGER NOT NULL DEFAULT 0, bonus_rolls INTEGER NOT NULL DEFAULT 0,
    last_claim REAL NOT NULL DEFAULT 0, coins INTEGER NOT NULL DEFAULT 0, daily_at REAL NOT NULL DEFAULT 0,
    last_steal REAL NOT NULL DEFAULT 0, last_seen REAL NOT NULL DEFAULT 0, guarantee INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild, user));
CREATE TABLE IF NOT EXISTS owned (
    guild TEXT NOT NULL, char_id INTEGER NOT NULL, user TEXT NOT NULL, at REAL NOT NULL,
    PRIMARY KEY (guild, char_id));
CREATE INDEX IF NOT EXISTS owned_by_user ON owned (guild, user);
CREATE TABLE IF NOT EXISTS wishes (
    guild TEXT NOT NULL, user TEXT NOT NULL, char_id INTEGER NOT NULL, PRIMARY KEY (guild, user, char_id));
CREATE TABLE IF NOT EXISTS party (
    guild TEXT NOT NULL, user TEXT NOT NULL, slot INTEGER NOT NULL, char_id INTEGER NOT NULL,
    PRIMARY KEY (guild, user, slot));
CREATE TABLE IF NOT EXISTS rolls (
    message_id TEXT PRIMARY KEY, guild TEXT NOT NULL, channel TEXT NOT NULL, char_id INTEGER NOT NULL,
    roller TEXT NOT NULL, at REAL NOT NULL, claimed_by TEXT);
CREATE TABLE IF NOT EXISTS log (at REAL NOT NULL, guild TEXT NOT NULL, user TEXT NOT NULL, what TEXT NOT NULL,
    char_id INTEGER);
"""
FIELDS = ("window_start", "rolls_used", "bonus_rolls", "last_claim", "coins", "daily_at", "last_steal", "last_seen",
          "guarantee", "name")


class Store:
    def __init__(self, path: str) -> None:
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def q(self, sql: str, args: tuple = (), *, write: bool = False):
        with self._lock:
            cur = self._db.execute(sql, args)
            rows = cur.fetchall() if not write else []
            if write:
                self._db.commit()
            return rows if not write else cur.rowcount

    # -- players ----------------------------------------------------------------------------------------------
    def player(self, guild: str, user: str, name: str = "") -> dict:
        with self._lock:
            self._db.execute("INSERT OR IGNORE INTO players (guild, user) VALUES (?, ?)", (guild, user))
            if name:
                self._db.execute("UPDATE players SET name=? WHERE guild=? AND user=?", (name, guild, user))
            self._db.commit()
            return dict(self._db.execute("SELECT * FROM players WHERE guild=? AND user=?", (guild, user)).fetchone())

    def update(self, guild: str, user: str, **fields) -> None:
        bad = set(fields) - set(FIELDS)
        if bad:
            raise ValueError(f"unknown fields {bad}")
        sets = ", ".join(f"{k}=?" for k in fields)
        self.q(f"UPDATE players SET {sets} WHERE guild=? AND user=?", (*fields.values(), guild, user), write=True)

    def add_coins(self, guild: str, user: str, n: int) -> int:
        self.player(guild, user)
        self.q("UPDATE players SET coins = MAX(0, coins + ?) WHERE guild=? AND user=?", (n, guild, user), write=True)
        return self.player(guild, user)["coins"]

    # -- ownership --------------------------------------------------------------------------------------------
    def owner(self, guild: str, char_id: int) -> str | None:
        rows = self.q("SELECT user FROM owned WHERE guild=? AND char_id=?", (guild, char_id))
        return rows[0]["user"] if rows else None

    def claim(self, guild: str, char_id: int, user: str) -> bool:
        """Give a free character to ``user``. False if someone already has it."""
        with self._lock:
            if self.owner(guild, char_id):
                return False
            self._db.execute("INSERT INTO owned VALUES (?, ?, ?, ?)", (guild, char_id, user, time.time()))
            self._db.commit()
            return True

    def transfer(self, guild: str, char_id: int, to: str) -> None:
        self.q("UPDATE owned SET user=?, at=? WHERE guild=? AND char_id=?", (to, time.time(), guild, char_id), write=True)
        self.q("DELETE FROM party WHERE guild=? AND char_id=?", (guild, char_id), write=True)

    def release(self, guild: str, char_id: int) -> None:
        self.q("DELETE FROM owned WHERE guild=? AND char_id=?", (guild, char_id), write=True)
        self.q("DELETE FROM party WHERE guild=? AND char_id=?", (guild, char_id), write=True)

    def owned_by(self, guild: str, user: str) -> list[int]:
        return [r["char_id"] for r in self.q("SELECT char_id FROM owned WHERE guild=? AND user=? ORDER BY at", (guild, user))]

    def taken(self, guild: str) -> set:
        return {r["char_id"] for r in self.q("SELECT char_id FROM owned WHERE guild=?", (guild,))}

    # -- wishes and party -------------------------------------------------------------------------------------
    def wish(self, guild: str, user: str, char_id: int, on: bool) -> None:
        if on:
            self.q("INSERT OR IGNORE INTO wishes VALUES (?, ?, ?)", (guild, user, char_id), write=True)
        else:
            self.q("DELETE FROM wishes WHERE guild=? AND user=? AND char_id=?", (guild, user, char_id), write=True)

    def wishes(self, guild: str, user: str) -> list[int]:
        return [r["char_id"] for r in self.q("SELECT char_id FROM wishes WHERE guild=? AND user=?", (guild, user))]

    def wishers(self, guild: str, char_id: int) -> list[str]:
        return [r["user"] for r in self.q("SELECT user FROM wishes WHERE guild=? AND char_id=?", (guild, char_id))]

    def set_party(self, guild: str, user: str, slot: int, char_id: int | None) -> None:
        self.q("DELETE FROM party WHERE guild=? AND user=? AND slot=?", (guild, user, slot), write=True)
        if char_id is not None:
            self.q("DELETE FROM party WHERE guild=? AND user=? AND char_id=?", (guild, user, char_id), write=True)
            self.q("INSERT INTO party VALUES (?, ?, ?, ?)", (guild, user, slot, char_id), write=True)

    def party(self, guild: str, user: str) -> dict:
        return {r["slot"]: r["char_id"] for r in self.q("SELECT slot, char_id FROM party WHERE guild=? AND user=?", (guild, user))}

    # -- rolls and the log ------------------------------------------------------------------------------------
    def add_roll(self, message_id: str, guild: str, channel: str, char_id: int, roller: str) -> None:
        self.q("INSERT OR REPLACE INTO rolls VALUES (?, ?, ?, ?, ?, ?, NULL)",
               (message_id, guild, channel, char_id, roller, time.time()), write=True)

    def roll(self, message_id: str) -> dict | None:
        rows = self.q("SELECT * FROM rolls WHERE message_id=?", (message_id,))
        return dict(rows[0]) if rows else None

    def latest_roll(self, channel: str) -> dict | None:
        rows = self.q("SELECT * FROM rolls WHERE channel=? ORDER BY at DESC LIMIT 1", (channel,))
        return dict(rows[0]) if rows else None

    def mark_claimed(self, message_id: str, user: str) -> bool:
        """True if this call took the roll (first one wins)."""
        return self.q("UPDATE rolls SET claimed_by=? WHERE message_id=? AND claimed_by IS NULL", (user, message_id),
                      write=True) == 1

    def log(self, guild: str, user: str, what: str, char_id: int | None = None) -> None:
        self.q("INSERT INTO log VALUES (?, ?, ?, ?, ?)", (time.time(), guild, user, what, char_id), write=True)

    def stats(self, guild: str | None = None) -> dict:
        w, a = ("WHERE guild=?", (guild,)) if guild else ("", ())
        one = lambda sql: (self.q(sql, a)[0][0] or 0)  # noqa: E731
        return {"players": one(f"SELECT COUNT(*) FROM players {w}"), "owned": one(f"SELECT COUNT(*) FROM owned {w}"),
                "rolls": one(f"SELECT COUNT(*) FROM rolls {w}"),
                "claims": one(f"SELECT COUNT(*) FROM log {w + (' AND' if w else 'WHERE')} what='claim'")}

    def recent(self, n: int = 10) -> list[dict]:
        return [dict(r) for r in self.q("SELECT * FROM log ORDER BY at DESC LIMIT ?", (n,))]

    def close(self) -> None:
        with self._lock:
            self._db.close()
