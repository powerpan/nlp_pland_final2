"""Agent features: session search, todo plan, budget checkpoint, in-context reflection,
kanban-style prerequisite handoff, skill usage tracking."""

from __future__ import annotations

import pytest

from pland.memory import SkillStore
from pland.prompts import OUTPUT_RULES, _OLD_FILE_RULE, _PREVIOUS_OUTPUT_RULES
from pland.sessions import SessionStore
from pland.store import dumps


@pytest.mark.parametrize("compacted", [False, True])
@pytest.mark.parametrize("saved_rules", [_OLD_FILE_RULE, _PREVIOUS_OUTPUT_RULES, OUTPUT_RULES],
                         ids=["early-file", "first-length-policy", "current"])
def test_existing_session_uses_current_output_rules_without_rewriting_history(rt, compacted, saved_rules):
    agent = rt.agent("default")
    previous = "Original identity and workspace\n\n# How you work\n" + saved_rules + "\n\nOriginal memory"
    agent.sessions.append(agent.session_id, {"role": "system", "content": previous})
    turn = agent.sessions.append(agent.session_id, {"role": "user", "content": "Prior request"})
    if compacted:
        agent.sessions.patch_meta(agent.session_id, {"compacted_upto": turn, "summary": "Earlier work"})
    agent.sessions.append(agent.session_id, {"role": "user", "content": "Continue in the same room"})

    expected = previous.replace(saved_rules, OUTPUT_RULES)
    assert agent._llm_messages()[0]["content"] == expected
    assert agent._llm_messages()[-1]["content"].endswith("Continue in the same room")
    assert agent.sessions.messages(agent.session_id)[0]["content"] == previous


def test_session_search_finds_past_conversation(rt, script):
    script([{"content": "Noted: the staging database is called orion-db."},
            {"tool_calls": [("session_search", {"query": "staging database"})]},
            lambda msgs, tools: {"content": "found: " + msgs[-1]["content"]}])
    rt.agent("default").run("FYI our staging database is named orion-db")
    res = rt.agent("default").run("what was the staging database called?")
    assert "orion-db" in res.text
    # CJK search via the trigram index
    store = SessionStore(rt.profiles.get("default"))
    sid = store.create(title="zh").id
    store.append(sid, {"role": "user", "content": "請記得我偏好繁體中文的回答"})
    hits = store.search("繁體中文")
    assert hits and hits[0]["session_id"] == sid


def test_todo_plan_persists_and_merges(rt, script):
    script([
        {"tool_calls": [("todo", {"todos": [{"id": "1", "content": "write code"}, {"id": "2", "content": "test it"}]})]},
        {"tool_calls": [("todo", {"todos": [{"id": "1", "status": "completed"}], "merge": True})]},
        {"content": "done"},
    ])
    agent = rt.agent("default")
    agent.run("plan and do")
    todos = agent.sessions.get(agent.session_id).meta["todos"]
    assert [t["status"] for t in todos] == ["completed", "pending"]
    tool_out = [m for m in agent.sessions.messages(agent.session_id) if m["role"] == "tool"][-1]["content"]
    assert "(1/2 done)" in tool_out and "[x] 1. write code" in tool_out


def test_budget_checkpoint_injected(rt, script):
    rt.profiles.update("default", settings={"max_iterations": 10})
    steps = [{"tool_calls": [("list_dir", {"path": "."})]} if i % 2 == 0 else {"tool_calls": [("list_dir", {})]} for i in range(9)]
    script(steps + [{"content": "final"}])
    agent = rt.agent("default")
    agent.run("go")
    users = [m["content"] for m in agent.sessions.messages(agent.session_id) if m["role"] == "user"]
    assert any("Step budget checkpoint" in u for u in users)


def test_reflection_reuses_session_context(rt, script):
    llm = script([{"content": "answer"}])
    agent = rt.agent("default")
    agent.run("small task")
    assert getattr(llm, "reflections", 0) == 1
    # the reflection request was sent on top of the session's own system prompt (cache-friendly), not stored
    stored = agent.sessions.messages(agent.session_id)
    assert not any("[reflection request" in str(m.get("content")) for m in stored)


def test_prerequisites_gate_and_handoff(rt, script):
    rt.profiles.create("lead", title="Lead")
    rt.profiles.create("coder", title="Coder")
    rt.profiles.create("writer", title="Writer")
    board = rt.board
    a = board.add("dm:lead", "implement", created_by="lead", assignee="coder")
    b = board.add("dm:lead", "document", created_by="lead", assignee="writer", depends_on=[a["id"]])
    seen = {}

    def writer_step(msgs, tools):
        seen["prompt"] = [m for m in msgs if m["role"] == "user"][-1]["content"]
        return {"content": "docs written"}

    script({
        "lead": [
            {"tool_calls": [("delegate_task", {"tasks": [{"to": "coder", "goal": "implement", "task_id": a["id"]},
                                                         {"to": "writer", "goal": "document", "task_id": b["id"]}]})]},
            {"tool_calls": [("delegate_task", {"tasks": [{"to": "writer", "goal": "document", "task_id": b["id"]}]})]},
            {"content": "all done"},
        ],
        "coder": [{"content": "IMPLEMENTED add() in lib.py"}],
        "writer": [writer_step],
    })
    agent = rt.agent("lead")
    agent.run("ship it")
    tool_results = [m["content"] for m in agent.sessions.messages(agent.session_id) if m["role"] == "tool"]
    assert "rejected" in tool_results[0] and "unfinished" in tool_results[0]  # writer had to wait for coder
    assert "RESULTS OF PREREQUISITE TASKS" in seen["prompt"] and "IMPLEMENTED add()" in seen["prompt"]
    assert board.get(b["id"])["status"] == "done"


def test_board_numbers_resolve_within_the_board_and_validate_before_insert(rt):
    board = rt.board
    other = board.add("dm:other", "unrelated", created_by="other")
    first = board.add("dm:lead", "draft", created_by="lead")
    second = board.add("dm:lead", "check", created_by="lead")
    refs = ["1", first["id"], "#2"]
    card = board.add("dm:lead", "publish", created_by="lead", depends_on=refs)
    assert card["depends_on"] == [first["id"], second["id"]]
    assert f"{second['id']} (#2)" in board.render("dm:lead")
    for ref in ["4", "0", "t_missing", other["id"]]:
        with pytest.raises(ValueError, match="Unknown prerequisite"):
            board.add("dm:lead", "invalid", created_by="lead", depends_on=[ref])
    assert len(board.list("dm:lead")) == 3


def test_legacy_numbered_and_unresolvable_dependencies_at_dispatch(rt, script):
    from pland.team.delegation import delegate

    rt.profiles.create("lead")
    rt.profiles.create("writer")
    board = rt.board
    draft = board.add("dm:lead", "draft", created_by="lead")
    card = board.add("dm:lead", "publish", created_by="lead")
    other = board.add("dm:other", "private", created_by="other")
    ctx = rt.agent("lead")._context()
    task = {"to": "writer", "goal": "publish", "task_id": card["id"]}
    for ref, error in [("missing", "Unknown prerequisite"), ("2", "Unknown prerequisite"),
                       (other["id"], "does not belong"), ("1", "unfinished")]:
        rt.shared.execute("UPDATE team_tasks SET depends_on=? WHERE id=?", (dumps([ref]), card["id"]))
        result, = delegate(ctx, [task])
        assert result["status"] == "rejected" and error in result["error"]
    assert board.get(card["id"])["depends_on"] == [draft["id"]]
    board.update(draft["id"], status="done", result="signed draft")
    llm = script({"writer": [{"content": "published"}]})
    result, = delegate(ctx, [task])
    assert result["status"] == "completed"
    assert any("signed draft" in m.get("content", "") for name, msgs in llm.calls
               if name == "writer" for m in msgs if m["role"] == "user")


def test_skill_usage_tracking(rt):
    skills = SkillStore(rt.profiles.get("default"))
    skills.save("deploy-app", "Deploy the app", "## When to Use\nx\n## Procedure\n1. y")
    skills.view("deploy-app")
    skills.view("deploy-app")
    entry = [s for s in skills.list() if s["name"] == "deploy-app"][0]
    assert entry["views"] == 2 and entry["saves"] == 1


def test_background_reflection_after_answer(rt, script):
    import threading

    from pland.agent import Agent
    from pland.memory import ExperienceStore

    gate = threading.Event()
    order = []
    llm = script([{"content": "answer"}])
    orig = llm.chat

    def chat(messages, tools=None, **kw):
        if str(messages[-1].get("content", "")).startswith("[reflection request"):
            gate.wait(5)  # hold the reflection until the run has returned
            order.append("reflection")
        return orig(messages, tools, **kw)

    llm.chat = chat
    prof = rt.profiles.get("default")
    sess = SessionStore(prof).create().id
    agent = Agent(rt, prof, sess)  # constructed directly: background reflection on (the default)
    assert agent.settings.background_reflection
    res = agent.run("quick task")
    order.append("returned")
    assert res.text == "answer" and not ExperienceStore(prof).all()
    gate.set()
    rt.wait_reflections(10)
    assert order == ["returned", "reflection"]
    assert len(ExperienceStore(prof).all()) == 1


def test_two_phase_compaction(rt, script):
    rt.profiles.update("default", settings={"context_char_budget": 20_000})
    big = "x" * 4000
    calls = {"compaction": 0}

    llm = script({"default": [{"content": "ok"}] * 50})
    orig = llm.chat

    def chat(messages, tools=None, **kw):
        if messages and messages[0]["content"].startswith("You compress the earlier part"):
            calls["compaction"] += 1
            from pland.llm.base import LLMResponse
            return LLMResponse(content="## Goal\nkeep going")
        return orig(messages, tools, **kw)

    llm.chat = chat
    prof = rt.profiles.get("default")
    store = SessionStore(prof)
    sid = store.create().id
    store.append(sid, {"role": "system", "content": "sys (@default)"})
    for i in range(6):  # six old turns, each with a large tool output
        store.append(sid, {"role": "user", "content": f"step {i}"})
        store.append(sid, {"role": "assistant", "content": "", "tool_calls": [
            {"id": f"c{i}", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]})
        store.append(sid, {"role": "tool", "tool_call_id": f"c{i}", "content": big})
        store.append(sid, {"role": "assistant", "content": f"done {i}"})
    agent = rt.agent("default", session_id=sid)
    agent.run("continue")
    meta = store.get(sid).meta
    assert meta.get("pruned_upto")  # phase 1 ran
    view = agent._llm_messages()
    assert any(m.get("content", "").startswith("[Old tool output cleared") for m in view if m["role"] == "tool")
    assert calls["compaction"] == 0  # pruning alone was enough: no model call

    for i in range(6, 40):  # many small turns: pruning can't help, phase 2 summarises
        store.append(sid, {"role": "user", "content": f"note {i} " + "y" * 800})
        store.append(sid, {"role": "assistant", "content": f"ack {i} " + "z" * 800})
    agent2 = rt.agent("default", session_id=sid)
    agent2.run("continue again")
    assert calls["compaction"] == 1
    assert store.get(sid).meta["summary"].startswith("## Goal")
    assert agent2._view_size() < 20_000


def test_reflection_corrects_a_wrong_note(rt, script):
    import json as _json

    from pland.memory import NotesMemory

    notes = NotesMemory(rt.profiles.get("default"))
    notes.add("memory", "Shell output in this environment is truncated to the first line")
    notes.add("memory", "The project uses Python 3.11")
    refl = _json.dumps({"outcome": "success", "summary": "s", "lessons": [], "procedure": "", "tags": [],
                        "memory_notes": [], "memory_correction": {"old_text": "truncated to the first line", "action": "remove"}})
    script([{"content": "multi-line output came back complete"}], reflection=refl)
    rt.agent("default").run("check shell output")
    entries = notes.entries("memory")
    assert entries == ["The project uses Python 3.11"]
