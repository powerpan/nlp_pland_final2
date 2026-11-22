"""Process-wide runtime: profile registry, shared state, event bus, HITL broker, sandboxes, locks."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from .budget import Ledger
from .config import AgentSettings, pland_home
from .events import EventBus
from .hitl import BrokerHITL, HITLChannel
from .profiles import Profile, ProfileManager
from .sandbox import Backend, make_backend
from .sessions import SessionStore
from .store import shared_db


class Runtime:
    def __init__(self, root: Path | None = None, *, hitl: HITLChannel | None = None):
        self.root = (root or pland_home()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.profiles = ProfileManager(self.root)
        self.shared = shared_db(self.root)
        self.bus = EventBus(self.shared)
        self.broker = BrokerHITL(self.shared, self.bus.publish)
        self.ledger = Ledger(self.shared)
        self.default_hitl: HITLChannel = hitl or self.broker
        self._locks: dict[tuple[str, str], threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._cancelled: set[tuple[str, str]] = set()
        self._cancel_all = False
        self._backends: dict[tuple[str, str], Backend] = {}
        self._threads: list[threading.Thread] = []
        self._reflections: list[threading.Thread] = []

    # ------------------------------------------------------------------ sessions & locks
    def session_lock(self, profile: str, session_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault((profile, session_id), threading.Lock())

    def is_busy(self, profile: str, session_id: str) -> bool:
        return self.session_lock(profile, session_id).locked()

    def cancel(self, profile: str, session_id: str) -> None:
        self._cancelled.add((profile, session_id))
        self.bus.publish("run.cancel_requested", profile=profile, session_id=session_id)

    def is_cancelled(self, profile: str, session_id: str) -> bool:
        return self._cancel_all or (profile, session_id) in self._cancelled

    def cancel_everything(self, on: bool = True) -> None:
        """Stop every running agent at its next step (used by the evaluation harness on timeout)."""
        self._cancel_all = on

    def clear_cancel(self, profile: str, session_id: str) -> None:
        self._cancelled.discard((profile, session_id))

    def recover_interrupted(self) -> list[dict[str, Any]]:
        """Find sessions left 'running' by a process that no longer exists (crash, restart) and mark
        them 'interrupted'. They can be continued with `Agent.resume()`, which completes any dangling
        tool calls (re-asking the human where needed) and carries on from the stored transcript."""
        import os

        found = []
        for prof in self.profiles.list():
            store = SessionStore(prof)
            for sess in store.list(limit=500):
                if sess.status not in ("running", "interrupted"):
                    continue
                pid = sess.meta.get("pid")
                alive = False
                if pid and pid != os.getpid():
                    try:
                        os.kill(int(pid), 0)
                        alive = True
                    except (OSError, ValueError):
                        alive = False
                if alive or self.is_busy(prof.name, sess.id):
                    continue
                if sess.status == "running":
                    store.update(sess.id, status="interrupted")
                found.append({"profile": prof.name, "session_id": sess.id, "title": sess.title, "kind": sess.kind})
        return found

    # ------------------------------------------------------------------ sandboxes
    def backend_for(self, profile: Profile, settings: AgentSettings) -> Backend:
        key = (profile.name, settings.sandbox.backend)
        with self._locks_guard:
            backend = self._backends.get(key)
            if backend is None:
                backend = make_backend(settings.sandbox, profile.name, profile.workspace, deny_roots=[self.root])
                self._backends[key] = backend
            return backend

    def shutdown(self) -> None:
        for backend in self._backends.values():
            stop = getattr(backend, "shutdown", None)
            if stop:
                stop()

    # ------------------------------------------------------------------ agents
    def agent(self, profile: str | Profile, session_id: str | None = None, **kw: Any):
        from .agent import Agent

        prof = profile if isinstance(profile, Profile) else self.profiles.get(profile)
        if session_id is None:
            session_id = SessionStore(prof).create(title="", kind=kw.pop("kind", "chat")).id
        else:
            kw.pop("kind", None)
        return Agent(self, prof, session_id, **kw)

    def track_reflection(self, th: threading.Thread) -> None:
        with self._locks_guard:
            self._reflections = [t for t in self._reflections if t.is_alive()] + [th]

    def wait_reflections(self, timeout: float = 120.0) -> None:
        """Block until background reflections have been written (evaluation, one-shot CLI exit)."""
        import time as _time

        deadline = _time.time() + timeout
        while True:
            with self._locks_guard:
                pending = [t for t in self._reflections if t.is_alive()]
            if not pending:
                return
            pending[0].join(max(0.0, deadline - _time.time()))
            if _time.time() >= deadline:
                return

    def spawn(self, fn: Callable[[], Any], name: str = "pland-run") -> threading.Thread:
        th = threading.Thread(target=fn, name=name, daemon=True)
        th.start()
        self._threads = [t for t in self._threads if t.is_alive()] + [th]
        return th
