"""Human-in-the-loop channels.

A tool that needs a human (clarification via `ask_user`, or an approval before a permissioned
operation) calls `channel.request(req)`. The run blocks at that point *inside* the tool call, so
when the answer arrives the agent continues exactly where it stopped — nothing restarts. Every
request is also persisted in shared.db; if the process dies while waiting, the session keeps a
dangling tool call and `Agent.resume()` re-asks and continues from the stored transcript.

Channels:
* `BrokerHITL`  — web UI / API: requests become cards; answered through `answer()`.
* `ConsoleHITL` — interactive CLI prompt.
* `ScriptedHITL`— evaluation harness: a simulated user with scripted replies and approval policy.
* `NoHumanHITL` — unattended runs: clarifications get "no human available", approvals are denied.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from .errors import NotFound
from .store import DB, dumps, loads, new_id, now

APPROVAL_CHOICES = ("once", "session", "always", "deny")


@dataclass
class HITLRequest:
    kind: str  # clarify | approval
    profile: str
    session_id: str
    question: str
    options: list[str] = field(default_factory=list)
    detail: str = ""
    category: str = ""
    room_id: str | None = None
    run_id: str | None = None
    id: str = field(default_factory=lambda: new_id("h_"))

    def payload(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "options": self.options,
            "detail": self.detail,
            "category": self.category,
            "run_id": self.run_id,
        }


@dataclass
class HITLAnswer:
    status: str  # answered | timeout | unavailable | cancelled
    text: str = ""
    choice: str | None = None  # approvals: once | session | always | deny

    @property
    def approved(self) -> bool:
        return self.status == "answered" and self.choice in {"once", "session", "always"}


class HITLChannel:
    interactive = True

    def request(self, req: HITLRequest, timeout: float | None = None) -> HITLAnswer:  # pragma: no cover
        raise NotImplementedError


class NoHumanHITL(HITLChannel):
    interactive = False

    def __init__(self, approve: bool = False):
        self.approve = approve

    def request(self, req, timeout=None) -> HITLAnswer:
        if req.kind == "approval":
            return HITLAnswer("answered", choice="once" if self.approve else "deny",
                              text="auto-approved (unattended)" if self.approve else "no human available; denied")
        return HITLAnswer("unavailable", text="No human is available right now. Make the most reasonable assumption, state it explicitly, and continue.")


class BrokerHITL(HITLChannel):
    """Persisted request/answer broker shared by the web server and resumable runs."""

    def __init__(self, db: DB, publish: Callable[..., Any] | None = None):
        self.db = db
        self.publish = publish or (lambda *a, **k: None)
        self._waiters: dict[str, tuple[threading.Event, list[HITLAnswer]]] = {}
        self._lock = threading.Lock()

    def request(self, req, timeout=None) -> HITLAnswer:
        ev = threading.Event()
        box: list[HITLAnswer] = []
        with self._lock:
            self._waiters[req.id] = (ev, box)
        self.db.execute(
            "INSERT INTO hitl_requests(id, profile, session_id, room_id, kind, payload, status, created) VALUES (?,?,?,?,?,?,?,?)",
            (req.id, req.profile, req.session_id, req.room_id, req.kind, dumps(req.payload()), "pending", now()),
        )
        self.publish("hitl.requested", profile=req.profile, session_id=req.session_id, room_id=req.room_id,
                     run_id=req.run_id, request={"id": req.id, "kind": req.kind, **req.payload()})
        ev.wait(timeout)
        with self._lock:
            self._waiters.pop(req.id, None)
        if box:  # answered, possibly just as the wait timed out
            return box[0]
        if not self.db.execute("UPDATE hitl_requests SET status='expired' WHERE id=? AND status='pending'",
                               (req.id,)).rowcount:
            # Settled by someone else between the wait and this update: an answer that landed counts.
            row = self.db.one("SELECT status, answer FROM hitl_requests WHERE id=?", (req.id,))
            if row and row["status"] == "answered":
                a = loads(row["answer"], {})
                return HITLAnswer("answered", text=a.get("text") or "", choice=a.get("choice"))
        else:
            self.publish("hitl.resolved", profile=req.profile, session_id=req.session_id, room_id=req.room_id,
                         request_id=req.id, status="timeout")
        return HITLAnswer("timeout", text="The human did not answer in time.")

    def answer(self, request_id: str, *, text: str = "", choice: str | None = None) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM hitl_requests WHERE id=?", (request_id,))
        if row is None:
            raise NotFound(request_id)
        if row["status"] != "pending":
            raise ValueError(f"request {request_id} is already {row['status']}")
        if row["kind"] == "approval":
            if choice not in APPROVAL_CHOICES:
                raise ValueError(f"approval choice must be one of {APPROVAL_CHOICES}")
        ans = HITLAnswer("answered", text=text, choice=choice)
        # Conditional: a timeout (or a second answer) may have settled the request since it was read above.
        cur = self.db.execute(
            "UPDATE hitl_requests SET status='answered', answer=?, answered=? WHERE id=? AND status='pending'",
            (dumps({"text": text, "choice": choice}), now(), request_id),
        )
        if not cur.rowcount:
            now_row = self.db.one("SELECT status FROM hitl_requests WHERE id=?", (request_id,)) or {}
            raise ValueError(f"request {request_id} is already {now_row.get('status', 'settled')}")
        with self._lock:
            waiter = self._waiters.get(request_id)
        if waiter:
            waiter[1].append(ans)
            waiter[0].set()
        self.publish("hitl.resolved", profile=row["profile"], session_id=row["session_id"], room_id=row["room_id"],
                     request_id=request_id, status="answered", choice=choice, text=text)
        return {"id": request_id, "live": waiter is not None, "profile": row["profile"], "session_id": row["session_id"]}

    def is_live(self, request_id: str) -> bool:
        with self._lock:
            return request_id in self._waiters

    def pending(self, *, room_id: str | None = None, profile: str | None = None) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM hitl_requests WHERE status='pending'", []
        if room_id:
            sql += " AND room_id=?"
            params.append(room_id)
        if profile:
            sql += " AND profile=?"
            params.append(profile)
        rows = self.db.query(sql + " ORDER BY created", params)
        for r in rows:
            r["payload"] = loads(r["payload"], {})
            r["live"] = self.is_live(r["id"])
        return rows

    def cancel_orphans(self) -> int:
        """Called at startup: requests whose waiting thread died can no longer be answered live."""
        rows = self.db.query("SELECT id FROM hitl_requests WHERE status='pending'")
        orphans = [r["id"] for r in rows if not self.is_live(r["id"])]
        for rid in orphans:
            self.db.execute("UPDATE hitl_requests SET status='cancelled' WHERE id=?", (rid,))
        return len(orphans)


class ConsoleHITL(HITLChannel):
    def __init__(self, console=None):
        self._lock = threading.Lock()
        self.console = console

    def _print(self, text: str) -> None:
        if self.console is not None:
            self.console.print(text)
        else:
            print(text)

    def request(self, req, timeout=None) -> HITLAnswer:
        with self._lock:  # parallel delegations must not interleave prompts
            who = f"@{req.profile}"
            if req.kind == "approval":
                self._print(f"\n[bold yellow]⚠ {who} requests permission:[/] {req.question}")
                if req.detail:
                    self._print(f"[dim]{req.detail}[/]")
                while True:
                    raw = input("Allow? [o]nce / [s]ession / [a]lways / [d]eny > ").strip().lower()
                    mapping = {"o": "once", "once": "once", "y": "once", "yes": "once", "s": "session", "session": "session",
                               "a": "always", "always": "always", "d": "deny", "deny": "deny", "n": "deny", "no": "deny"}
                    if raw in mapping:
                        return HITLAnswer("answered", choice=mapping[raw])
            self._print(f"\n[bold cyan]? {who} asks:[/] {req.question}")
            for i, opt in enumerate(req.options, 1):
                self._print(f"  {i}. {opt}")
            raw = input("Your answer > ").strip()
            if raw.isdigit() and req.options and 1 <= int(raw) <= len(req.options):
                raw = req.options[int(raw) - 1]
            return HITLAnswer("answered", text=raw)


@dataclass
class ScriptedRule:
    match: str  # regex matched against question/detail/category (case-insensitive)
    reply: str | None = None  # clarification reply
    choice: str | None = None  # approval choice


class ScriptedHITL(HITLChannel):
    """Simulated user for automated evaluation. Every interaction is logged for the report."""

    interactive = True

    def __init__(self, rules: list[ScriptedRule] | None = None, *, default_reply: str | None = None,
                 default_choice: str = "once"):
        self.rules = rules or []
        self.default_reply = default_reply
        self.default_choice = default_choice
        self.log: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def request(self, req, timeout=None) -> HITLAnswer:
        haystack = " ".join([req.question, req.detail, req.category])
        ans: HITLAnswer | None = None
        for rule in self.rules:
            if re.search(rule.match, haystack, re.IGNORECASE):
                if req.kind == "approval" and rule.choice:
                    ans = HITLAnswer("answered", choice=rule.choice)
                    break
                if req.kind == "clarify" and rule.reply is not None:
                    ans = HITLAnswer("answered", text=rule.reply)
                    break
        if ans is None:
            if req.kind == "approval":
                ans = HITLAnswer("answered", choice=self.default_choice)
            elif self.default_reply is not None:
                ans = HITLAnswer("answered", text=self.default_reply)
            else:
                ans = HITLAnswer("unavailable", text="No further information is available; make a reasonable assumption and state it.")
        with self._lock:
            self.log.append({"kind": req.kind, "profile": req.profile, "question": req.question,
                             "category": req.category, "answer": ans.text, "choice": ans.choice, "ts": now()})
        return ans
