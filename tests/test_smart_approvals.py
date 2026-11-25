from __future__ import annotations

import pytest

from pland.hitl import ScriptedHITL
from pland.llm.base import LLMResponse
from pland.tools.files import delete_file
from pland.tools.registry import ToolError


@pytest.mark.parametrize(
    ("answer", "deleted", "human_requests"),
    [("APPROVE", True, 0), ("DENY", False, 0), ("ESCALATE", False, 1), ("unexpected", False, 1)],
)
def test_smart_file_delete_uses_guard_and_returns_result(rt, monkeypatch, answer, deleted, human_requests):
    rt.profiles.update("default", settings={"approvals": {"mode": "smart"}})
    hitl = ScriptedHITL(default_choice="deny")
    agent = rt.agent("default", hitl=hitl)
    target = agent.workspace / "scratch-output.txt"
    target.write_text("temporary output")
    calls = []

    def review(messages, tools=None, **kwargs):
        calls.append((messages, kwargs))
        return LLMResponse(content=answer)

    monkeypatch.setattr(agent, "chat", review)
    if deleted:
        result = delete_file(agent._context(), {"path": target.name})
        assert result == "Deleted scratch-output.txt"
    else:
        with pytest.raises(ToolError, match="not permitted"):
            delete_file(agent._context(), {"path": target.name})
    assert target.exists() is not deleted
    assert len(hitl.log) == human_requests
    assert len(calls) == 1
    assert str(target) in calls[0][0][-1]["content"]
    assert calls[0][1]["thinking"] is False


def test_smart_guard_failure_requests_human(rt, monkeypatch):
    rt.profiles.update("default", settings={"approvals": {"mode": "smart"}})
    hitl = ScriptedHITL(default_choice="deny")
    agent = rt.agent("default", hitl=hitl)
    target = agent.workspace / "scratch-output.txt"
    target.write_text("temporary output")

    def unavailable(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(agent, "chat", unavailable)
    with pytest.raises(ToolError, match="not permitted"):
        delete_file(agent._context(), {"path": target.name})
    assert target.exists()
    assert len(hitl.log) == 1


@pytest.mark.parametrize("category", ["git:push", "shell:touch credential files", "shell:run as superuser"])
def test_smart_sensitive_operations_still_request_human(rt, monkeypatch, category):
    rt.profiles.update("default", settings={"approvals": {"mode": "smart"}})
    hitl = ScriptedHITL(default_choice="deny")
    agent = rt.agent("default", hitl=hitl)

    def unexpected(*args, **kwargs):
        pytest.fail("sensitive operations must be decided by the human")

    monkeypatch.setattr(agent, "chat", unexpected)
    decision = agent._context().approvals.require(category, "Sensitive operation", "test only; never executed")
    assert not decision.allowed
    assert len(hitl.log) == 1
