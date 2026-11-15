"""Request and answer contracts plus the unattended channel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .store import new_id

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
