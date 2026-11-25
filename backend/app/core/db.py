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

CREATE TABLE IF NOT EXISTS messages (
    id           TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    external_id  TEXT NOT NULL,
    thread_id    TEXT,
    sender       TEXT,
    sender_name  TEXT,
    subject      TEXT,
    snippet      TEXT,
    body         TEXT,
    received_at  TEXT,
    labels       TEXT,
    category     TEXT,
    priority     TEXT,
    summary      TEXT,
    needs_action INTEGER DEFAULT 0,
    deadline_id  TEXT,
    flags        TEXT,
    unread       INTEGER DEFAULT 1,
    archived     INTEGER DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    UNIQUE(source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_received ON messages(received_at);
CREATE INDEX IF NOT EXISTS idx_messages_source ON messages(source);
CREATE INDEX IF NOT EXISTS idx_messages_category ON messages(category);

CREATE TABLE IF NOT EXISTS deadlines (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    source_id   TEXT,
    title       TEXT NOT NULL,
    due_date    TEXT,
    due_at      TEXT,
    timezone    TEXT,
    category    TEXT,
    priority    TEXT,
    confidence  REAL DEFAULT 0.5,
    evidence    TEXT,
    status      TEXT NOT NULL DEFAULT 'active',
    dedupe_key  TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_deadlines_due ON deadlines(due_date);
CREATE INDEX IF NOT EXISTS idx_deadlines_status ON deadlines(status);
CREATE INDEX IF NOT EXISTS idx_deadlines_dedupe ON deadlines(dedupe_key);

CREATE TABLE IF NOT EXISTS reminders (
    id          TEXT PRIMARY KEY,
    deadline_id TEXT NOT NULL,
    channel     TEXT NOT NULL DEFAULT 'in-app',
    fire_at     TEXT NOT NULL,
    sent_at     TEXT,
    status      TEXT NOT NULL DEFAULT 'scheduled',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(status, fire_at);

CREATE TABLE IF NOT EXISTS notifications (
    id         TEXT PRIMARY KEY,
    ts         TEXT NOT NULL,
    title      TEXT NOT NULL,
    body       TEXT,
    kind       TEXT,
    source     TEXT,
    source_id  TEXT,
    read       INTEGER DEFAULT 0,
    meta       TEXT
);

CREATE INDEX IF NOT EXISTS idx_notifications_ts ON notifications(ts);

CREATE TABLE IF NOT EXISTS profiles (
    id         TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS companion_devices (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    platform   TEXT,
    token_hash TEXT NOT NULL,
    last_seen  TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    ts         TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    meta       TEXT
);

CREATE INDEX IF NOT EXISTS idx_conversations_ts ON conversations(ts);

CREATE TABLE IF NOT EXISTS sync_state (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS form_audit (
    id         TEXT PRIMARY KEY,
    ts         TEXT NOT NULL,
    url        TEXT,
    site       TEXT,
    fields     INTEGER,
    submitted  INTEGER DEFAULT 0,
    detail     TEXT
);
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
        conn = sqlite3.connect(self.path, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=15000")
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

    def executemany(self, sql: str, rows: list[tuple]) -> None:
        with self.connect() as conn:
            conn.executemany(sql, rows)
