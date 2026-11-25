"""Live state for the web UI, derived from the runtime's event bus.

The core publishes everything observable on `runtime.bus` from worker threads (agent runs, room
drives, delegations). The server needs two things on top of that stream:

* `LiveState` — an in-memory view of *who is working right now* (active runs with their current
  step and latest `todo` plan, active room drives), so a freshly opened page can show "@coder is
  running run_shell…" without replaying history, plus the **origin** of every session: a delegated or subagent run is
  traced back to the conversation the human started it from, so its HITL cards and progress show
  up in that conversation.
* `EventBridge` — a per-WebSocket fan-out that hands bus events (produced on worker threads) to
  the asyncio loop safely via `loop.call_soon_threadsafe` into a bounded `asyncio.Queue`.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import TYPE_CHECKING, Any

from ..sessions import SessionStore
from .views import session_todos

if TYPE_CHECKING:
    from ..runtime import Runtime

MAX_ORIGIN_DEPTH = 8
ORIGIN_CACHE_LIMIT = 5000


class LiveState:
    """Tracks active runs and room drives; resolves session origins (cached)."""

    def __init__(self, runtime: "Runtime"):
        self.rt = runtime
        self._lock = threading.Lock()
        self.runs: dict[tuple[str, str], dict[str, Any]] = {}
        self.drives: dict[str, dict[str, Any]] = {}
        self._origins: dict[tuple[str, str], dict[str, Any]] = {}
        self._delivery_parent: dict[str, tuple[str, str]] = {}
        self._token = runtime.bus.subscribe(self._on_event)

    def close(self) -> None:
        self.rt.bus.unsubscribe(self._token)

    # ------------------------------------------------------------------ event tracking
    def _on_event(self, ev: dict[str, Any]) -> None:
        t = ev.get("type", "")
        key = (ev.get("profile"), ev.get("session_id"))
        with self._lock:
            if t == "delegation.started" and ev.get("delivery_id") and key[0] and key[1]:
                self._delivery_parent[ev["delivery_id"]] = key  # type: ignore[assignment]
            if t == "run.started" and key[0] and key[1]:
                self.runs[key] = {  # type: ignore[index]
                    "profile": key[0], "session_id": key[1], "room_id": ev.get("room_id"), "run_id": ev.get("run_id"),
                    "role": ev.get("role"), "depth": ev.get("depth"), "state": "thinking", "tool": None,
                    "since": ev.get("ts", time.time()), "todos": None,
                    "plan_idle": 0,  # tool calls since the plan (todo) was last written: the UI flags a stale plan
                }
            elif t == "run.finished":
                self.runs.pop(key, None)  # type: ignore[arg-type]
            elif key in self.runs:
                run = self.runs[key]  # type: ignore[index]
                if t == "llm.request":
                    run.update(state="thinking", tool=None)
                elif t == "tool.started":
                    run.update(state="tool", tool=ev.get("tool"))
                elif t == "tool.finished":
                    run.update(state="thinking", tool=None)
                    if ev.get("tool") != "todo":
                        run["plan_idle"] = run.get("plan_idle", 0) + 1
                elif t == "hitl.requested":
                    run.update(state="waiting")
                elif t == "hitl.resolved" and run.get("state") == "waiting":
                    run.update(state="tool")
                elif t == "todo.updated":
                    run["todos"] = list(ev.get("todos") or [])
                    run["plan_idle"] = 0
            if t == "room.drive" and ev.get("room_id"):
                if ev.get("state") == "started":
                    self.drives[ev["room_id"]] = {"room_id": ev["room_id"], "lead": ev.get("lead"),
                                                  "addressed": ev.get("addressed") or [], "since": ev.get("ts")}
                else:
                    self.drives.pop(ev["room_id"], None)

    def is_running(self, profile: str, session_id: str | None = None) -> bool:
        with self._lock:
            if session_id is not None:
                return (profile, session_id) in self.runs
            return any(p == profile for p, _ in self.runs)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            runs = [dict(r) for r in self.runs.values()]
            drives = [dict(d) for d in self.drives.values()]
        for r in runs:
            r["origin"] = self.origin(r["profile"], r["session_id"])
            if r.get("todos") is None:
                # No `todo.updated` seen during this run yet: show the plan the session already keeps,
                # so a page opened mid-run sees it at once (read once, then cached on the run).
                sess = self._session(r["profile"], r["session_id"])
                r["todos"] = session_todos(sess) if sess else []
                with self._lock:
                    live = self.runs.get((r["profile"], r["session_id"]))
                    if live is not None and live.get("run_id") == r.get("run_id") and live.get("todos") is None:
                        live["todos"] = r["todos"]
        return {"runs": runs, "drives": drives}

    # ------------------------------------------------------------------ origins
    def origin(self, profile: str, session_id: str) -> dict[str, Any]:
        """The human-facing conversation a session belongs to.

        Subagent sessions point at their parent session (`meta.parent_session`); delegation
        sessions point at the session that issued the `delegate_task` call (found through the
        `delegation.started` event carrying the same delivery id). The walk is repeated so a
        delegate of a delegate resolves to the root conversation. Unknown sessions are their own
        origin."""
        key = (profile, session_id)
        with self._lock:
            hit = self._origins.get(key)
        if hit is not None:
            return hit
        cur_profile, cur_sid, kind = profile, session_id, None
        for _ in range(MAX_ORIGIN_DEPTH):
            parent = self._parent_of(cur_profile, cur_sid)
            if parent is None:
                break
            cur_profile, cur_sid, kind = parent
            if kind not in {"delegation", "subagent"}:
                break
        if kind is None:
            kind = self._kind_of(cur_profile, cur_sid)
        result = {"profile": cur_profile, "session_id": cur_sid, "kind": kind}
        with self._lock:
            if len(self._origins) > ORIGIN_CACHE_LIMIT:
                self._origins.clear()
            self._origins[key] = result
        return result

    def _session(self, profile: str, session_id: str):
        try:
            return SessionStore(self.rt.profiles.get(profile)).get(session_id)
        except KeyError:
            return None

    def _kind_of(self, profile: str, session_id: str) -> str | None:
        sess = self._session(profile, session_id)
        return sess.kind if sess else None

    def _parent_of(self, profile: str, session_id: str) -> tuple[str, str, str | None] | None:
        sess = self._session(profile, session_id)
        if sess is None:
            return None
        meta = sess.meta or {}
        if sess.kind == "subagent" and meta.get("parent_session"):
            psid = meta["parent_session"]
            return profile, psid, self._kind_of(profile, psid)
        if sess.kind == "delegation" and meta.get("delivery"):
            parent = self._delivery_parent_of(meta["delivery"])
            if parent:
                return parent[0], parent[1], self._kind_of(*parent)
        return None

    def _delivery_parent_of(self, delivery: str) -> tuple[str, str] | None:
        with self._lock:
            hit = self._delivery_parent.get(delivery)
        if hit:
            return hit
        row = None
        try:
            row = self.rt.shared.one(
                "SELECT profile, session_id FROM events WHERE type='delegation.started' "
                "AND json_extract(data, '$.delivery_id')=? LIMIT 1", (delivery,))
        except Exception:  # SQLite without JSON1: fall back to a substring match
            row = self.rt.shared.one(
                "SELECT profile, session_id FROM events WHERE type='delegation.started' AND data LIKE ? LIMIT 1",
                (f'%"{delivery}"%',))
        if row and row.get("profile") and row.get("session_id"):
            with self._lock:
                self._delivery_parent[delivery] = (row["profile"], row["session_id"])
            return row["profile"], row["session_id"]
        return None

    def enrich(self, ev: dict[str, Any]) -> dict[str, Any]:
        """Copy of an event with `origin` attached when it belongs to a session."""
        profile, sid = ev.get("profile"), ev.get("session_id")
        if not profile or not sid:
            return ev
        try:
            return {**ev, "origin": self.origin(profile, sid)}
        except Exception:
            return ev


class EventBridge:
    """Thread-safe hand-off of bus events to one WebSocket connection's asyncio loop.

    `push()` is called on whatever thread published the event; it serialises the event there (so
    the event loop only ever sees immutable strings) and schedules the enqueue on the loop. The
    queue is bounded: a client that stops reading loses the oldest events and is told to resync."""

    def __init__(self, runtime: "Runtime", live: LiveState, loop: asyncio.AbstractEventLoop, maxsize: int = 2000):
        self.rt = runtime
        self.live = live
        self.loop = loop
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)
        self._token: int | None = None
        self.dropped = 0

    def start(self) -> None:
        self._token = self.rt.bus.subscribe(self.push)

    def stop(self) -> None:
        if self._token is not None:
            self.rt.bus.unsubscribe(self._token)
            self._token = None

    def push(self, ev: dict[str, Any]) -> None:
        try:
            text = json.dumps(self.live.enrich(ev), ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return
        try:
            self.loop.call_soon_threadsafe(self._offer, text)
        except RuntimeError:  # the loop is closed: the connection is gone
            pass

    def _offer(self, text: str) -> None:
        if self.queue.full():
            self.dropped += 1
            notify = self.dropped == 1 or self.dropped % 100 == 0
            for _ in range(2 if notify else 1):
                try:
                    self.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            if notify:
                self.queue.put_nowait(json.dumps({"type": "stream.overflow", "dropped": self.dropped, "ts": time.time()}))
        try:
            self.queue.put_nowait(text)
        except asyncio.QueueFull:  # pragma: no cover - only if maxsize < 2
            pass
