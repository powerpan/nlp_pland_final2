"""Session-lock waits and bot-to-bot messaging: stop during a wait, cross-chain message cycles, message timeouts.
All model calls are scripted (RoutingLLM in conftest)."""

from __future__ import annotations

import threading
import time

from pland.agent import lock_registry
from pland.sessions import SessionStore
from pland.tools import team as team_tools


def make_pair(rt):
    rt.profiles.create("lead", title="Lead", description="plans")
    rt.profiles.create("writer", title="Writer", description="writes")


def wait_until(fn, timeout: float = 5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fn():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met in time")


def run_in_thread(fn):
    box: dict = {}
    th = threading.Thread(target=lambda: box.setdefault("result", fn()), daemon=True)
    th.start()
    return th, box


def dangling(store: SessionStore, sid: str) -> list[str]:
    msgs = store.messages(sid)
    answered = {m.get("tool_call_id") for m in msgs if m["role"] == "tool"}
    return [tc["id"] for m in msgs if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])
            if tc["id"] not in answered]


def test_stop_during_lock_wait_returns_promptly_and_is_not_lost(rt, script):
    script([{"content": "never reached"}])
    agent = rt.agent("default")
    sid = agent.session_id
    lock = rt.session_lock("default", sid)
    lock.acquire()  # another run holds the session
    try:
        th, box = run_in_thread(lambda: agent.run("queued message"))
        wait_until(lambda: lock_registry(rt).waiting)
        t0 = time.time()
        rt.cancel("default", sid)
        th.join(3)
        assert not th.is_alive() and time.time() - t0 < 2
        res = box["result"]
        assert res.status == "cancelled" and res.not_started == "cancelled"
        # the stop request still stands for the run holding the session; nothing was written to the transcript
        assert rt.is_cancelled("default", sid)
        assert SessionStore(rt.profiles.get("default")).messages(sid) == []
        assert not lock_registry(rt).waiting
    finally:
        lock.release()


def test_stop_arriving_during_wait_survives_the_acquisition(rt, script):
    script([{"content": "should not run"}])
    agent = rt.agent("default")
    sid = agent.session_id
    lock = rt.session_lock("default", sid)
    lock.acquire()
    th, box = run_in_thread(lambda: agent.run("queued"))
    wait_until(lambda: lock_registry(rt).waiting)
    # the stop and the release race: whichever the waiter sees first, it must end cancelled
    rt.cancel("default", sid)
    lock.release()
    th.join(3)
    assert box["result"].status == "cancelled"


def test_stopping_the_caller_ends_a_message_wait(rt, script):
    make_pair(rt)
    script({"lead": [{"tool_calls": [("message_agent", {"target": "writer", "message": "hi"})]},
                     {"content": "should not get here"}]})
    writer_sid = rt.profiles.get("writer").canonical_chat_id()
    wlock = rt.session_lock("writer", writer_sid)
    wlock.acquire()  # the writer is busy with something else
    try:
        lead = rt.agent("lead")
        th, box = run_in_thread(lambda: lead.run("ask the writer"))
        wait_until(lambda: lock_registry(rt).waiting)
        t0 = time.time()
        rt.cancel("lead", lead.session_id)
        th.join(3)
        assert not th.is_alive() and time.time() - t0 < 2
        assert box["result"].status == "cancelled"
        store = SessionStore(rt.profiles.get("lead"))
        assert dangling(store, lead.session_id) == []
        assert SessionStore(rt.profiles.get("writer")).messages(writer_sid) == []
    finally:
        wlock.release()


def test_cross_chain_message_cycle_fails_fast(rt, script):
    make_pair(rt)
    started = {"lead": threading.Event(), "writer": threading.Event()}
    other = {"lead": "writer", "writer": "lead"}

    def bot(name):
        def step(msgs, tools):
            last = msgs[-1]
            if last["role"] == "tool":
                return {"content": f"{name} finished: {last['content'][:300]}"}
            if str(last.get("content") or "").startswith("Message from"):
                return {"content": f"reply from {name}"}
            started[name].set()  # both top-level runs hold their own chat before either sends its message
            assert started[other[name]].wait(5)
            return {"tool_calls": [("message_agent", {"target": other[name], "message": f"question from {name}"})]}
        return step

    script({"lead": [bot("lead")] * 6, "writer": [bot("writer")] * 6})
    lead_sid = rt.profiles.get("lead").canonical_chat_id()
    writer_sid = rt.profiles.get("writer").canonical_chat_id()
    t0 = time.time()
    t1, b1 = run_in_thread(lambda: rt.agent("lead", lead_sid).run("ask the writer"))
    t2, b2 = run_in_thread(lambda: rt.agent("writer", writer_sid).run("ask the lead"))
    t1.join(15)
    t2.join(15)
    assert not t1.is_alive() and not t2.is_alive()
    assert time.time() - t0 < 10  # not a 30-minute wait
    assert b1["result"].ok and b2["result"].ok
    outs = {}
    for name, sid in (("lead", lead_sid), ("writer", writer_sid)):
        store = SessionStore(rt.profiles.get(name))
        outs[name] = [m["content"] for m in store.messages(sid) if m["role"] == "tool"]
        assert dangling(store, sid) == []
    refused = [n for n, o in outs.items() if o and o[0].startswith("ERROR") and "deadlock" in o[0]]
    assert len(refused) == 1, outs  # exactly one side is refused, with a clear error...
    answered = other[refused[0]]
    assert "reply from " + refused[0] in outs[answered][0]  # ...and the other side's message is answered afterwards
    reg = lock_registry(rt)
    assert not reg.waiting and not reg.holder and not reg.parent


def test_message_agent_timeout_stops_target_and_keeps_transcript_consistent(rt, script, monkeypatch):
    make_pair(rt)
    real = team_tools.message_agent
    monkeypatch.setattr(team_tools, "message_agent", lambda ctx, target, message: real(ctx, target, message, timeout=1.0))

    def slow(msgs, tools):
        time.sleep(1.5)  # the target is still thinking when the sender's time limit passes
        return {"tool_calls": [("write_file", {"path": "late.txt", "content": "late"})]}

    script({
        "lead": [{"tool_calls": [("message_agent", {"target": "writer", "message": "slow question"})]},
                 lambda m, t: {"content": "lead saw: " + m[-1]["content"]}],
        "writer": [slow, {"content": "fresh reply"}],
    })
    t0 = time.time()
    res = rt.agent("lead").run("ask the writer")
    assert res.ok and time.time() - t0 < 6
    assert '"status": "timeout"' in res.text or "timeout" in res.text
    writer = rt.profiles.get("writer")
    sid = writer.canonical_chat_id()
    store = SessionStore(writer)
    assert dangling(store, sid) == []  # the unrun tool call got a result
    assert not (writer.workspace / "late.txt").exists()
    assert store.messages(sid)[-1]["role"] == "assistant" and "time limit" in store.messages(sid)[-1]["content"]
    assert store.get(sid).status == "idle"
    assert not rt.is_cancelled("writer", sid)  # the timeout's stop flag does not linger
    # the writer's chat works normally afterwards
    again = rt.agent("writer", sid).run("hello again")
    assert again.ok and again.text == "fresh reply"


def test_message_agent_times_out_waiting_for_a_busy_chat(rt, script, monkeypatch):
    make_pair(rt)
    real = team_tools.message_agent
    monkeypatch.setattr(team_tools, "message_agent", lambda ctx, target, message: real(ctx, target, message, timeout=1.0))
    script({"lead": [{"tool_calls": [("message_agent", {"target": "writer", "message": "hi"})]},
                     lambda m, t: {"content": "lead saw: " + m[-1]["content"]}]})
    sid = rt.profiles.get("writer").canonical_chat_id()
    lock = rt.session_lock("writer", sid)
    lock.acquire()
    try:
        t0 = time.time()
        res = rt.agent("lead").run("ask the writer")
        assert res.ok and 0.9 < time.time() - t0 < 5
        assert "timeout" in res.text and "busy" in res.text
        assert SessionStore(rt.profiles.get("writer")).messages(sid) == []
    finally:
        lock.release()
