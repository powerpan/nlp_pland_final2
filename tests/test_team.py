from __future__ import annotations

import os
import threading
import time

import pytest

from pland.sandbox import DockerBackend
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
                 {"content": "!handoff @coder Please confirm the API.\nPlan posted."}],
    })
    out = rt.rooms.send(room["id"], "Let's build a calculator", background=False)["result"]
    speakers = [m["speaker"] for m in rt.rooms.messages(room["id"]) if m["kind"] == "message"]
    assert speakers[:3] == ["user", "coder", "lead"]  # writer passed; members speak before the lead
    assert out["lead"] == "lead"
    assert rt.board.list(room["id"])[0]["assignee"] == "coder"
    # The lead explicitly handed off → coder got a second-round turn.
    assert speakers[-1] == "coder"


def test_room_mention_scopes_round(rt, script):
    make_team(rt)
    room = rt.rooms.create("proj2", ["lead", "coder", "writer"])
    llm = script({"writer": [{"content": "Docs plan ready."}]})
    rt.rooms.send(room["id"], "@writer draft the docs outline", background=False)
    called = {name for name, _ in llm.calls}
    assert called == {"writer"}


def test_summary_mentions_do_not_schedule_room_turns(rt, script):
    make_team(rt)
    room = rt.rooms.create("summary", ["lead", "coder", "writer"], lead="lead")
    llm = script({"lead": ["Complete.\n- @coder: implementation\n@writer wrote the guide."]})
    rt.rooms.send(room["id"], "@lead build the project", background=False)
    assert [name for name, _ in llm.calls] == ["lead"]


@pytest.mark.parametrize(("filename", "first_verdict", "verdict"), [
    ("main.py", "PASS", "PASS"),
    ("README.md", "PASS", "FAIL"),
    ("settings.yaml", "FAIL", "PASS"),
])
def test_reviewed_changes_are_rechecked_on_the_same_card_before_delivery(rt, script, filename, first_verdict, verdict):
    make_team(rt)
    room = rt.rooms.create("review", ["lead", "coder"], lead="lead")
    rid = room["id"]
    folder = rt.rooms.shared_dir(rid)
    (folder / filename).write_text("ORIGINAL_VALUE\n")
    (folder / "reference.txt").write_text("stable reference\n")

    def recheck(messages, tools):
        prompt = messages[-1]["content"]
        assert "+REVISED_VALUE" in prompt and "-ORIGINAL_VALUE" in prompt
        assert "unchanged" in prompt.lower()
        if first_verdict == "FAIL":
            assert "Initial defect." in prompt
        assert not any(m["content"] == "Everything passed. @coder wrote the implementation."
                       for m in rt.rooms.messages(rid))
        return {"tool_calls": [("write_file", {"path": "shared/check.md", "content": f"Verdict: {verdict}\nRechecked."})]}

    llm = script({
        "lead": [
            {"tool_calls": [("delegate_task", {"tasks": [{
                "to": "coder", "goal": "Check the output",
                "review": {"inputs": [f"shared/{filename}", "shared/reference.txt"], "report": "shared/check.md"},
            }]})]},
            {"tool_calls": [("write_file", {"path": f"shared/{filename}", "content": "REVISED_VALUE\n"})]},
            {"content": "Everything passed. @coder wrote the implementation."},
        ],
        "coder": [
            {"tool_calls": [("write_file", {"path": "shared/check.md", "content": f"Verdict: {first_verdict}\nInitial defect."})]},
            {"content": "First review finished."},
            recheck, {"content": "Focused review finished."},
        ],
    })
    original_chat = llm.chat

    def stream_reply(*args, **kwargs):
        reply = original_chat(*args, **kwargs)
        if reply.content.startswith("Everything passed") and kwargs.get("on_delta"):
            kwargs["on_delta"]("content", reply.content)
        return reply

    llm.chat = stream_reply
    events = []
    subscription = rt.bus.subscribe(events.append)
    try:
        rt.rooms.send(rid, "@lead finish the file", background=False)
    finally:
        rt.bus.unsubscribe(subscription)
    assert not any(e["type"] == "assistant.delta" and "Everything passed" in e.get("text", "") for e in events)
    card, = rt.board.list(rid)
    messages = [m for m in rt.rooms.messages(rid) if m["speaker"] == "lead" and m["kind"] == "message"]
    assert len(messages) == 1
    if verdict == "PASS":
        assert card["status"] == "done" and card["review"]["verdict"] == "pass"
        assert "Everything passed" in messages[0]["content"]
    else:
        assert card["status"] == "blocked" and card["review"]["verdict"] == "fail"
        assert "Everything passed" not in messages[0]["content"]
        assert "check.md" in messages[0]["content"]
    assert len([name for name, _ in llm.calls if name == "coder"]) == 4


def test_a_stale_review_from_an_earlier_turn_does_not_block_unrelated_work(rt, script):
    make_team(rt)
    rid = rt.rooms.create("review and other work", ["lead", "coder", "writer"], lead="lead")["id"]
    shared = rt.rooms.shared_dir(rid)
    (shared / "old.txt").write_text("Old output")
    llm = script({
        "lead": [
            {"tool_calls": [("delegate_task", {"tasks": [{
                "to": "coder", "goal": "Review the old output",
                "review": {"inputs": ["shared/old.txt"], "report": "shared/check.md"},
            }]})]},
            {"content": "First job complete."},
            {"tool_calls": [("delegate_task", {"tasks": [{"to": "writer", "goal": "Write another document"}]})]},
            {"content": "Second job complete."},
        ],
        "coder": [
            {"tool_calls": [("write_file", {"path": "shared/check.md", "content": "Verdict: PASS\nChecked."})]},
            {"content": "First review finished."},
        ],
        "writer": [{"content": "Other work finished."}],
    })
    rt.rooms.send(rid, "@lead review the file", background=False)
    (shared / "old.txt").write_text("Externally revised")
    rt.rooms.send(rid, "@lead do unrelated work", background=False)
    assert rt.rooms.messages(rid)[-1]["content"] == "Second job complete."
    assert len([name for name, _ in llm.calls if name == "coder"]) == 2
    assert rt.board.reviewed(rid)[0]["review"]["verdict"] == "stale"


def test_binary_recheck_is_scoped_to_changed_files(tmp_path):
    from pland.team.review import finish_review, prepare_review

    asset = tmp_path / "preview.bin"
    asset.write_bytes(b"\x00\xfffirst")
    (tmp_path / "guide.md").write_text("shared reference")
    report = tmp_path / "check.md"
    spec = {"inputs": ["shared/preview.bin", "shared/guide.md"], "report": "shared/check.md"}
    initial = prepare_review(tmp_path, spec)
    report.write_text("Verdict: PASS\nChecked.")
    last = finish_review(tmp_path, initial, "completed")
    asset.write_bytes(b"\x00\xffsecond")
    recheck = prepare_review(tmp_path, spec, last)
    assert recheck["changed_inputs"] == ["shared/preview.bin"]
    assert recheck["_changes"] == {}
    assert recheck["inputs"]["shared/guide.md"] == initial["inputs"]["shared/guide.md"]


def test_room_member_discussion_turn_is_read_only(rt, script):
    make_team(rt)
    room = rt.rooms.create("disc", ["lead", "coder"], lead="lead")
    script({
        "coder": [{"tool_calls": [("write_file", {"path": "x.py", "content": "x"})]}, {"content": "I can write x.py"}],
        "lead": [{"content": "ok"}],
    })
    rt.rooms.send(room["id"], "make x", background=False)
    assert not (rt.profiles.get("coder").workspace / "x.py").exists()


def test_clarification_precedes_and_invalidates_same_turn_delegation(rt, script):
    make_team(rt)
    room = rt.rooms.create("clarify", ["lead", "coder"], lead="lead")
    llm = script({
        "lead": [
            {"tool_calls": [
                ("delegate_task", {"tasks": [{"to": "coder", "goal": "Use the unconfirmed input"}]}),
                ("ask_user", {"question": "Which input should we use?"}),
            ]},
            {"tool_calls": [("delegate_task", {"tasks": [{"to": "coder", "goal": "Use the confirmed defaults"}]})]},
            {"content": "Completed."},
        ],
        "coder": ["Please ask @user about the input first.", "Used the confirmed defaults."],
    })
    result = rt.rooms.send(room["id"], "Make the analysis", background=False)["result"]
    tasks = rt.board.list(room["id"])
    assert [task["title"] for task in tasks] == ["Use the confirmed defaults"]
    second_lead_turn = [messages for name, messages in llm.calls if name == "lead"][1]
    assert any("use defaults" in m["content"] for m in second_lead_turn if m["role"] == "tool")
    assert not result["needs_you"] and not rt.rooms.get(room["id"])["needs_you"]


def test_lead_can_handoff_to_user_in_text(rt, script):
    make_team(rt)
    room = rt.rooms.create("handoff", ["lead", "coder"], lead="lead")
    script({"coder": ["[PASS]"], "lead": ["@user please select an input."]})
    result = rt.rooms.send(room["id"], "Make the analysis", background=False)["result"]
    assert result["needs_you"]


def test_review_pass_only_applies_to_the_reviewed_version(rt, script):
    make_team(rt)
    room = rt.rooms.create("review", ["lead", "coder"], lead="lead")
    path = rt.rooms.shared_dir(room["id"]) / "draft.md"
    path.write_text("# Draft v1\n")
    script({
        "lead": [
            {"tool_calls": [("delegate_task", {"tasks": [{
                "to": "coder", "goal": "Review the draft",
                "review": {"inputs": ["shared/draft.md"], "report": "shared/review.md"},
            }]})]},
            {"content": "Review returned."},
        ],
        "coder": [
            {"tool_calls": [("write_file", {"path": "shared/review.md", "content": "Verdict: PASS\nChecked."})]},
            {"content": "Checked."},
        ],
    })
    rt.rooms.send(room["id"], "@lead review the draft", background=False)
    card = rt.board.list(room["id"])[0]
    assert card["status"] == "done" and card["review"]["verdict"] == "pass"
    path.write_text("# Draft v2\n")
    card = rt.board.get(card["id"])
    assert card["status"] == "blocked" and card["review"]["verdict"] == "stale"


def test_review_failure_cannot_be_marked_done_by_the_caller(rt, script):
    make_team(rt)
    room = rt.rooms.create("review", ["lead", "coder"], lead="lead")
    (rt.rooms.shared_dir(room["id"]) / "draft.md").write_text("# Draft\n")

    def mark_done(messages, tools):
        task, = rt.board.list(room["id"])
        return {"tool_calls": [("team_tasks", {"action": "update", "task_id": task["id"], "status": "done"})]}

    script({
        "lead": [
            {"tool_calls": [("delegate_task", {"tasks": [{
                "to": "coder", "goal": "Review the draft",
                "review": {"inputs": ["shared/draft.md"], "report": "shared/review.md"},
            }]})]},
            mark_done, {"content": "Review returned."},
        ],
        "coder": [
            {"tool_calls": [("write_file", {"path": "shared/review.md", "content": "Verdict: FAIL\nFix the draft."})]},
            {"content": "Fix the draft."},
        ],
    })
    rt.rooms.send(room["id"], "@lead review the draft", background=False)
    card, = rt.board.list(room["id"])
    assert card["status"] == "blocked"
    assert card["review"]["verdict"] == "fail" and card["review"]["report_written"]


def test_step_limited_review_keeps_report_without_claiming_pass(rt, script):
    make_team(rt)
    room = rt.rooms.create("review", ["lead", "coder"], lead="lead")
    (rt.rooms.shared_dir(room["id"]) / "draft.md").write_text("# Draft\n")
    script({
        "lead": [
            {"tool_calls": [("delegate_task", {"tasks": [{
                "to": "coder", "goal": "Review the draft",
                "review": {"inputs": ["shared/draft.md"], "report": "shared/review.md", "max_steps": 2},
            }]})]},
            {"content": "Partial review returned."},
        ],
        "coder": [
            {"tool_calls": [("write_file", {"path": "shared/review.md", "content": "Verdict: PASS\nDraft."})]},
            {"tool_calls": [("read_file", {"path": "shared/draft.md"})]},
            {"content": "Partial review."},
        ],
    })
    rt.rooms.send(room["id"], "@lead review the draft", background=False)
    card, = rt.board.list(room["id"])
    assert card["status"] == "blocked"
    assert card["review"]["verdict"] == "incomplete" and card["review"]["report_written"]


def test_review_limits_are_set_by_the_platform(rt, script):
    from fastapi.testclient import TestClient
    from pland.server.app import create_app

    make_team(rt)
    room = rt.rooms.create("bounded review", ["lead", "coder"], lead="lead")
    rid = room["id"]
    (rt.rooms.shared_dir(rid) / "notes.txt").write_text("Notes")
    settings = TestClient(create_app(rt)).patch(
        "/api/settings", json={"review_max_steps": 4, "review_timeout_seconds": 12}
    )
    assert settings.status_code == 200
    assert settings.json()["values"]["review_timeout_seconds"] == 12

    def check_limits(messages, _tools):
        assert "at most 4 steps and 12 seconds" in messages[-1]["content"]
        return {"tool_calls": [("write_file", {
            "path": "shared/review.md", "content": "Verdict: PASS\nNotes checked."
        })]}

    script({
        "lead": [
            {"tool_calls": [("delegate_task", {"tasks": [{
                "to": "coder", "goal": "Review the meeting notes",
                "review": {"inputs": ["shared/notes.txt"], "report": "shared/review.md",
                           "max_steps": 120, "timeout_seconds": 800},
            }]})]},
            "Review complete.",
        ],
        "coder": [check_limits, "Done."],
    })

    rt.rooms.send(rid, "@lead review the notes", background=False)

    assert rt.board.reviewed(rid)[0]["review"]["verdict"] == "pass"


@pytest.mark.skipif(not DockerBackend.available() or os.environ.get("PLAND_SKIP_DOCKER"), reason="docker not available")
def test_review_deadline_stops_a_running_docker_tool(rt, script):
    make_team(rt)
    rid = rt.rooms.create("docker review", ["lead", "coder"], lead="lead")["id"]
    root = rt.rooms.shared_dir(rid)
    (root / "data.json").write_text("{}")
    coder = rt.profiles.update("coder", settings={"sandbox": {"backend": "docker", "docker_network": "none"}})
    backend = rt.backend_for(coder, coder.settings())
    assert backend.run("true", coder.workspace, mounts={"shared": root}).exit_code == 0

    script({
        "lead": [
            {"tool_calls": [("delegate_task", {"tasks": [{
                "to": "coder", "goal": "Review the JSON",
                "review": {"inputs": ["shared/data.json"], "report": "shared/review.md", "timeout_seconds": 2},
            }]})]},
            "Review completed.",
        ],
        "coder": [
            {"tool_calls": [("run_shell", {
                "command": "touch shared/started; sleep 8; touch shared/late", "timeout": 10
            })]},
            "Done.",
        ],
    })

    start = time.monotonic()
    rt.rooms.send(rid, "@lead verify the JSON", background=False)
    assert time.monotonic() - start < 5
    assert (root / "started").exists() and not (root / "late").exists()
    assert rt.board.reviewed(rid)[0]["review"]["verdict"] == "incomplete"
    assert "Review completed." not in rt.rooms.messages(rid)[-1]["content"]


@pytest.mark.parametrize("fast", [False, True])
def test_partial_delivery_shows_verified_and_pending_scopes(rt, script, fast):
    make_team(rt)
    rid = rt.rooms.create("partial delivery", ["lead", "coder", "writer"], lead="lead", fast_mode=fast)["id"]
    root = rt.rooms.shared_dir(rid)
    (root / "module.py").write_text("print(1)")
    (root / "fixture.json").write_text("{}")

    def review(goal, inputs, report):
        return {"tool_calls": [("delegate_task", {"tasks": [{
            "to": "coder", "goal": goal, "review": {"inputs": inputs, "report": report},
        }]})]}

    script({
        "lead": [
            {"tool_calls": [("delegate_task", {"tasks": [{
                "to": "writer", "goal": "Write the guide", "expected_output": "shared/guide.md"
            }]})]},
            review("Full compatibility", ["shared/module.py", "shared/fixture.json"], "shared/full.md"),
            review("Code check", ["shared/module.py"], "shared/code-check.md"),
            "Everything passed. @coder verified every requirement.",
        ],
        "coder": [
            "Compatibility review stopped without a verdict.",
            {"tool_calls": [("write_file", {"path": "shared/code-check.md", "content": "Verdict: PASS\nCode checked."})]},
            "Code check passed.",
        ],
        "writer": [
            {"tool_calls": [("write_file", {"path": "shared/guide.md", "content": "Usage guide."})]},
            "Guide ready.",
        ],
    })

    rt.rooms.send(rid, "@lead deliver the module", background=False)

    final = next(m["content"] for m in reversed(rt.rooms.messages(rid))
                 if m["speaker"] == "lead" and m["kind"] == "message")
    assert "Everything passed" not in final
    assert "Code check: PASS" in final and "shared/code-check.md" in final
    assert "Full compatibility: INCOMPLETE" in final and "shared/fixture.json" in final
    assert "shared/guide.md" in final


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

@pytest.mark.parametrize(("report", "expected"), [
    ("# Compatibility review\n\nVerdict: FAIL\nBoundary excluded.", "fail"),
    ("\ufeff# Export review\r\n\r\nVERDICT: PASS\r\nChecked.", "pass"),
    ("  vErDiCt : fAiL\nMissing a prerequisite.", "fail"),
    ("Verdict: PASS or FAIL\nVerdict: PASS", "incomplete"),
    ("# Notes\n\nA quoted example follows.\nVerdict: PASS", "incomplete"),
    ("# Notes\n\n```\nVerdict: PASS\n```", "incomplete"),
    ("Verdict: INCOMPLETE\nCitations checked; one calculation remains.", "incomplete"),
])
def test_review_reads_only_a_header_verdict(tmp_path, report, expected):
    from pland.team.review import finish_review, prepare_review

    (tmp_path / "input").write_text("sample")
    review = prepare_review(tmp_path, {"inputs": ["shared/input"], "report": "shared/result.md"})
    (tmp_path / "result.md").write_text(report)
    result = finish_review(tmp_path, review, "completed")
    assert result["verdict"] == expected
    if expected == "incomplete":
        reason = "explicitly left checks open" if report.startswith("Verdict: INCOMPLETE") else "Unrecognized verdict header"
        assert reason in result["verdict_reason"]
    else:
        assert "verdict_reason" not in result


@pytest.mark.parametrize(("observation", "evidence", "expected"), [
    ("Exercise the exported file", "Evidence: observed | Opened the export and read back all 12 records.", "pass"),
    ("Exercise the exported file", "EVIDENCE : OBSERVED | Read back all 12 records.", "pass"),
    ("Exercise the exported file", "Evidence: estimated | Counted source rows.", "incomplete"),
    ("Exercise the exported file", "Evidence: observed | ", "incomplete"),
    ("Exercise the exported file", "No export reader was available.", "incomplete"),
    (None, "Evidence: unavailable | Missing the target device.", "incomplete"),
    (None, "EVIDENCE: unavailable | Missing the target device.", "incomplete"),
    (None, "Evidence: estimated | Computed the requested forecast and its interval from the supplied data.", "pass"),
    (None, "The proposed sampling method and its assumptions are internally consistent.", "pass"),
])
def test_verdict_respects_requested_observation(tmp_path, observation, evidence, expected):
    from pland.team.review import prepare_review, finish_review

    (tmp_path / "input").write_text("sample")
    review = prepare_review(tmp_path, {"inputs": ["shared/input"], "report": "shared/result.md",
                                      "observation": observation})
    (tmp_path / "result.md").write_text(f"Verdict: PASS\n{evidence}\n")
    assert finish_review(tmp_path, review, "completed")["verdict"] == expected
