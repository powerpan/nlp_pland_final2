from __future__ import annotations

import threading
import time

from pland.sessions import SessionStore


def make_team(rt):
    rt.profiles.create("lead", title="Lead", description="plans and integrates")
    rt.profiles.create("coder", title="Coder", description="writes Python")
    rt.profiles.create("writer", title="Writer", description="writes docs")


def test_delegation_runs_in_target_profile(rt, script):
    make_team(rt)
    script({
        "lead": [
            {"tool_calls": [("delegate_task", {"tasks": [
                {"to": "coder", "goal": "create add.py with add(a,b)", "context": "plain python"},
                {"to": "writer", "goal": "write USAGE.md", "context": "one line"},
            ]})]},
            {"content": "Team finished."},
        ],
        "coder": [{"tool_calls": [("write_file", {"path": "add.py", "content": "def add(a,b): return a+b\n"})]}, {"content": "add.py ready"}],
        "writer": [{"tool_calls": [("write_file", {"path": "USAGE.md", "content": "call add"})]}, {"content": "USAGE.md ready"}],
    })
    res = rt.agent("lead").run("build the add library")
    assert res.ok
    assert (rt.profiles.get("coder").workspace / "add.py").exists()
    assert (rt.profiles.get("writer").workspace / "USAGE.md").exists()
    assert not (rt.profiles.get("lead").workspace / "add.py").exists()  # isolation
    tasks = rt.board.list("dm:lead")
    assert {t["assignee"] for t in tasks} == {"coder", "writer"} and all(t["status"] == "done" for t in tasks)
    deleg = SessionStore(rt.profiles.get("coder")).list(kinds=("delegation",))
    assert len(deleg) == 1


def test_delegation_cycle_rejected(rt, script):
    make_team(rt)
    script({
        "lead": [{"tool_calls": [("delegate_task", {"tasks": [{"to": "coder", "goal": "do x"}]})]}, {"content": "ok"}],
        "coder": [{"tool_calls": [("delegate_task", {"tasks": [{"to": "lead", "goal": "do x back"}]})]}, {"content": "coder report"}],
    })
    rt.agent("lead").run("go")
    coder_sess = SessionStore(rt.profiles.get("coder")).list(kinds=("delegation",))[0]
    tool_out = [m for m in SessionStore(rt.profiles.get("coder")).messages(coder_sess.id) if m["role"] == "tool"][0]["content"]
    assert "cycle" in tool_out


def test_parallel_delegation_is_concurrent(rt, script):
    make_team(rt)
    barrier = threading.Barrier(2, timeout=5)

    def wait_then(name):
        def step(msgs, tools):
            barrier.wait()  # both delegates must be running at the same time
            return {"content": f"{name} done"}
        return step

    script({
        "lead": [{"tool_calls": [("delegate_task", {"tasks": [{"to": "coder", "goal": "a"}, {"to": "writer", "goal": "b"}]})]},
                 {"content": "merged"}],
        "coder": [wait_then("coder")],
        "writer": [wait_then("writer")],
    })
    t0 = time.time()
    res = rt.agent("lead").run("parallel please")
    assert res.ok and time.time() - t0 < 5


def test_message_agent(rt, script):
    make_team(rt)
    script({
        "lead": [{"tool_calls": [("message_agent", {"target": "writer", "message": "What is our doc style?"})]},
                 lambda m, t: {"content": "writer said: " + m[-1]["content"]}],
        "writer": [{"content": "Use short sentences."}],
    })
    res = rt.agent("lead").run("ask writer")
    assert "Use short sentences" in res.text
    chat = SessionStore(rt.profiles.get("writer")).find(kind="bot_chat")
    assert chat is not None


def test_room_lead_and_pass(rt, script):
    make_team(rt)
    room = rt.rooms.create("proj", ["lead", "coder", "writer"], lead="lead")
    script({
        "coder": [{"content": "I can implement the code part."}],
        "writer": [{"content": "[PASS]"}],
        "lead": [{"tool_calls": [("team_tasks", {"action": "add", "title": "implement", "assignee": "coder"})]},
                 {"content": "Plan posted. @coder please confirm the API."}],
    })
    out = rt.rooms.send(room["id"], "Let's build a calculator", background=False)["result"]
    speakers = [m["speaker"] for m in rt.rooms.messages(room["id"]) if m["kind"] == "message"]
    assert speakers[:3] == ["user", "coder", "lead"]  # writer passed; members speak before the lead
    assert out["lead"] == "lead"
    assert rt.board.list(room["id"])[0]["assignee"] == "coder"
    # coder was @mentioned by the lead → got a second-round turn (scripted default reply)
    assert speakers[-1] == "coder"


def test_room_mention_scopes_round(rt, script):
    make_team(rt)
    room = rt.rooms.create("proj2", ["lead", "coder", "writer"])
    llm = script({"writer": [{"content": "Docs plan ready."}]})
    rt.rooms.send(room["id"], "@writer draft the docs outline", background=False)
    called = {name for name, _ in llm.calls}
    assert called == {"writer"}


def test_room_member_discussion_turn_is_read_only(rt, script):
    make_team(rt)
    room = rt.rooms.create("disc", ["lead", "coder"], lead="lead")
    script({
        "coder": [{"tool_calls": [("write_file", {"path": "x.py", "content": "x"})]}, {"content": "I can write x.py"}],
        "lead": [{"content": "ok"}],
    })
    rt.rooms.send(room["id"], "make x", background=False)
    assert not (rt.profiles.get("coder").workspace / "x.py").exists()


def test_room_shared_folder_in_shell(rt, script):
    make_team(rt)
    room = rt.rooms.create("sh", ["coder"])
    script({"coder": [{"tool_calls": [("run_shell", {"command": "echo hi > shared/from_shell.txt"})]}, {"content": "done"}]})
    rt.rooms.send(room["id"], "write via shell", background=False)
    assert (rt.rooms.shared_dir(room["id"]) / "from_shell.txt").read_text().strip() == "hi"


def test_room_shared_folder(rt, script):
    make_team(rt)
    room = rt.rooms.create("proj3", ["coder"])
    script({"coder": [{"tool_calls": [("write_file", {"path": "shared/spec.md", "content": "# spec"})]}, {"content": "wrote spec"}]})
    rt.rooms.send(room["id"], "write the spec", background=False)
    assert (rt.rooms.shared_dir(room["id"]) / "spec.md").read_text() == "# spec"


def test_discussion_turns_run_concurrently(rt, script):
    make_team(rt)
    room = rt.rooms.create("par", ["lead", "coder", "writer"], lead="lead")
    barrier = threading.Barrier(2, timeout=5)

    def discuss(name):
        def step(msgs, tools):
            barrier.wait()  # both discussion turns must be in flight at the same time
            return {"content": f"{name} can help"}
        return step

    script({"coder": [discuss("coder")], "writer": [discuss("writer")], "lead": [{"content": "plan"}]})
    rt.rooms.send(room["id"], "do it", background=False)
    speakers = [m["speaker"] for m in rt.rooms.messages(room["id"]) if m["kind"] == "message"]
    assert speakers == ["user", "coder", "writer", "lead"]  # posted in roster order after running in parallel
