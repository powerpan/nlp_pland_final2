"""Fixes from the review of a real team run ("can encrypted data still be fuzzy-searched?") — no network.

- successive edits of one file are progress, not a loop; a guard stop still records the call's result
- read_file pages under the tool-result cap instead of losing the middle; search_files accepts a file
- a teammate's files come back to the delegator; results show the run budget; reflection is not charged to it
- board status follows the deliverable, and a stopped follow-up does not undo finished work
- a plan left untouched gets one reminder; the root agent is told when most of the budget is spent
"""

from __future__ import annotations

import json

from pland.sessions import SessionStore


def make_team(rt):
    rt.profiles.create("lead", title="Lead", description="plans and integrates")
    rt.profiles.create("coder", title="Coder", description="writes Python")


def tool_results(agent):
    return [m for m in agent.sessions.messages(agent.session_id) if m["role"] == "tool"]


def unanswered_calls(store, sid):
    msgs = store.messages(sid)
    called = [tc["id"] for m in msgs if m["role"] == "assistant" for tc in m.get("tool_calls") or []]
    answered = {m.get("tool_call_id") for m in msgs if m["role"] == "tool"}
    return [c for c in called if c not in answered]


# --------------------------------------------------------------------------- loop guard

def test_successive_edits_of_one_file_are_not_a_loop(rt, script):
    lines = "\n".join(f"line {i}: draft" for i in range(8)) + "\n"
    steps = [{"tool_calls": [("write_file", {"path": "notes.md", "content": lines})]}]
    # each edit returns the same text, "Edited notes.md (1 replacement)" — it used to trip the guard after six
    steps += [{"tool_calls": [("edit_file", {"path": "notes.md", "old_text": f"line {i}: draft", "new_text": f"line {i}: final"})]}
              for i in range(8)]
    steps.append({"content": "all eight lines finalised"})
    script(steps)
    agent = rt.agent("default")
    res = agent.run("finalise the notes")
    assert res.status == "completed", res.text
    assert not any("progress guard" in m["content"] for m in tool_results(agent))
    assert (rt.profiles.get("default").workspace / "notes.md").read_text().count("final") == 8
    assert agent.written_paths == ["notes.md"]


def test_guard_stop_records_the_triggering_result_and_answers_the_rest(rt, script):
    counter = iter(range(100))

    def step(msgs, tools):
        if "Stop using tools" in str(msgs[-1].get("content")):
            return {"content": "final summary"}
        return {"tool_calls": [("run_shell", {"command": f"echo same  # a{next(counter)}"}),
                               ("run_shell", {"command": f"echo same  # b{next(counter)}"})]}

    script([step] * 20)
    agent = rt.agent("default")
    res = agent.run("loop forever")
    assert res.status == "loop_detected" and res.text == "final summary"
    results = tool_results(agent)
    assert any("stopping this run" in m["content"] for m in results)  # the call that tripped it is recorded
    assert results[-1]["content"].startswith("(not run: the loop guard stopped this run")  # its sibling is answered
    assert unanswered_calls(agent.sessions, agent.session_id) == []


# --------------------------------------------------------------------------- file tools

def test_read_file_pages_under_the_tool_result_cap(rt, script):
    ws = rt.profiles.get("default").workspace
    (ws / "big.md").write_text("".join(f"row {i:04d} " + "x" * 40 + "\n" for i in range(3000)), encoding="utf-8")
    script([{"tool_calls": [("read_file", {"path": "big.md"})]},
            lambda msgs, tools: {"tool_calls": [("read_file", {"path": "big.md", "offset": int(
                json.dumps(msgs[-1]["content"]).split("offset=")[1].split(" ")[0])})]},
            {"content": "read it"}])
    agent = rt.agent("default")
    agent.run("read big.md")
    first, second = [m["content"] for m in tool_results(agent)]
    assert len(first) < 24_000 and "cut from the middle" not in first
    assert "(3000 lines), showing 1-" in first and "call read_file again with offset=" in first
    end = int(first.split("showing 1-")[1].split("\n")[0])
    assert f"row {end - 1:04d}" in first and f"row {end:04d}" not in first  # whole lines, nothing skipped
    assert second.splitlines()[1].lstrip().startswith(f"{end + 1}\trow {end:04d}")


def test_search_files_accepts_a_single_file_and_rejects_a_missing_path(rt, script):
    ws = rt.profiles.get("default").workspace
    (ws / "docs").mkdir()
    (ws / "docs" / "report.md").write_text("benchmark: 98.3 ms\nend\n", encoding="utf-8")
    script([{"tool_calls": [("search_files", {"pattern": "98\\.3", "path": "docs/report.md"}),
                            ("search_files", {"pattern": "x", "path": "docs/nope.md"})]},
            {"content": "checked"}])
    agent = rt.agent("default")
    agent.run("check the report")
    found, missing = [m["content"] for m in tool_results(agent)]
    assert "report.md:1: benchmark: 98.3 ms" in found
    assert missing.startswith("ERROR") and "does not exist" in missing


# --------------------------------------------------------------------------- delegation

def test_teammate_files_come_back_and_results_show_the_budget(rt, script):
    make_team(rt)
    script({
        "lead": [{"tool_calls": [("delegate_task", {"tasks": [
                     {"to": "coder", "goal": "write the notes", "expected_output": "Write notes/out.md"}]})]},
                 {"content": "done"}],
        "coder": [{"tool_calls": [("write_file", {"path": "notes/out.md", "content": "# Notes\n"}),
                                  ("write_file", {"path": "scratch.txt", "content": "working"})]},
                  {"content": "notes/out.md written"}],
    })
    lead = rt.agent("lead")
    lead.run("get notes")
    result = json.loads(tool_results(lead)[0]["content"])[0]
    assert result["files_in_your_folder"] == ["inbox/from-coder/notes/out.md", "inbox/from-coder/scratch.txt"]
    ws = rt.profiles.get("lead").workspace
    assert (ws / "inbox/from-coder/notes/out.md").read_text() == "# Notes\n"
    assert "model calls" in result["run_budget"] and "weighted tokens" in result["run_budget"]
    # the teammate is told it need not share the files itself
    coder_sess = SessionStore(rt.profiles.get("coder")).list(kinds=("delegation",))[0]
    first = SessionStore(rt.profiles.get("coder")).messages(coder_sess.id)[1]["content"]
    assert "copied back to @lead automatically" in first


def test_board_counts_a_stopped_run_with_its_file_as_done_and_keeps_finished_work(rt, script):
    make_team(rt)
    rt.profiles.update("coder", settings={"max_iterations": 2})
    tid = rt.board.add("dm:lead", "write report", assignee="coder", created_by="lead")["id"]
    script({
        "lead": [{"tool_calls": [("delegate_task", {"tasks": [
                     {"to": "coder", "task_id": tid, "goal": "write it", "expected_output": "report.md"}]})]},
                 {"content": "first round done"},
                 {"tool_calls": [("delegate_task", {"tasks": [
                     {"to": "coder", "task_id": tid, "goal": "check it", "expected_output": "review-2.md"}]})]},
                 {"content": "second round stopped"}],
        "coder": [{"tool_calls": [("write_file", {"path": "report.md", "content": "# Report\n"})]},
                  {"tool_calls": [("run_shell", {"command": "echo still polishing"})]},
                  {"content": "stopped at the step limit; report.md is written"},
                  # follow-up: never writes review-2.md before the step limit
                  {"tool_calls": [("run_shell", {"command": "echo reading"})]},
                  {"tool_calls": [("run_shell", {"command": "echo reading more"})]},
                  {"content": "ran out of steps"}],
    })
    lead = rt.agent("lead")
    lead.run("round one")
    task = rt.board.get(tid)
    first = json.loads(tool_results(lead)[0]["content"])[0]
    assert first["status"] == "max_iterations" and "requested file(s) were written" in first["note"]
    assert task["status"] == "done" and task["result"].startswith("[stopped early (max_iterations)")
    lead.run("round two")
    task = rt.board.get(tid)
    assert task["status"] == "done"
    assert task["result"].startswith("[A follow-up run stopped (max_iterations)") and "report.md is written" in task["result"]


def test_reflection_is_recorded_but_not_charged_to_the_run(rt, script):
    script([{"content": "hello"}])
    agent = rt.agent("default")
    agent.settings.reflection = True
    agent.run("say hello")
    purposes = [r["purpose"] for r in rt.shared.query("SELECT purpose FROM llm_calls WHERE session_id=?", (agent.session_id,))]
    assert purposes.count("reflection") == 1
    assert agent.budget.calls == purposes.count("turn") == 1


# --------------------------------------------------------------------------- plan and budget notes

def test_untouched_plan_gets_one_reminder(rt, script):
    plan = {"todos": [{"id": "1", "content": "search", "status": "in_progress"},
                      {"id": "2", "content": "write", "status": "pending"}]}
    steps = [{"tool_calls": [("todo", plan)]}]
    steps += [{"tool_calls": [("run_shell", {"command": f"echo step {i}"})]} for i in range(12)]
    steps.append({"content": "finished"})
    script(steps)
    agent = rt.agent("default")
    agent.run("do the work")
    notes = [m["content"] for m in agent.sessions.messages(agent.session_id)
             if m["role"] == "user" and "Your plan shows" in str(m["content"])]
    assert len(notes) == 1 and "0 of 2 items done" in notes[0]


def test_plan_updates_reset_the_reminder(rt, script):
    plan = [{"id": "1", "content": "a", "status": "in_progress"}, {"id": "2", "content": "b", "status": "pending"}]
    steps = [{"tool_calls": [("todo", {"todos": plan})]}]
    for i in range(12):
        steps.append({"tool_calls": [("run_shell", {"command": f"echo {i}"})]})
        if i % 5 == 4:
            steps.append({"tool_calls": [("todo", {"todos": [{"id": "1", "status": "in_progress"}], "merge": True})]})
    steps.append({"content": "finished"})
    script(steps)
    agent = rt.agent("default")
    agent.run("do the work")
    assert not any("Your plan shows" in str(m["content"]) for m in agent.sessions.messages(agent.session_id) if m["role"] == "user")


def test_root_agent_is_told_when_most_of_the_budget_is_spent(rt, script):
    rt.profiles.update("default", settings={"max_run_calls": 10})
    script([{"tool_calls": [("run_shell", {"command": f"echo {i}"})]} for i in range(8)] + [{"content": "wrapped up"}])
    agent = rt.agent("default")
    agent.run("work")
    notes = [m["content"] for m in agent.sessions.messages(agent.session_id)
             if m["role"] == "user" and str(m["content"]).startswith("[system] Run budget:")]
    assert len(notes) == 1 and "7/10 model calls" in notes[0]
