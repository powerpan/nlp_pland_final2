"""Process-wide runtime: profile registry, shared state, event bus, sandboxes, locks."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from .budget import Ledger
from .config import AgentSettings, pland_home
from .events import EventBus
from .hitl import HITLChannel, NoHumanHITL
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
        self.ledger = Ledger(self.shared)
        self.default_hitl: HITLChannel = hitl or NoHumanHITL()
        self._locks: dict[tuple[str, str], threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._cancelled: set[tuple[str, str]] = set()
        self._backends: dict[tuple[str, str], Backend] = {}
        self._threads: list[threading.Thread] = []

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
        return (profile, session_id) in self._cancelled

    def clear_cancel(self, profile: str, session_id: str) -> None:
        self._cancelled.discard((profile, session_id))

    # ------------------------------------------------------------------ sandboxes
    def backend_for(self, profile: Profile, settings: AgentSettings) -> Backend:
        key = (profile.name, settings.sandbox.backend)
        with self._locks_guard:
            backend = self._backends.get(key)
            if backend is None:
                backend = make_backend(settings.sandbox, profile.name, profile.workspace)
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

    def spawn(self, fn: Callable[[], Any], name: str = "pland-run") -> threading.Thread:
        th = threading.Thread(target=fn, name=name, daemon=True)
        th.start()
        self._threads = [t for t in self._threads if t.is_alive()] + [th]
        return th
