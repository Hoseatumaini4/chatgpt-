"""SQLite storage: conversation memory, message de-duplication, daily usage, per-user provider."""
from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import List, Optional

EAT = timezone(timedelta(hours=3))  # East Africa Time; daily limits reset at local midnight


def _today() -> str:
    return datetime.now(EAT).date().isoformat()


class Store:
    def __init__(self, path: str):
        self.path = path
        with closing(self._conn()) as c, c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone TEXT NOT NULL, role TEXT NOT NULL,
                    content TEXT NOT NULL, ts REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_messages_phone ON messages(phone, id);
                CREATE TABLE IF NOT EXISTS seen(msg_id TEXT PRIMARY KEY, ts REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS usage(
                    phone TEXT NOT NULL, day TEXT NOT NULL, n INTEGER NOT NULL,
                    PRIMARY KEY(phone, day));
                CREATE TABLE IF NOT EXISTS prefs(phone TEXT PRIMARY KEY, provider TEXT NOT NULL);
                """
            )

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    # --- de-duplication (Africa's Talking retries callbacks that time out) ---
    def claim_message(self, msg_id: str) -> bool:
        """True the first time `msg_id` is seen, False afterwards. Empty ids always pass."""
        if not msg_id:
            return True
        with closing(self._conn()) as c, c:
            cur = c.execute("INSERT OR IGNORE INTO seen(msg_id, ts) VALUES(?, ?)", (msg_id, time.time()))
            return cur.rowcount == 1

    # --- conversation memory ---
    def add(self, phone: str, role: str, content: str) -> None:
        with closing(self._conn()) as c, c:
            c.execute(
                "INSERT INTO messages(phone, role, content, ts) VALUES(?,?,?,?)",
                (phone, role, content, time.time()),
            )

    def history(self, phone: str, max_messages: int, ttl_minutes: int) -> List[dict]:
        cutoff = time.time() - ttl_minutes * 60
        with closing(self._conn()) as c:
            rows = c.execute(
                "SELECT role, content FROM messages WHERE phone=? AND ts>? ORDER BY id DESC LIMIT ?",
                (phone, cutoff, max_messages),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def clear(self, phone: str) -> None:
        with closing(self._conn()) as c, c:
            c.execute("DELETE FROM messages WHERE phone=?", (phone,))

    # --- daily usage (cost control) ---
    def bump_usage(self, phone: str) -> int:
        """Count one more incoming message today and return the new total."""
        day = _today()
        with closing(self._conn()) as c, c:
            c.execute(
                "INSERT INTO usage(phone, day, n) VALUES(?,?,1) "
                "ON CONFLICT(phone, day) DO UPDATE SET n = n + 1",
                (phone, day),
            )
            return c.execute("SELECT n FROM usage WHERE phone=? AND day=?", (phone, day)).fetchone()["n"]

    # --- per-user provider choice ---
    def get_provider(self, phone: str) -> Optional[str]:
        with closing(self._conn()) as c:
            row = c.execute("SELECT provider FROM prefs WHERE phone=?", (phone,)).fetchone()
        return row["provider"] if row else None

    def set_provider(self, phone: str, provider: str) -> None:
        with closing(self._conn()) as c, c:
            c.execute(
                "INSERT INTO prefs(phone, provider) VALUES(?,?) "
                "ON CONFLICT(phone) DO UPDATE SET provider=excluded.provider",
                (phone, provider),
            )

    # --- housekeeping ---
    def purge(self, older_than_days: int = 7) -> None:
        cutoff = time.time() - older_than_days * 86400
        with closing(self._conn()) as c, c:
            c.execute("DELETE FROM messages WHERE ts<?", (cutoff,))
            c.execute("DELETE FROM seen WHERE ts<?", (cutoff,))
