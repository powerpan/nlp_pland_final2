"""Decision interface for permissioned operations before interactive approval."""

from dataclasses import dataclass


@dataclass
class Decision:
    allowed: bool
    reason: str


class ApprovalGate:
    """Sensitive operations remain unavailable until an approval channel is integrated."""

    def __init__(self, profile, cfg, hitl, session_id, *, room_id=None, run_id=None, publish=None):
        pass

    def require(self, category: str, summary: str, detail: str = "") -> Decision:
        return Decision(False, "interactive approvals are unavailable at this stage")
