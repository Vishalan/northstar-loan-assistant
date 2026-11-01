"""Platform database: audit log, turns, spans and client metrics.

Two interchangeable backends with the same small interface (execute, executemany, query, audit, save_turn):
- SQLite through the standard library (default; APP_DB is the file): zero local setup.
- Postgres (APP_DB_URL=postgresql://...; `uv sync --extra postgres`): any managed Postgres such as RDS,
  Cloud SQL or Azure Database, shared by every orchestrator replica.
Queries are written with ? placeholders; the Postgres backend converts them. The audit table is append-only
by construction in both: this module exposes no update or delete for it, and a trigger rejects them.
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


AUDIT_COLS = ["at", "actor", "customer_id", "session_id", "turn_id", "action", "tier", "params_hash",
              "confirmation", "result", "request_id"]


def _audit_values(row: dict) -> tuple:
    return tuple(json.dumps(row[c]) if isinstance(row.get(c), (dict, list)) else row.get(c) for c in AUDIT_COLS)


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
        self.execute(f"INSERT INTO audit_log ({','.join(AUDIT_COLS)}) VALUES ({','.join('?' * len(AUDIT_COLS))})",
                     _audit_values(row))

    def save_turn(self, values: tuple) -> None:
        self.execute("INSERT OR REPLACE INTO turns VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", values)


PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
  audit_id BIGSERIAL PRIMARY KEY, at TEXT NOT NULL, actor TEXT NOT NULL, customer_id TEXT NOT NULL,
  session_id TEXT, turn_id TEXT, action TEXT NOT NULL, tier TEXT NOT NULL, params_hash TEXT NOT NULL,
  confirmation TEXT, result TEXT NOT NULL, request_id TEXT);
CREATE OR REPLACE FUNCTION audit_append_only() RETURNS trigger AS $$
  BEGIN RAISE EXCEPTION 'audit is append-only'; END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS audit_no_change ON audit_log;
CREATE TRIGGER audit_no_change BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW EXECUTE FUNCTION audit_append_only();
CREATE TABLE IF NOT EXISTS turns (
  turn_id TEXT PRIMARY KEY, session_id TEXT, customer_id TEXT, channel TEXT, mode TEXT, user_text TEXT,
  answer_text TEXT, tools TEXT, status TEXT, first_status_ms DOUBLE PRECISION, first_token_ms DOUBLE PRECISION,
  total_ms DOUBLE PRECISION, at TEXT);
CREATE TABLE IF NOT EXISTS spans (
  id BIGSERIAL PRIMARY KEY, trace_id TEXT, name TEXT NOT NULL, system TEXT, status TEXT,
  duration_ms DOUBLE PRECISION NOT NULL, attrs TEXT, at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS spans_name ON spans(name, id);
CREATE TABLE IF NOT EXISTS client_metrics (
  id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, ms DOUBLE PRECISION NOT NULL, meta TEXT, at TEXT NOT NULL);
"""


class PostgresDatabase(Database):
    """Same interface on Postgres. One connection guarded by a lock, like the SQLite backend; a pool is the
    next step when one replica's writes become the bottleneck."""

    def __init__(self, url: str):
        import psycopg
        from psycopg.rows import dict_row

        self._lock = threading.Lock()
        self._db = psycopg.connect(url, autocommit=True, row_factory=dict_row)
        with self._lock:
            self._db.execute(PG_SCHEMA)

    @staticmethod
    def _sql(sql: str) -> str:
        return sql.replace("%", "%%").replace("?", "%s")

    def execute(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._db.execute(self._sql(sql), params)

    def executemany(self, sql: str, rows: list[tuple]) -> None:
        with self._lock, self._db.cursor() as cur:
            cur.executemany(self._sql(sql), rows)

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            return list(self._db.execute(self._sql(sql), params).fetchall())

    def save_turn(self, values: tuple) -> None:
        cols = ["turn_id", "session_id", "customer_id", "channel", "mode", "user_text", "answer_text", "tools",
                "status", "first_status_ms", "first_token_ms", "total_ms", "at"]
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols[1:])
        self.execute(f"INSERT INTO turns ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
                     f"ON CONFLICT (turn_id) DO UPDATE SET {updates}", values)


def open_db(target: str | Path) -> Database:
    target = str(target)
    return PostgresDatabase(target) if target.startswith(("postgres://", "postgresql://")) else Database(target)


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        default = Path(__file__).resolve().parents[2] / "var" / "app.db"
        _db = open_db(os.environ.get("APP_DB_URL") or os.environ.get("APP_DB", default))
    return _db


def reset_db(path: str | Path) -> Database:
    global _db
    _db = open_db(path)
    return _db
