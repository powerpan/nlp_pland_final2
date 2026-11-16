"""In-process event bus.

Everything observable (model calls, tool calls, HITL requests, memory changes, delegations, room
messages, task-board updates) is published here. Subscribers include the web UI's WebSocket fan-out,
the CLI renderer and the evaluation trace recorder. Events are also appended to shared.db so runs
can be analysed after the fact.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from .store import DB, dumps

Subscriber = Callable[[dict[str, Any]], None]


class EventBus:
    def __init__(self, db: DB | None = None):
        self._db = db
        self._subs: dict[int, Subscriber] = {}
        self._next = 0
        self._lock = threading.Lock()

    def subscribe(self, fn: Subscriber) -> int:
        with self._lock:
            self._next += 1
            self._subs[self._next] = fn
            return self._next

    def unsubscribe(self, token: int) -> None:
        with self._lock:
            self._subs.pop(token, None)

    def publish(self, type: str, **fields: Any) -> dict[str, Any]:
        event = {"type": type, "ts": time.time(), **fields}
        if self._db is not None:
            try:
                self._db.execute(
                    "INSERT INTO events(ts, type, profile, session_id, room_id, run_id, data) VALUES (?,?,?,?,?,?,?)",
                    (
                        event["ts"],
                        type,
                        fields.get("profile"),
                        fields.get("session_id"),
                        fields.get("room_id"),
                        fields.get("run_id"),
                        dumps(fields),
                    ),
                )
            except Exception:  # the log is best-effort; never break a run because of it
                pass
        with self._lock:
            subs = list(self._subs.values())
        for fn in subs:
            try:
                fn(event)
            except Exception:
                pass
        return event
