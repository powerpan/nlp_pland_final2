"""SQLite persistence for profile transcripts, memory, approvals, HITL and run history."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

PROFILE_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT,
    kind TEXT NOT NULL DEFAULT 'chat',      -- chat | bot_chat | room_member | delegation | subagent | eval
    room_id TEXT,
    status TEXT NOT NULL DEFAULT 'idle',    -- idle | running | waiting_human | error
    created REAL NOT NULL,
    updated REAL NOT NULL,
    meta TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    body TEXT NOT NULL,                     -- full chat-format message as JSON
    meta TEXT NOT NULL DEFAULT '{}',
    created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS experiences (
    id TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    outcome TEXT NOT NULL,                  -- success | partial | failure
    summary TEXT NOT NULL,
    lessons TEXT NOT NULL DEFAULT '[]',
    procedure TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    session_id TEXT,
    created REAL NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0,
    helpful INTEGER NOT NULL DEFAULT 0,
    unhelpful INTEGER NOT NULL DEFAULT 0,
    last_used REAL
);
CREATE TABLE IF NOT EXISTS memory_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    store TEXT NOT NULL,                    -- memory | user | experience | skill
    op TEXT NOT NULL,                       -- add | replace | remove | retrieve | feedback
    detail TEXT NOT NULL,
    session_id TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content, session_id UNINDEXED, msg_id UNINDEXED, role UNINDEXED, tokenize='trigram'
);
CREATE TABLE IF NOT EXISTS approval_rules (
    pattern TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    created REAL NOT NULL
);
"""

SHARED_SCHEMA = """
CREATE TABLE IF NOT EXISTS hitl_requests (
    id TEXT PRIMARY KEY,
    profile TEXT NOT NULL,
    session_id TEXT NOT NULL,
    room_id TEXT,
    kind TEXT NOT NULL,                     -- clarify | approval
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', -- pending | answered | expired | cancelled
    answer TEXT,
    created REAL NOT NULL,
    answered REAL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    type TEXT NOT NULL,
    profile TEXT,
    session_id TEXT,
    room_id TEXT,
    run_id TEXT,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id);
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    root_run TEXT NOT NULL,
    run_id TEXT,
    profile TEXT,
    session_id TEXT,
    purpose TEXT NOT NULL,                  -- turn | reflection | compaction | wrapup
    model TEXT,
    prompt_tokens INTEGER NOT NULL,
    cached_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    duration REAL NOT NULL,
    ok INTEGER NOT NULL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_root ON llm_calls(root_run);
"""


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def now() -> float:
    return time.time()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def loads(text: str | None, default: Any = None) -> Any:
    if text is None:
        return default
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return default


class DB:
    """A thread-safe SQLite wrapper (one connection, serialized by a re-entrant lock)."""

    _registry: dict[Path, "DB"] = {}
    _registry_lock = threading.Lock()

    def __init__(self, path: Path, schema: str):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=30000")
            self._conn.executescript(schema)
            self._conn.commit()

    @classmethod
    def open(cls, path: Path, schema: str) -> "DB":
        path = path.resolve()
        with cls._registry_lock:
            db = cls._registry.get(path)
            if db is None:
                db = cls(path, schema)
                cls._registry[path] = db
            return db

    @classmethod
    def close_all(cls) -> None:
        with cls._registry_lock:
            for db in cls._registry.values():
                try:
                    db._conn.close()
                except sqlite3.Error:
                    pass
            cls._registry.clear()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None


def profile_db(home: Path) -> DB:
    return DB.open(home / "state.db", PROFILE_SCHEMA)


def shared_db(root: Path) -> DB:
    return DB.open(root / "shared.db", SHARED_SCHEMA)
