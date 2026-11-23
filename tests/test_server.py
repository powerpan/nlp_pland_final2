"""HTTP/WebSocket API tests. Every model call is served by the scripted RoutingLLM (see conftest)."""

from __future__ import annotations

import json
import subprocess
import threading
import time
import warnings

import pytest

with warnings.catch_warnings():  # starlette's TestClient warns about its httpx backend at import time
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from pland.memory import ExperienceStore
from pland.server import app as server_app
from pland.server.app import create_app
from pland.sessions import SessionStore


def wait_for(fn, timeout: float = 10.0, interval: float = 0.02):
    """Poll `fn` until it returns a truthy value (returned) or fail after `timeout` seconds."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s (last value: {last!r})")


@pytest.fixture()
def client(rt):
    with TestClient(create_app(rt)) as c:
        yield c


def idle(client, profile, sid):
    data = client.get(f"/api/profiles/{profile}/sessions/{sid}/messages").json()
    return data if not data["busy"] else None


# --------------------------------------------------------------------------- status & static

def test_status_never_leaks_the_key(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-very-secret-value")
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["api_key_set"] is True
    assert body["provider"] and body["version"]
    assert "sk-test-very-secret-value" not in r.text


def test_static_ui_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()
    for asset in ("app.js", "style.css"):
        assert client.get(f"/{asset}").status_code == 200


# --------------------------------------------------------------------------- profiles

def test_profile_crud(client, rt):
    r = client.post("/api/profiles", json={
        "name": "coder", "title": "Coder", "description": "writes Python", "soul": "You write tidy Python.",
        "model": "deepseek-v4-pro", "thinking": True, "backend": "local", "toolsets": ["files", "code", "memory"],
    })
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["name"] == "coder" and created["bot"] is True
    assert created["settings"]["model"] == "deepseek-v4-pro" and created["settings"]["thinking"] is True
    assert created["settings"]["toolsets"] == ["files", "code", "memory"]
    assert "tidy Python" in created["soul"]

    assert client.post("/api/profiles", json={"name": "coder"}).status_code == 409
    assert client.post("/api/profiles", json={"name": "Bad Name!"}).status_code == 400

    names = [p["name"] for p in client.get("/api/profiles").json()]
    assert {"default", "coder"} <= set(names)
    assert [p["name"] for p in client.get("/api/profiles?bots_only=true").json()] == ["coder"]

    r = client.patch("/api/profiles/coder", json={"title": "Senior Coder", "soul": "Be terse.", "thinking": False,
                                                  "approvals": "off"})
    assert r.status_code == 200, r.text
    detail = client.get("/api/profiles/coder").json()
    assert detail["title"] == "Senior Coder" and detail["soul"] == "Be terse."
    assert detail["settings"]["thinking"] is False and detail["settings"]["approvals"] == "off"
    assert detail["settings"]["model"] == "deepseek-v4-pro"  # untouched fields survive a patch

    mem = client.get("/api/profiles/coder/memory").json()
    assert set(mem["notes"]) == {"memory", "user"} and mem["experiences"] == []

    assert client.delete("/api/profiles/default").status_code == 400
    assert client.delete("/api/profiles/coder").status_code == 200
    assert client.get("/api/profiles/coder").status_code == 404
    assert not rt.profiles.exists("coder")


def test_bot_chat_is_canonical(client, rt):
    client.post("/api/profiles", json={"name": "helper", "title": "Helper"})
    a = client.get("/api/profiles/helper/bot-chat").json()["session_id"]
    b = client.get("/api/profiles/helper/bot-chat").json()["session_id"]
    assert a == b == rt.profiles.get("helper").canonical_chat_id()
    assert client.get("/api/profiles/helper").json()["bot_chat_id"] == a


# --------------------------------------------------------------------------- single-agent runs

def test_posting_a_message_runs_the_agent(client, rt, script):
    gate = threading.Event()

    def held(msgs, tools):
        gate.wait(5)  # keep the run busy until the test has checked the 409
        return {"content": "Created hello.py for you."}

    script([
        {"tool_calls": [("write_file", {"path": "hello.py", "content": "print('hi')\n"})]},
        held,
    ])
    # An experience that matches the task: the stored prompt gets augmented, the UI must not show that.
    ExperienceStore(rt.profiles.get("default")).add(task="write hello script python", outcome="success",
                                                    summary="wrote it", lessons=["keep it short"])
    sid = client.post("/api/profiles/default/sessions", json={}).json()["id"]
    text = "write a hello script in python"
    r = client.post(f"/api/profiles/default/sessions/{sid}/messages", json={"text": text})
    assert r.status_code == 202, r.text
    assert client.post(f"/api/profiles/default/sessions/{sid}/messages", json={"text": "again"}).status_code == 409
    gate.set()
    data = wait_for(lambda: idle(client, "default", sid))
    items = data["items"]
    user = [i for i in items if i["role"] == "user"]
    assert user[0]["content"] == text  # meta.display, not the experience-augmented prompt
    assert user[0]["recalled"] == ["write hello script python"]  # ...but the UI can say what was recalled
    calls = [c for i in items if i["role"] == "assistant" for c in i["tool_calls"]]
    assert calls[0]["name"] == "write_file" and calls[0]["ok"] is True and calls[0]["result"]
    assert items[-1]["role"] == "assistant" and items[-1]["content"] == "Created hello.py for you."
    assert (rt.profiles.get("default").workspace / "hello.py").exists()
    # the session got a title from the first message, and the incremental fetch works
    assert client.get(f"/api/profiles/default/sessions/{sid}").json()["title"].startswith("write a hello")
    tail = client.get(f"/api/profiles/default/sessions/{sid}/messages?after={data['last_id']}").json()
    assert tail["items"] == [] and tail["last_id"] == data["last_id"]
    assert client.get("/api/usage").json()["calls"] >= 2


def test_hitl_clarification_round_trip(client, rt, script):
    script([
        {"tool_calls": [("ask_user", {"question": "Which language should I use?", "options": ["Python", "Go"]})]},
        lambda msgs, tools: {"content": "Using " + ("Python" if "Python" in msgs[-1]["content"] else "??")},
    ])
    sid = client.post("/api/profiles/default/sessions", json={"title": "fizz"}).json()["id"]
    assert client.post(f"/api/profiles/default/sessions/{sid}/messages", json={"text": "write fizzbuzz"}).status_code == 202
    pending = wait_for(lambda: client.get("/api/hitl").json())
    req = pending[0]
    assert req["kind"] == "clarify" and req["payload"]["question"] == "Which language should I use?"
    assert req["payload"]["options"] == ["Python", "Go"] and req["live"] is True
    assert req["origin"]["session_id"] == sid
    assert client.get(f"/api/hitl?session_id={sid}").json()[0]["id"] == req["id"]
    # the card also travels with the session view
    assert client.get(f"/api/profiles/default/sessions/{sid}/messages").json()["pending_hitl"][0]["id"] == req["id"]

    r = client.post(f"/api/hitl/{req['id']}", json={"choice": "Python"})  # option button
    assert r.status_code == 200 and r.json()["live"] is True
    data = wait_for(lambda: idle(client, "default", sid))
    assert data["items"][-1]["content"] == "Using Python"
    assert client.get("/api/hitl").json() == []
    assert client.post(f"/api/hitl/{req['id']}", json={"text": "late"}).status_code == 409


def test_hitl_approval_choice(client, rt, script):
    script([
        {"tool_calls": [("run_shell", {"command": "mkdir -p d1 && rm -r d1"})]},
        {"content": "cleaned"},
    ])
    sid = client.post("/api/profiles/default/sessions", json={}).json()["id"]
    client.post(f"/api/profiles/default/sessions/{sid}/messages", json={"text": "clean up"})
    req = wait_for(lambda: client.get("/api/hitl").json())[0]
    assert req["kind"] == "approval" and req["payload"]["options"] == ["once", "session", "always", "deny"]
    assert client.post(f"/api/hitl/{req['id']}", json={"choice": "maybe"}).status_code == 400
    assert client.post(f"/api/hitl/{req['id']}", json={"choice": "once"}).status_code == 200
    data = wait_for(lambda: idle(client, "default", sid))
    call = [c for i in data["items"] if i["role"] == "assistant" for c in i["tool_calls"]][0]
    assert call["name"] == "run_shell" and "not permitted" not in (call["result"] or "")


def test_stop_releases_a_run_waiting_for_the_human(client, rt, script):
    script([
        {"tool_calls": [("ask_user", {"question": "Proceed?"})]},
        {"content": "should not get here"},
    ])
    sid = client.post("/api/profiles/default/sessions", json={}).json()["id"]
    client.post(f"/api/profiles/default/sessions/{sid}/messages", json={"text": "do it"})
    wait_for(lambda: client.get("/api/hitl").json())
    r = client.post(f"/api/profiles/default/sessions/{sid}/stop")
    assert r.status_code == 200 and r.json()["released_hitl"] == 1
    data = wait_for(lambda: idle(client, "default", sid))
    assert data["items"][-1]["cancelled"] is True


# --------------------------------------------------------------------------- rooms

def test_room_create_send_and_board(client, rt, script):
    for name, title in (("lead", "Lead"), ("coder", "Coder")):
        assert client.post("/api/profiles", json={"name": name, "title": title}).status_code == 201
    script({
        "lead": [
            {"tool_calls": [("delegate_task", {"tasks": [{"to": "coder", "goal": "write x.py"}]})]},
            {"content": "Integrated: x.py is ready."},
        ],
        "coder": ["[PASS]", {"content": "x.py done"}],  # member turn (passes), then the delegated work
    })
    r = client.post("/api/rooms", json={"name": "Build team", "members": ["lead", "coder"], "lead": "lead"})
    assert r.status_code == 201, r.text
    room = r.json()
    rid = room["id"]
    assert room["lead"] == "lead" and [m["name"] for m in room["member_info"]] == ["lead", "coder"]
    assert client.post("/api/rooms", json={"name": "Build team", "members": ["lead"]}).status_code == 409
    assert client.post("/api/rooms", json={"name": "X", "members": ["ghost"]}).status_code == 400

    r = client.post(f"/api/rooms/{rid}/messages", json={"text": "@all please build x.py"})
    assert r.status_code == 202 and r.json()["message"]["speaker"] == "user"

    def settled():
        data = client.get(f"/api/rooms/{rid}/messages").json()
        done = [m for m in data["messages"] if m["speaker"] == "lead" and m["kind"] == "message"]
        return data if done and not data["room"]["driving"] else None

    data = settled_data = wait_for(settled)
    kinds = [(m["speaker"], m["kind"]) for m in data["messages"]]
    assert ("system", "system") in kinds and ("user", "message") in kinds
    assert ("lead", "activity") in kinds and ("coder", "activity") in kinds  # delegation started / finished
    assert settled_data["messages"][-1]["content"] == "Integrated: x.py is ready."
    tasks = client.get(f"/api/rooms/{rid}/tasks").json()
    assert len(tasks) == 1 and tasks[0]["assignee"] == "coder" and tasks[0]["status"] == "done"
    assert client.get(f"/api/board/{rid}").json()[0]["id"] == tasks[0]["id"]
    last = data["last_id"]
    assert client.get(f"/api/rooms/{rid}/messages?after={last}").json()["messages"] == []

    # each member's private view of the room: the turn prompt is shown as a group update, read-only
    lead_sess = client.get("/api/profiles/lead/sessions?kinds=room_member").json()[0]
    turn = client.get(f"/api/profiles/lead/sessions/{lead_sess['id']}/messages").json()["items"][0]
    assert turn["kind"] == "room_turn" and turn["turn_role"] == "lead"
    assert client.post(f"/api/profiles/lead/sessions/{lead_sess['id']}/messages", json={"text": "hi"}).status_code == 400

    rooms = client.get("/api/rooms").json()
    assert rooms[0]["id"] == rid and rooms[0]["preview"]["speaker"] == "lead"
    r = client.patch(f"/api/rooms/{rid}", json={"name": "Builders", "lead": "coder"})
    assert r.status_code == 200 and r.json()["name"] == "Builders" and r.json()["lead"] == "coder"
    # deleting a member bot removes it from the room
    assert client.delete("/api/profiles/coder").status_code == 200
    room = client.get(f"/api/rooms/{rid}").json()
    assert room["members"] == ["lead"] and room["lead"] is None
    assert client.delete(f"/api/rooms/{rid}").status_code == 200
    assert client.get(f"/api/rooms/{rid}").status_code == 404


# --------------------------------------------------------------------------- events

def test_websocket_receives_events(client, rt, script):
    script([{"content": "pong"}])
    with client.websocket_connect("/api/events") as ws:
        assert ws.receive_json()["type"] == "hello"  # subscribed from here on
        rt.bus.publish("test.ping", value=42)
        ev = ws.receive_json()
        assert ev["type"] == "test.ping" and ev["value"] == 42
        sid = client.post("/api/profiles/default/sessions", json={}).json()["id"]
        client.post(f"/api/profiles/default/sessions/{sid}/messages", json={"text": "ping"})
        seen = []
        while True:
            ev = ws.receive_json()
            seen.append(ev["type"])
            if ev["type"] == "run.started":
                assert ev["origin"]["session_id"] == sid  # events are enriched with their origin
            if ev["type"] == "run.finished" and ev.get("session_id") == sid:
                break
        assert "run.started" in seen and "assistant.message" in seen
    wait_for(lambda: idle(client, "default", sid))
    # after disconnect the bridge unsubscribed: only the server's own subscribers remain
    assert len(rt.bus._subs) == 2


def test_delegated_hitl_is_traced_to_the_origin_session(client, rt, script):
    client.post("/api/profiles", json={"name": "coder", "title": "Coder"})
    script({
        "default": [{"tool_calls": [("delegate_task", {"tasks": [{"to": "coder", "goal": "pick a name"}]})]},
                    {"content": "coder finished"}],
        "coder": [{"tool_calls": [("ask_user", {"question": "Which name?"})]}, {"content": "named it"}],
    })
    sid = client.post("/api/profiles/default/sessions", json={}).json()["id"]
    client.post(f"/api/profiles/default/sessions/{sid}/messages", json={"text": "delegate naming"})
    req = wait_for(lambda: client.get("/api/hitl").json())[0]
    assert req["profile"] == "coder" and req["session_id"] != sid
    assert req["origin"] == {"profile": "default", "session_id": sid, "kind": "chat"}
    acts = client.get("/api/activity").json()["runs"]
    assert any(r["profile"] == "coder" and r["state"] == "waiting" for r in acts)
    client.post(f"/api/hitl/{req['id']}", json={"text": "Zed"})
    data = wait_for(lambda: idle(client, "default", sid))
    assert data["items"][-1]["content"] == "coder finished"
    assert client.get("/api/activity").json()["runs"] == []


def test_interrupted_session_is_recovered_and_resumed(rt, script):
    # A chat left 'running' by a process that died in the middle of a tool call.
    dead = subprocess.Popen(["true"])
    dead.wait()
    prof = rt.profiles.get("default")
    store = SessionStore(prof)
    sess = store.create(title="crashed")
    store.append(sess.id, {"role": "system", "content": "sys (@default)"})
    store.append(sess.id, {"role": "user", "content": "make a.txt"}, meta={"display": "make a.txt"})
    store.append(sess.id, {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "write_file", "arguments": json.dumps({"path": "a.txt", "content": "x"})}}]})
    store.update(sess.id, status="running", meta={"pid": dead.pid})
    script([{"content": "a.txt is written"}])
    with TestClient(create_app(rt)) as c:
        assert [r["session_id"] for r in c.get("/api/status").json()["recovered"]] == [sess.id]
        data = c.get(f"/api/profiles/default/sessions/{sess.id}/messages").json()
        assert data["interrupted"] is True and data["session"]["status"] == "interrupted"
        assert [r["session_id"] for r in c.get("/api/interrupted").json()] == [sess.id]
        row = [s for s in c.get("/api/profiles/default/sessions").json() if s["id"] == sess.id][0]
        assert row["status"] == "interrupted" and row["interrupted"] is True
        # a new message on top of an unanswered tool call is refused; resume completes it in place
        assert c.post(f"/api/profiles/default/sessions/{sess.id}/messages", json={"text": "hello?"}).status_code == 409
        assert c.post(f"/api/profiles/default/sessions/{sess.id}/resume").status_code == 202
        data = wait_for(lambda: idle(c, "default", sess.id))
        call = [x for i in data["items"] if i["role"] == "assistant" for x in i["tool_calls"]][0]
        assert call["ok"] is True and data["items"][-1]["content"] == "a.txt is written"
        assert data["interrupted"] is False and data["session"]["status"] == "idle"
        assert c.get("/api/interrupted").json() == []
    assert (prof.workspace / "a.txt").read_text() == "x"


# --------------------------------------------------------------------------- plan, activity, skills, backend

def test_todo_plan_reaches_session_payloads_and_events(client, rt, script):
    gate = threading.Event()
    plan = [{"id": "1", "content": "Write the script", "status": "in_progress"},
            {"id": "2", "content": "Run it", "status": "pending"},
            {"id": "3", "content": "Nice extra", "status": "pending"}]

    def held(msgs, tools):
        gate.wait(5)  # keep the run alive so the live state can be checked
        return {"tool_calls": [("todo", {"merge": True, "todos": [{"id": "1", "status": "completed"},
                                                                   {"id": "2", "status": "in_progress"},
                                                                   {"id": "3", "status": "cancelled"}]})]}

    script([{"tool_calls": [("todo", {"todos": plan})]}, held, {"content": "done"}])
    sid = client.post("/api/profiles/default/sessions", json={}).json()["id"]
    assert client.get(f"/api/profiles/default/sessions/{sid}").json()["todos"] == []
    with client.websocket_connect("/api/events") as ws:
        assert ws.receive_json()["type"] == "hello"
        client.post(f"/api/profiles/default/sessions/{sid}/messages", json={"text": "plan and do it"})
        while True:
            ev = ws.receive_json()
            if ev["type"] == "todo.updated":
                break
        assert ev["session_id"] == sid and ev["todos"] == plan
        assert ev["origin"] == {"profile": "default", "session_id": sid, "kind": "chat"}
        # the plan travels with the session row, the transcript fetch and the live run state
        assert client.get(f"/api/profiles/default/sessions/{sid}").json()["todos"] == plan
        assert client.get(f"/api/profiles/default/sessions/{sid}/messages").json()["todos"] == plan
        runs = wait_for(lambda: [r for r in client.get("/api/activity").json()["runs"] if r["session_id"] == sid])
        assert runs[0]["todos"] == plan
        gate.set()
        while True:
            ev = ws.receive_json()
            if ev["type"] == "todo.updated":
                break
        assert [t["status"] for t in ev["todos"]] == ["completed", "in_progress", "cancelled"]
    data = wait_for(lambda: idle(client, "default", sid))
    assert [t["status"] for t in data["todos"]] == ["completed", "in_progress", "cancelled"]
    row = [s for s in client.get("/api/profiles/default/sessions").json() if s["id"] == sid][0]
    assert row["todos"] == data["todos"]
    call = [c for i in data["items"] if i["role"] == "assistant" for c in i["tool_calls"]][0]
    assert call["name"] == "todo" and "(0/3 done)" in call["result"]


def test_delegate_plan_is_visible_in_its_work_log(client, rt, script):
    client.post("/api/profiles", json={"name": "coder", "title": "Coder"})
    script({
        "default": [{"tool_calls": [("delegate_task", {"tasks": [{"to": "coder", "goal": "build it"}]})]},
                    {"content": "delegated"}],
        "coder": [{"tool_calls": [("todo", {"todos": [{"id": "a", "content": "Build", "status": "completed"}]})]},
                  {"content": "built"}],
    })
    sid = client.post("/api/profiles/default/sessions", json={}).json()["id"]
    client.post(f"/api/profiles/default/sessions/{sid}/messages", json={"text": "delegate the build"})
    wait_for(lambda: idle(client, "default", sid))
    log = [s for s in client.get("/api/profiles/coder/sessions").json() if s["kind"] == "delegation"][0]
    assert log["todos"] == [{"id": "a", "content": "Build", "status": "completed"}]
    assert client.get(f"/api/profiles/coder/sessions/{log['id']}/messages").json()["todos"] == log["todos"]
    assert client.get(f"/api/profiles/default/sessions/{sid}").json()["todos"] == []  # plans stay per session


def test_activity_events_come_with_the_transcript(client, rt, script):
    script([
        {"tool_calls": [("session_search", {"query": "zebra migration"})]},
        {"content": "Nothing found."},
    ])
    sid = client.post("/api/profiles/default/sessions", json={}).json()["id"]
    other = client.post("/api/profiles/default/sessions", json={}).json()["id"]
    client.post(f"/api/profiles/default/sessions/{sid}/messages", json={"text": "did we talk about zebras?"})
    data = wait_for(lambda: idle(client, "default", sid))
    acts = data["activity"]
    search = [a for a in acts if a["type"] == "memory.session_search"]
    assert search and search[0]["query"] == "zebra migration" and search[0]["hits"] == 0
    assert search[0]["role"] == "event" and search[0]["created"] and search[0]["id"].startswith("e")
    added = wait_for(lambda: [a for a in client.get(f"/api/profiles/default/sessions/{sid}/messages").json()["activity"]
                              if a["type"] == "experience.added"])
    assert added[0]["outcome"] == "success" and added[0]["lessons"] == ["check files exist"]
    # other activity types; events of other sessions and unrelated types are not included
    rt.bus.publish("approval.auto", profile="default", session_id=sid, category="shell:recursive delete",
                   grant="session", summary="rm -r build")
    rt.bus.publish("context.compacted", profile="default", session_id=sid, folded=12, size=900)
    rt.bus.publish("loop.detected", profile="default", session_id=sid, reason="same call 5 times")
    rt.bus.publish("memory.session_search", profile="default", session_id=other, query="elsewhere", hits=1)
    rt.bus.publish("tool.started", profile="default", session_id=sid, tool="read_file")
    cursor = client.get(f"/api/profiles/default/sessions/{sid}/messages").json()["last_event_id"]
    data = client.get(f"/api/profiles/default/sessions/{sid}/messages?after={data['last_id']}").json()
    types = [a["type"] for a in data["activity"]]
    assert types[-3:] == ["approval.auto", "context.compacted", "loop.detected"]
    assert "tool.started" not in types and all(a.get("query") != "elsewhere" for a in data["activity"])
    auto = data["activity"][-3]
    assert (auto["category"], auto["grant"], auto["summary"]) == ("shell:recursive delete", "session", "rm -r build")
    assert data["activity"][-2]["folded"] == 12 and data["activity"][-1]["reason"] == "same call 5 times"
    # incremental: only events after the cursor, and the cursor advances past unrelated events too
    tail = client.get(f"/api/profiles/default/sessions/{sid}/messages?after={data['last_id']}&events_after={cursor}").json()
    assert tail["activity"] == [] and tail["last_event_id"] == cursor
    rt.bus.publish("context.pruned", profile="default", session_id=sid, upto=3, size=100)
    tail = client.get(f"/api/profiles/default/sessions/{sid}/messages?after={data['last_id']}&events_after={cursor}").json()
    assert [a["type"] for a in tail["activity"]] == ["context.pruned"] and tail["last_event_id"] > cursor


def test_activity_events_are_forwarded_to_websocket(client, rt):
    with client.websocket_connect("/api/events") as ws:
        assert ws.receive_json()["type"] == "hello"
        for t, data in (("memory.session_search", {"query": "q", "hits": 2}), ("budget.checkpoint", {"steps_left": 8}),
                        ("context.pruned", {"size": 10}), ("context.compacted", {"folded": 3}),
                        ("loop.detected", {"reason": "r"}), ("experience.retrieved", {"ids": ["x_1"], "scores": [1.0]}),
                        ("experience.added", {"outcome": "success"}), ("approval.auto", {"category": "git:push", "grant": "always"})):
            rt.bus.publish(t, profile="default", session_id="s_x", **data)
            ev = ws.receive_json()
            assert ev["type"] == t and all(ev[k] == v for k, v in data.items())




def test_backend_labels(client, rt, monkeypatch):
    monkeypatch.setattr(server_app, "seatbelt_available", lambda: True)
    client.post("/api/profiles", json={"name": "boxed", "title": "Boxed", "backend": "local"})
    client.post("/api/profiles", json={"name": "contained", "title": "Contained", "backend": "docker"})
    rt.profiles.update("default", settings={"sandbox": {"os_sandbox": "off"}})
    rows = {p["name"]: p for p in client.get("/api/profiles").json()}
    assert (rows["boxed"]["backend_effective"], rows["boxed"]["backend_label"]) == ("local+seatbelt", "local (sandboxed)")
    assert (rows["contained"]["backend_effective"], rows["contained"]["backend_label"]) == ("docker", "docker")
    assert (rows["default"]["backend_effective"], rows["default"]["backend_label"]) == ("local", "local")
    settings = client.get("/api/profiles/boxed").json()["settings"]
    assert settings["backend"] == "local" and settings["os_sandbox"] == "auto"
    assert settings["backend_label"] == "local (sandboxed)"
    status = client.get("/api/status").json()
    assert status["seatbelt"] is True and status["backend_labels"]["local+seatbelt"] == "local (sandboxed)"
    monkeypatch.setattr(server_app, "seatbelt_available", lambda: False)  # e.g. Linux: plain local
    assert client.get("/api/profiles/boxed").json()["backend_label"] == "local"
    assert client.get("/api/status").json()["seatbelt"] is False


def test_streamed_deltas_are_forwarded_with_origin(client, rt, script):
    llm = script([{"content": "Hello world"}])
    scripted_chat = llm.chat

    def streaming_chat(messages, tools=None, *, on_delta=None, **kw):  # a provider that streams its reply
        if on_delta is not None:
            on_delta("reasoning", "Let me think. ")
            on_delta("content", "Hello ")
            on_delta("content", "world")
        return scripted_chat(messages, tools, on_delta=on_delta, **kw)

    llm.chat = streaming_chat
    sid = client.post("/api/profiles/default/sessions", json={}).json()["id"]
    with client.websocket_connect("/api/events") as ws:
        assert ws.receive_json()["type"] == "hello"
        client.post(f"/api/profiles/default/sessions/{sid}/messages", json={"text": "say hello"})
        deltas, order = [], []
        while True:
            ev = ws.receive_json()
            if ev.get("session_id") != sid:
                continue
            order.append(ev["type"])
            if ev["type"] == "assistant.delta":
                deltas.append(ev)
            if ev["type"] == "run.finished":
                break
    assert deltas and all(d["origin"] == {"profile": "default", "session_id": sid, "kind": "chat"} for d in deltas)
    assert all(d["iteration"] == 1 and d["profile"] == "default" and d["run_id"] for d in deltas)
    assert "".join(d["text"] for d in deltas if d["kind"] == "content") == "Hello world"
    assert "".join(d["text"] for d in deltas if d["kind"] == "reasoning") == "Let me think. "
    assert order.index("assistant.delta") < order.index("assistant.message")  # the bubble is replaced afterwards
    data = wait_for(lambda: idle(client, "default", sid))
    assert data["items"][-1]["content"] == "Hello world"
