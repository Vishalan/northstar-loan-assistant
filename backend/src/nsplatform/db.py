"""Platform database: audit log, OTP challenges, turns, spans and client metrics.

SQLite through the standard library keeps local setup to zero. The audit table is append-only by
construction: this module exposes no update or delete for it.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
  audit_id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL, customer_id TEXT NOT NULL,
  session_id TEXT, turn_id TEXT, action TEXT NOT NULL, tier TEXT NOT NULL, params_hash TEXT NOT NULL,
  confirmation TEXT, result TEXT NOT NULL, request_id TEXT);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
CREATE TABLE IF NOT EXISTS turns (
  turn_id TEXT PRIMARY KEY, session_id TEXT, customer_id TEXT, channel TEXT, mode TEXT, user_text TEXT,
  answer_text TEXT, tools TEXT, status TEXT, first_status_ms REAL, first_token_ms REAL, total_ms REAL, at TEXT);
CREATE TABLE IF NOT EXISTS spans (
  id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT, name TEXT NOT NULL, system TEXT, status TEXT,
  duration_ms REAL NOT NULL, attrs TEXT, at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS spans_name ON spans(name, id);
CREATE TABLE IF NOT EXISTS client_metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, ms REAL NOT NULL, meta TEXT, at TEXT NOT NULL);
"""


class Database:
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)

    def execute(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._db.execute(sql, params)
            self._db.commit()

    def executemany(self, sql: str, rows: list[tuple]) -> None:
        with self._lock:
            self._db.executemany(sql, rows)
            self._db.commit()

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, params).fetchall()]

    def audit(self, **row) -> None:
        cols = ["at", "actor", "customer_id", "session_id", "turn_id", "action", "tier", "params_hash",
                "confirmation", "result", "request_id"]
        values = tuple(json.dumps(row[c]) if isinstance(row.get(c), (dict, list)) else row.get(c) for c in cols)
        self.execute(f"INSERT INTO audit_log ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", values)


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        default = Path(__file__).resolve().parents[2] / "var" / "app.db"
        _db = Database(os.environ.get("APP_DB", default))
    return _db


def reset_db(path: str | Path) -> Database:
    global _db
    _db = Database(path)
    return _db
