"""Per-profile conversation sessions. The transcript *is* the run state: a run that pauses for a
human (clarification/approval) or crashes can be resumed from the stored messages alone."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from .errors import NotFound
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
            raise NotFound(f"no session {sid} in profile {self.profile.name}")
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

    def patch_meta(self, sid: str, changes: dict[str, Any] | None = None, fn=None) -> dict[str, Any]:
        """Atomic read-modify-write of a session's metadata (runs, background reflection, room driver
        and tools may update the same session from different threads)."""
        with _meta_lock(self.profile.name, sid):
            meta = dict(self.get(sid).meta)
            if changes:
                meta.update(changes)
            if fn is not None:
                fn(meta)
            self.update(sid, meta=meta)
            return meta

    def delete(self, sid: str) -> None:
        self.db.execute("DELETE FROM messages_fts WHERE session_id=?", (sid,))
        self.db.execute("DELETE FROM messages WHERE session_id=?", (sid,))
        self.db.execute("DELETE FROM sessions WHERE id=?", (sid,))

    # ----------------------------------------------------------------- messages
    def append(self, sid: str, message: dict[str, Any], meta: dict[str, Any] | None = None) -> int:
        cur = self.db.execute(
            "INSERT INTO messages(session_id, role, body, meta, created) VALUES (?,?,?,?,?)",
            (sid, message.get("role", "user"), dumps(message), dumps(meta or {}), now()),
        )
        self.db.execute("UPDATE sessions SET updated=? WHERE id=?", (now(), sid))
        mid = int(cur.lastrowid)
        text = _searchable(message, meta)
        if text:
            self.db.execute("INSERT INTO messages_fts(content, session_id, msg_id, role) VALUES (?,?,?,?)",
                            (text, sid, mid, message.get("role", "user")))
        return mid

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

    # ----------------------------------------------------------------- search (session_search)
    def ensure_index(self) -> None:
        """Backfill the full-text index for databases created before it existed."""
        if self.db.one("SELECT 1 FROM messages_fts LIMIT 1") or not self.db.one("SELECT 1 FROM messages LIMIT 1"):
            return
        for r in self.db.query("SELECT id, session_id, role, body, meta FROM messages ORDER BY id"):
            text = _searchable(loads(r["body"], {}), loads(r["meta"], {}))
            if text:
                self.db.execute("INSERT INTO messages_fts(content, session_id, msg_id, role) VALUES (?,?,?,?)",
                                (text, r["session_id"], r["id"], r["role"]))

    def search(self, query: str, *, limit: int = 5, exclude: str | None = None) -> list[dict[str, Any]]:
        """Full-text search over this profile's past messages (trigram index, works for CJK too).
        Returns at most one hit per session, best first."""
        self.ensure_index()
        terms = [t for t in _FTS_TERM.findall(query or "") if len(t) >= 3]
        rows: list[dict[str, Any]] = []
        if terms:
            match = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms[:12])
            rows = self.db.query(
                "SELECT session_id, msg_id, role, snippet(messages_fts, 0, '«', '»', '…', 12) AS snip, bm25(messages_fts) AS score"
                " FROM messages_fts WHERE messages_fts MATCH ? ORDER BY score LIMIT 200", (match,))
        elif query and query.strip():
            rows = self.db.query("SELECT session_id, msg_id, role, substr(content,1,200) AS snip, 0 AS score FROM messages_fts"
                                 " WHERE content LIKE ? ORDER BY msg_id DESC LIMIT 200", (f"%{query.strip()}%",))
        out, seen = [], set()
        for r in rows:
            sid = r["session_id"]
            if sid == exclude or sid in seen:
                continue
            seen.add(sid)
            try:
                sess = self.get(sid)
            except KeyError:
                continue
            out.append({"session_id": sid, "title": sess.title, "kind": sess.kind, "when": sess.updated,
                        "match_message_id": int(r["msg_id"]), "role": r["role"], "snippet": r["snip"]})
            if len(out) >= limit:
                break
        return out

    def window(self, sid: str, around_id: int, size: int = 4) -> list[dict[str, Any]]:
        before = self.db.query("SELECT id, role, body, meta FROM messages WHERE session_id=? AND id<=? ORDER BY id DESC LIMIT ?",
                               (sid, around_id, size + 1))
        after = self.db.query("SELECT id, role, body, meta FROM messages WHERE session_id=? AND id>? ORDER BY id LIMIT ?",
                              (sid, around_id, size))
        rows = list(reversed(before)) + after
        out = []
        for r in rows:
            text = _searchable(loads(r["body"], {}), loads(r["meta"], {}))
            if text:
                out.append({"id": r["id"], "role": r["role"], "text": text[:1500]})
        return out

    def replace_messages(self, sid: str, messages: list[dict[str, Any]]) -> None:
        """Used by context compaction: rewrite a session's working transcript."""
        self.db.execute("DELETE FROM messages_fts WHERE session_id=?", (sid,))
        self.db.execute("DELETE FROM messages WHERE session_id=?", (sid,))
        for m in messages:
            self.append(sid, m)


_META_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_META_GUARD = threading.Lock()


def _meta_lock(profile: str, sid: str) -> threading.Lock:
    with _META_GUARD:
        return _META_LOCKS.setdefault((profile, sid), threading.Lock())


_FTS_TERM = re.compile(r"[A-Za-z0-9_./-]+|[\u3400-\u9fff\uf900-\ufaff]+")


def _searchable(message: dict[str, Any], meta: dict[str, Any] | None) -> str:
    """Text worth indexing: what the user typed (not the experience-augmented prompt), assistant replies,
    and the head of tool results (facts discovered by tools). System prompts are not indexed."""
    role = message.get("role")
    if role == "system":
        return ""
    if role == "user":
        return str((meta or {}).get("display") or message.get("content") or "")[:4000]
    if role == "tool":
        return str(message.get("content") or "")[:2000]
    text = str(message.get("content") or "")
    for tc in message.get("tool_calls") or []:
        text += f"\n[{tc['function']['name']}] {tc['function'].get('arguments', '')[:300]}"
    return text[:4000]
