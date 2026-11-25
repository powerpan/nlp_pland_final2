"""Regression tests for review findings in the agent loop, compaction, room budget, provider client, HITL broker
and memory files. Scripted models and mocked transports only — no network."""

from __future__ import annotations

import json
import threading
import time

import httpx
import pytest

from pland.agent import PRUNED_TOOL_OUTPUT, Agent
from pland.budget import Budget
from pland.config import ModelConfig
from pland.llm.base import LLMError
from pland.llm.openai_compat import OpenAICompatClient
from pland.memory import NotesMemory, SkillStore
from pland.sessions import SessionStore
from pland.store import dumps, now


# 1 ----------------------------------------------------------------------------------------------- progress guard
def test_write_file_with_object_content_does_not_crash_the_run(rt, script):
    script([
        {"tool_calls": [("write_file", {"path": "cfg.json", "content": {"a": 1, "b": [1, 2]}})]},
        {"tool_calls": [("write_file", {"path": "list.json", "content": [1, 2]})]},
        {"content": "wrote them"},
    ])
    agent = rt.agent("default", reflect=False)
    res = agent.run("write the config files")
    assert res.status == "completed", res.text
    ws = rt.profiles.get("default").workspace
    assert json.loads((ws / "cfg.json").read_text()) == {"a": 1, "b": [1, 2]}


# 2 ----------------------------------------------------------------------------------------------- compaction
def test_compaction_keeps_the_newest_tool_result_in_a_long_tool_chain(rt, script):
    ws = rt.profiles.get("default").workspace
    for i in range(8):
        (ws / f"f{i}.txt").write_text("".join(f"line {i} row {j} some padding text here\n" for j in range(150)))
    seen = {}

    def inspect(messages, tools):
        seen["messages"] = messages
        return {"content": "done"}

    script([{"tool_calls": [("read_file", {"path": f"f{i}.txt"})]} for i in range(8)] + [inspect])
    agent = rt.agent("default", reflect=False)
    agent.settings.context_char_budget = 30_000
    agent.settings.stream = False
    assert agent.run("read all files").status == "completed"
    tools = [m for m in seen["messages"] if m["role"] == "tool"]
    assert tools[-1]["content"] != PRUNED_TOOL_OUTPUT and "line 7 row 0" in tools[-1]["content"]
    assert any(m["content"] == PRUNED_TOOL_OUTPUT for m in tools[:-1])  # older outputs were still cleared
    assert SessionStore(rt.profiles.get("default")).get(agent.session_id).meta.get("pruned_upto")


def test_phase2_without_a_user_turn_in_the_tail_keeps_the_task(rt, script):
    seen = {}

    def inspect(messages, tools):
        seen["messages"] = messages
        return {"content": "done"}

    script([inspect])
    prof = rt.profiles.get("default")
    store = SessionStore(prof)
    sid = store.create().id
    store.append(sid, {"role": "system", "content": "sys (@default)"})
    store.append(sid, {"role": "user", "content": "TASK-7Q: audit every module"}, meta={"display": "TASK-7Q"})
    for i in range(30):  # a long tool-call chain with bulky assistant text: pruning tool outputs cannot help
        store.append(sid, {"role": "assistant", "content": f"thinking {i} " + "z" * 1500, "tool_calls": [
            {"id": f"c{i}", "type": "function", "function": {"name": "list_files", "arguments": "{}"}}]})
        store.append(sid, {"role": "tool", "tool_call_id": f"c{i}", "content": f"result {i}"})
    agent = rt.agent("default", session_id=sid, reflect=False)
    agent.settings.context_char_budget = 20_000
    agent.settings.stream = False
    agent.run(None)
    meta = store.get(sid).meta
    assert meta.get("compacted_upto") and meta.get("task_note", "").startswith("TASK-7Q")
    view = seen["messages"]
    assert view[1]["role"] == "user" and "TASK-7Q: audit every module" in view[1]["content"]
    assert view[-2]["role"] == "assistant" and view[-2]["content"].startswith("thinking 29")
    assert view[-1] == {"role": "tool", "tool_call_id": "c29", "content": "result 29"}


def test_tail_start_never_splits_a_group_and_keeps_the_newest_one(rt):
    agent = rt.agent("default", reflect=False)

    def rec(role, size=10):
        return {"message": {"role": role, "content": "x" * size}, "meta": {}}

    live = [rec("user"), rec("assistant"), rec("tool", 500), rec("assistant"), rec("tool", 5000), rec("tool", 5000)]
    assert agent._tail_start(live, 1000) == 3  # the newest group alone exceeds the budget: keep it whole
    live = [rec("user"), rec("assistant"), rec("tool", 3000), rec("assistant"), rec("tool", 100), rec("assistant"),
            rec("tool", 100)]
    assert agent._tail_start(live, 1000) == 3  # cut at the group boundary that keeps the tail near the budget
    live = [rec("user"), rec("assistant"), rec("tool", 3000), rec("user"), rec("assistant"), rec("tool", 100)]
    assert agent._tail_start(live, 1000) == 3  # a user message in the tail is still preferred


# 3 ----------------------------------------------------------------------------------------------- room lead budget
def test_room_lead_writes_a_summary_at_the_budget_limit(rt, script):
    rt.profiles.create("lead", title="Lead", description="plans")
    rt.profiles.update("lead", settings={"max_run_calls": 5})  # the drive gets 10 calls
    ws = rt.profiles.get("lead").workspace
    for i in range(20):
        (ws / f"n{i}.txt").write_text(f"note {i}\n")

    def step(i):
        def fn(messages, tools):
            if "run budget is nearly exhausted" in str(messages[-1].get("content")):
                return {"content": "LEAD SUMMARY: read the notes"}
            return {"tool_calls": [("read_file", {"path": f"n{i}.txt"})]}
        return fn

    script({"lead": [step(i) for i in range(20)]})
    room = rt.rooms.create("solo", ["lead"], lead="lead")
    rt.rooms.send(room["id"], "do the work", background=False)
    posts = [m["content"] for m in rt.rooms.messages(room["id"]) if m["speaker"] == "lead"]
    assert posts == ["LEAD SUMMARY: read the notes"]


def test_budget_root_flag(rt):
    prof = rt.profiles.get("default")
    sid = SessionStore(prof).create().id
    shared = Budget()
    assert Agent(rt, prof, sid).is_root
    assert not Agent(rt, prof, sid, budget=shared).is_root
    lead = Agent(rt, prof, sid, budget=shared, budget_root=True)
    assert lead.is_root and lead.budget is shared


# 4 ----------------------------------------------------------------------------------------------- provider client
def _client(handler, retries=1):
    return OpenAICompatClient(ModelConfig(provider="deepseek", model="deepseek-flash", api_key="fixture",
                                          max_retries=retries), transport=httpx.MockTransport(handler))


def test_non_json_200_is_a_retryable_llm_error(rt, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    hits = []

    def handler(request):
        hits.append(1)
        return httpx.Response(200, text="<html>gateway</html>")

    with pytest.raises(LLMError) as err:
        _client(handler).chat([{"role": "user", "content": "hi"}])
    assert err.value.retryable and len(hits) == 2
    with pytest.raises(LLMError) as err:  # streamed: a 200 that carries no events at all
        _client(handler).chat([{"role": "user", "content": "hi"}], on_delta=lambda k, t: None)
    assert err.value.retryable

    agent = rt.agent("default", llm=_client(handler, retries=0), reflect=False)
    agent.settings.stream = False
    res = agent.run("hi")
    assert res.status == "error" and res.text.startswith("Model error:")
    assert [r["ok"] for r in rt.shared.query("SELECT ok FROM llm_calls")] == [0]


def test_provider_error_bodies_are_redacted(monkeypatch):
    fake = "sk" + "-" + "Abc123" * 5

    def handler(request):
        msg = f"Authentication Fails, Your api key: ****wxyz is invalid; also {fake}"
        return httpx.Response(401, json={"error": {"message": msg}})

    with pytest.raises(LLMError) as err:
        _client(handler).chat([{"role": "user", "content": "hi"}])
    text = str(err.value)
    assert err.value.status == 401 and "Authentication Fails" in text
    assert "wxyz" not in text and fake not in text and "[redacted]" in text


# 5 ----------------------------------------------------------------------------------------------- HITL race
def _pending_row(rt, rid, status="pending"):
    rt.shared.execute(
        "INSERT INTO hitl_requests(id, profile, session_id, room_id, kind, payload, status, created) VALUES (?,?,?,?,?,?,?,?)",
        (rid, "default", "s1", None, "clarify", dumps({"question": "q?"}), status, now()))


def test_answer_after_timeout_settled_it_is_refused(rt, monkeypatch):
    broker = rt.broker
    _pending_row(rt, "h_race", status="expired")
    real_one = broker.db.one
    stale = {"done": False}

    def one(sql, params=()):  # the answer reads the row just before the timeout marks it expired
        row = real_one(sql, params)
        if not stale["done"] and row:
            stale["done"] = True
            row = {**row, "status": "pending"}
        return row

    monkeypatch.setattr(broker.db, "one", one)
    with pytest.raises(ValueError, match="already expired"):
        broker.answer("h_race", text="late")
    assert real_one("SELECT status, answer FROM hitl_requests WHERE id='h_race'")["status"] == "expired"


def test_answer_landing_as_the_wait_times_out_is_returned(rt, monkeypatch):
    from pland.hitl import HITLRequest

    broker = rt.broker
    real_execute = broker.db.execute

    def execute(sql, params=()):
        if sql.startswith("UPDATE hitl_requests SET status='expired'"):  # the human answers right now
            real_execute("UPDATE hitl_requests SET status='answered', answer=? WHERE id=?",
                         (dumps({"text": "just in time", "choice": None}), params[0]))
        return real_execute(sql, params)

    monkeypatch.setattr(broker.db, "execute", execute)
    ans = broker.request(HITLRequest("clarify", "default", "s1", "q?"), timeout=0.01)
    assert ans.status == "answered" and ans.text == "just in time"


# 6 ----------------------------------------------------------------------------------------------- room drive failure
def test_failed_drive_still_publishes_settled(rt, monkeypatch):
    rt.profiles.create("solo", title="Solo")
    room = rt.rooms.create("r", ["solo"], lead="solo")
    events = []
    token = rt.bus.subscribe(lambda ev: events.append(ev) if ev["type"] == "room.drive" else None)

    def boom(*a, **k):
        raise RuntimeError("drive failed")

    monkeypatch.setattr(rt.rooms, "_member_turn", boom)
    try:
        with pytest.raises(RuntimeError, match="drive failed"):
            rt.rooms.send(room["id"], "go", background=False)
    finally:
        rt.bus.unsubscribe(token)
    assert [e["state"] for e in events] == ["started", "settled"]


# 7 ----------------------------------------------------------------------------------------------- memory files
def test_concurrent_note_writes_lose_nothing(rt, monkeypatch):
    prof = rt.profiles.get("default")
    real_entries = NotesMemory.entries

    def slow_entries(self, target):  # widen the read-modify-write window
        out = real_entries(self, target)
        time.sleep(0.01)
        return out

    monkeypatch.setattr(NotesMemory, "entries", slow_entries)
    monkeypatch.setattr(NotesMemory, "similar", lambda self, target, content, threshold=0.6: None)
    words = ["apple", "banana", "cherry", "damson", "elder", "fig", "grape", "hazel"]
    threads = [threading.Thread(target=NotesMemory(prof).add, args=("memory", f"likes {w}")) for w in words]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    monkeypatch.setattr(NotesMemory, "entries", real_entries)
    assert sorted(NotesMemory(prof).entries("memory")) == sorted(f"likes {w}" for w in words)
    assert not list(prof.memories_dir.glob("*.tmp"))


def test_concurrent_skill_usage_bumps_lose_nothing(rt, monkeypatch):
    prof = rt.profiles.get("default")
    SkillStore(prof).save("deploy", "how to deploy", "1. push")
    real_usage = SkillStore.usage

    def slow_usage(self):
        out = real_usage(self)
        time.sleep(0.01)
        return out

    monkeypatch.setattr(SkillStore, "usage", slow_usage)
    threads = [threading.Thread(target=SkillStore(prof).view, args=("deploy",)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    monkeypatch.setattr(SkillStore, "usage", real_usage)
    assert SkillStore(prof).usage()["deploy"]["views"] == 8


# 8 ----------------------------------------------------------------------------------------------- announce-only reply
def test_an_announce_only_first_reply_is_nudged_once_to_act(rt, script):
    # Real hard-suite run: "I'll start by setting up the plan…" with no tool call ended the run with nothing built.
    script([
        {"content": "I'll start by setting up the plan and understanding the exact spec."},
        {"tool_calls": [("write_file", {"path": "ttl.py", "content": "x = 1\n"})]},
        {"content": "Wrote ttl.py."},
    ])
    agent = rt.agent("default", reflect=False)
    res = agent.run("build the cache")
    assert res.status == "completed" and res.text == "Wrote ttl.py."
    assert (rt.profiles.get("default").workspace / "ttl.py").exists()


def test_the_nudge_happens_only_once_and_not_for_plain_answers(rt, script):
    script([{"content": "Let me think about that."}, {"content": "Let me be brief: 4."}])
    res = rt.agent("default", reflect=False).run("what is 2+2?")
    assert res.text == "Let me be brief: 4."  # nudged once, then the reply stands
    script([{"content": "2 + 2 = 4."}])
    assert rt.agent("default", reflect=False).run("what is 2+2?").text == "2 + 2 = 4."  # no announcement: no nudge
    script([{"tool_calls": [("list_dir", {})]}, {"content": "I'll summarise: the folder is empty."}])
    assert rt.agent("default", reflect=False).run("look around").text.startswith("I'll summarise")  # acted already
