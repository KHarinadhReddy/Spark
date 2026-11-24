from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS actions (
    id          TEXT PRIMARY KEY,
    tool        TEXT NOT NULL,
    args        TEXT NOT NULL,
    args_hash   TEXT NOT NULL,
    preview     TEXT NOT NULL,
    status      TEXT NOT NULL,
    source      TEXT,
    created_at  TEXT NOT NULL,
    decided_at  TEXT,
    executed_at TEXT,
    result      TEXT,
    undo        TEXT,
    undo_status TEXT
);

CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status);
CREATE INDEX IF NOT EXISTS idx_actions_hash ON actions(tool, args_hash, status);

CREATE TABLE IF NOT EXISTS audit (
    id         TEXT PRIMARY KEY,
    ts         TEXT NOT NULL,
    event      TEXT NOT NULL,
    action_id  TEXT,
    tool       TEXT,
    detail     TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts);
"""


class Database:
    """Tiny SQLite wrapper. One connection per unit of work, safe across threads."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(sql, params).fetchone()

    def query_all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute(sql, params).fetchall())

    def execute(self, sql: str, params: tuple = ()) -> None:
        with self.connect() as conn:
            conn.execute(sql, params)
