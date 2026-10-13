"""Historique optionnel des messages (SQLite, mode WAL). Désactivé par défaut."""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at REAL NOT NULL,
    radio_id TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    channel INTEGER,
    type TEXT NOT NULL,
    sender_declared TEXT,
    text TEXT,
    lat REAL,
    lon REAL,
    blob BLOB,
    delivery TEXT
);
CREATE INDEX IF NOT EXISTS messages_radio_id ON messages (radio_id, id);
"""


class History:
    """Un message reçu a un expéditeur **déclaré** ; seul un message envoyé (``out``) a une origine certaine."""

    def __init__(self, path: str | Path) -> None:
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)

    def add(self, radio_id: str, direction: str, type_: str, sender: str | None = None, text: str | None = None,
            channel: int | None = None, lat: float | None = None, lon: float | None = None,
            blob: bytes | None = None, delivery: str | None = None) -> int:
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO messages (received_at, radio_id, direction, channel, type, sender_declared, text, lat, lon, blob, delivery)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (time.time(), radio_id, direction, channel, type_, sender, text, lat, lon, blob, delivery))
            return cur.lastrowid

    def list(self, radio_id: str, limit: int = 100, before_id: int | None = None) -> list[dict]:
        limit = max(1, min(limit, 500))
        sql = "SELECT id, received_at, radio_id, direction, channel, type, sender_declared, text, lat, lon, delivery, length(blob) AS blob_bytes FROM messages WHERE radio_id=?"
        args: list = [radio_id]
        if before_id is not None:
            sql += " AND id<?"
            args.append(before_id)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, args)]

    def blob(self, radio_id: str, message_id: int) -> bytes | None:
        with self._lock:
            row = self._db.execute("SELECT blob FROM messages WHERE radio_id=? AND id=?", (radio_id, message_id)).fetchone()
        return row["blob"] if row else None

    def close(self) -> None:
        with self._lock:
            self._db.close()
