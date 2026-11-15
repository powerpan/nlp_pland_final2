"""Persist a profile’s sessions and conversation transcript."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from .store import dumps, loads, new_id, now

if TYPE_CHECKING:
    from .profiles import Profile


@dataclass
class Session:
    id: str
    title: str
    kind: str
    room_id: str | None
    status: str
    created: float
    updated: float
    meta: dict[str, Any]

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Session":
        return cls(
            id=row["id"],
            title=row["title"] or "",
            kind=row["kind"],
            room_id=row["room_id"],
            status=row["status"],
            created=row["created"],
            updated=row["updated"],
            meta=loads(row["meta"], {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class SessionStore:
    def __init__(self, profile: "Profile"):
        self.profile = profile
        self.db = profile.db

    def create(self, *, title: str = "", kind: str = "chat", room_id: str | None = None, meta: dict | None = None) -> Session:
        sid = new_id("s_")
        ts = now()
        self.db.execute(
            "INSERT INTO sessions(id, title, kind, room_id, status, created, updated, meta) VALUES (?,?,?,?,?,?,?,?)",
            (sid, title, kind, room_id, "idle", ts, ts, dumps(meta or {})),
        )
        return self.get(sid)

    def get(self, sid: str) -> Session:
        row = self.db.one("SELECT * FROM sessions WHERE id=?", (sid,))
        if row is None:
            raise KeyError(f"no session {sid} in profile {self.profile.name}")
        return Session.from_row(row)

    def find(self, *, kind: str, room_id: str | None = None) -> Session | None:
        if room_id is None:
            row = self.db.one("SELECT * FROM sessions WHERE kind=? ORDER BY created LIMIT 1", (kind,))
        else:
            row = self.db.one("SELECT * FROM sessions WHERE kind=? AND room_id=? ORDER BY created LIMIT 1", (kind, room_id))
        return Session.from_row(row) if row else None

    def list(self, *, kinds: tuple[str, ...] | None = None, limit: int = 100) -> list[Session]:
        if kinds:
            marks = ",".join("?" * len(kinds))
            rows = self.db.query(
                f"SELECT * FROM sessions WHERE kind IN ({marks}) ORDER BY updated DESC LIMIT ?", (*kinds, limit)
            )
        else:
            rows = self.db.query("SELECT * FROM sessions ORDER BY updated DESC LIMIT ?", (limit,))
        return [Session.from_row(r) for r in rows]

    def update(self, sid: str, **fields: Any) -> None:
        sets, params = [], []
        for key in ("title", "status", "room_id"):
            if key in fields:
                sets.append(f"{key}=?")
                params.append(fields[key])
        if "meta" in fields:
            sets.append("meta=?")
            params.append(dumps(fields["meta"]))
        sets.append("updated=?")
        params.append(now())
        params.append(sid)
        self.db.execute(f"UPDATE sessions SET {', '.join(sets)} WHERE id=?", params)

    def delete(self, sid: str) -> None:
        self.db.execute("DELETE FROM messages WHERE session_id=?", (sid,))
        self.db.execute("DELETE FROM sessions WHERE id=?", (sid,))

    # ----------------------------------------------------------------- messages
    def append(self, sid: str, message: dict[str, Any], meta: dict[str, Any] | None = None) -> int:
        cur = self.db.execute(
            "INSERT INTO messages(session_id, role, body, meta, created) VALUES (?,?,?,?,?)",
            (sid, message.get("role", "user"), dumps(message), dumps(meta or {}), now()),
        )
        self.db.execute("UPDATE sessions SET updated=? WHERE id=?", (now(), sid))
        return int(cur.lastrowid)

    def messages(self, sid: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT body FROM messages WHERE session_id=? ORDER BY id", (sid,))
        return [loads(r["body"], {}) for r in rows]

    def records(self, sid: str, *, after_id: int = 0) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT id, role, body, meta, created FROM messages WHERE session_id=? AND id>? ORDER BY id", (sid, after_id)
        )
        return [
            {"id": r["id"], "role": r["role"], "message": loads(r["body"], {}), "meta": loads(r["meta"], {}), "created": r["created"]}
            for r in rows
        ]

    def replace_messages(self, sid: str, messages: list[dict[str, Any]]) -> None:
        """Used by context compaction: rewrite a session's working transcript."""
        self.db.execute("DELETE FROM messages WHERE session_id=?", (sid,))
        for m in messages:
            self.append(sid, m)
