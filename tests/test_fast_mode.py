"""Fast Mode for group tasks (pland/team/fast.py): command-time limits, card checks, review limits and reuse, and the
closing summary of verified files. Scripted models only; shell commands are faked where their duration matters."""

from __future__ import annotations

import time

import pytest

from pland.agent import Agent
from pland.sandbox import backends
from pland.sandbox.backends import ExecResult
from pland.config import AgentSettings, save_global_settings
from pland.team.fast import FastLimit, FastMode


def team(rt, *, fast=True):
    rt.profiles.create("lead", title="Lead", description="plans", settings={"model": {"thinking": True, "reasoning_effort": "high"}})
    rt.profiles.create("reviewer", title="QA Reviewer", description="reviews",
                       settings={"model": {"thinking": True, "reasoning_effort": "max"}})
    return rt.rooms.create("fastroom", ["lead", "reviewer"], lead="lead", fast_mode=fast)


def tool_outputs(rt, name):
    from pland.sessions import SessionStore

    store = SessionStore(rt.profiles.get(name))
    out = []
    for sess in store.list():
        out += [m["content"] for m in store.messages(sess.id) if m["role"] == "tool"]
    return out


@pytest.fixture()
def fake_exec(monkeypatch):
    """Shell commands return at once but report that they ran for their whole timeout (or `durations`)."""
    seen: list[dict] = []

    def run(self, command, cwd, *, timeout=None, env=None, mounts=None, cancel=None):
        seen.append({"command": command, "timeout": timeout})
        took = timeout or 0.0
        return ExecResult(0, "ok\n", "", timed_out=False, duration=took)

    monkeypatch.setattr(backends.LocalBackend, "run", run)
    return seen


# ---------------------------------------------------------------------- command time
def test_reserve_caps_each_command_and_the_team_total(rt):
    fm = FastMode(rt, "room_x")
    held = [fm.reserve(600) for _ in range(3)]
    assert held == [25.0, 25.0, 25.0]
    for h in held:
        fm.settle(h, 40.0)  # a command cannot be charged more than it was allowed to run
    assert fm.used == 75.0
    assert fm.reserve(None) == 15.0  # only what is left of the 90 s
    fm.settle(15.0, 15.0)
    with pytest.raises(FastLimit, match="used up"):
        fm.reserve(5)
    assert fm.refused == 1


def test_parallel_reservations_never_exceed_the_team_total(rt):
    fm = FastMode(rt, "room_x")
    held = [fm.reserve(None) for _ in range(3)] + [fm.reserve(None)]  # all still running
    assert sum(held) == 90.0
    with pytest.raises(FastLimit):
        fm.reserve(None)


def test_shell_commands_in_a_fast_group_get_the_limits(rt, script, fake_exec):
    room = team(rt)
    script({"lead": [{"tool_calls": [("run_shell", {"command": "echo 1", "timeout": 600})]},
                     {"tool_calls": [("run_shell", {"command": "echo 2"})]},
                     {"tool_calls": [("run_shell", {"command": "echo 3"})]},
                     {"tool_calls": [("run_shell", {"command": "echo 4"})]},
                     {"tool_calls": [("run_shell", {"command": "echo 5"})]},
                     {"content": "done"}],
            "reviewer": [{"content": "[PASS]"}]})
    out = rt.rooms.send(room["id"], "@lead go", background=False)["result"]
    assert [c["timeout"] for c in fake_exec] == [25.0, 25.0, 25.0, 15.0]  # the 5th never started
    assert out["fast_mode"]["command_seconds"] == 90.0 and out["fast_mode"]["refused"] == 1
    assert any("command time is used up" in t for t in tool_outputs(rt, "lead"))


def test_without_fast_mode_nothing_changes(rt, script, fake_exec):
    room = team(rt, fast=False)
    seen_tools: list[set] = []

    def lead_step(msgs, tools):
        seen_tools.append({t["function"]["name"] for t in tools or []})
        return {"tool_calls": [("run_shell", {"command": "echo 1", "timeout": 300})]}

    script({"lead": [lead_step, {"content": "done"}], "reviewer": [{"content": "[PASS]"}]})
    out = rt.rooms.send(room["id"], "@lead go", background=False)["result"]
    assert fake_exec[0]["timeout"] == 300
    assert "fast_mode" not in out
    assert "run_checks" not in seen_tools[0]


def review_call(task_id=None, inputs=("shared/a.py",), goal="review the module", report="shared/review.md", criterion=None):
    task = {"to": "reviewer", "goal": goal, "review": {"inputs": list(inputs), "report": report}}
    if criterion:
        task["review"]["criterion"] = criterion
    if task_id:
        task["task_id"] = task_id
    return {"tool_calls": [("delegate_task", {"tasks": [task]})]}


def write_report(verdict, report="shared/review.md", seen=None):
    """A reviewer step: note the request, then write the report whose first line is the verdict."""
    def step(msgs, tools):
        if seen is not None:
            seen.append(msgs[-1]["content"])
        return {"tool_calls": [("write_file", {"path": report, "content": f"Verdict: {verdict}\nchecked {len(seen or [])}\n"})]}
    return step


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize(("header", "verdict", "reason"), [
    ("VERDICT: PASS", "pass", ""),
    ("Verdict: pass/fail", "incomplete", "Unrecognized verdict header"),
])
def test_group_publishes_the_review_decision_or_its_parse_error(rt, script, fast, header, verdict, reason):
    rid = team(rt, fast=fast)["id"]
    root = rt.rooms.shared_dir(rid)
    (root / "report.md").write_text("Six of eight respondents agreed.\n")
    requirement = "Describe the share of respondents who agreed."
    review = review_call(inputs=["shared/report.md"], criterion=requirement)
    script({"lead": [review, {"content": "The report is ready."}],
            "reviewer": [{"tool_calls": [("write_file", {"path": "shared/review.md", "content":
                         f"{header}\nEVIDENCE: observed | 6/8 equals 75%; the report uses a count."})]},
                         {"content": "Finished checking."}]})
    rt.rooms.send(rid, "@lead review the survey report", background=False)

    card, = rt.board.reviewed(rid)
    assert card["review"]["verdict"] == verdict
    assert card["review"]["evidence"]["basis"] == "observed"
    final = [m["content"] for m in rt.rooms.messages(rid) if m["speaker"] == "lead" and m["kind"] == "message"][-1]
    if reason:
        assert card["status"] == "blocked" and reason in card["result"] and reason in final
        if fast:
            assert reason in next(m["content"] for m in rt.rooms.messages(rid) if "fast_mode" in m["meta"])
    else:
        assert card["status"] == "done" and f"{requirement}: PASS" in final


@pytest.mark.parametrize("fast", [False, True])
def test_reviewer_can_correct_its_evidence_line_before_handoff(rt, script, fast):
    rid = team(rt, fast=fast)["id"]
    root = rt.rooms.shared_dir(rid)
    (root / "receipt.txt").write_text("Delivered: 8 parcels")
    request = review_call(inputs=["shared/receipt.txt"], criterion="Verify the delivery count")
    request["tool_calls"][0][1]["tasks"][0]["review"]["observation"] = "Read back the count from the receipt."
    def draft(messages, tools):
        assert "Delivered: 8 parcels" in messages[-1]["content"]
        return {"tool_calls": [("write_file", {"path": "shared/review.md",
                    "content": "VERDICT: PASS\nI opened the receipt and found 8 parcels."})]}
    def correct(messages, tools):
        assert "Evidence: observed |" in messages[-1]["content"]
        return {"tool_calls": [("edit_file", {"path": "shared/review.md", "old_text": "I opened",
                                              "new_text": "EVIDENCE: observed | I opened"})]}
    script({"lead": [request, {"content": "Ready."}], "reviewer": [
        {"tool_calls": [("read_file", {"path": "shared/receipt.txt"})]}, draft, correct, {"content": "Checked."}]})
    rt.rooms.send(rid, "@lead verify", background=False)
    card, = rt.board.reviewed(rid)
    assert card["status"] == "done" and card["review"]["evidence"]["detail"] == "I opened the receipt and found 8 parcels."
    outputs = tool_outputs(rt, "reviewer")
    assert sum("Review report format:" in msg for msg in outputs) == 1
    assert len(rt.shared.query("SELECT id FROM deliveries WHERE target='reviewer'")) == 1


def test_each_bot_keeps_its_configured_reasoning(rt, script, monkeypatch):
    room = team(rt)
    (rt.rooms.shared_dir(room["id"]) / "a.py").write_text("def f():\n    return 1\n")
    calls: list[tuple] = []
    orig = Agent.chat

    def chat(self, messages, tools=None, *, purpose="turn", **kw):
        if purpose == "turn":
            calls.append((self.profile.name, self.settings.model.reasoning_effort, kw.get("thinking"), kw.get("effort")))
        return orig(self, messages, tools, purpose=purpose, **kw)

    monkeypatch.setattr(Agent, "chat", chat)
    script({"lead": [review_call(), {"content": "done"}], "reviewer": [write_report("PASS"), {"content": "PASS"}]})
    rt.rooms.send(room["id"], "@lead go", background=False)
    assert ("lead", "high", None, None) in calls
    assert ("reviewer", "max", None, None) in calls  # the review thinks at the reviewer's own level
    assert all(c[2] is None and c[3] is None for c in calls)  # Fast Mode overrides nobody's thinking


def test_one_review_then_reuse_then_one_change_only_follow_up_then_refused(rt, script):
    room = team(rt)
    shared = rt.rooms.shared_dir(room["id"])
    (shared / "a.py").write_text("def f():\n    return 1\n")
    (shared / "b.py").write_text("X = 1\n")
    card = rt.board.add(room["id"], "review the module", assignee="reviewer", created_by="lead")["id"]
    seen: list[str] = []

    def edit(text, goal):
        def step(msgs, tools):
            (shared / "a.py").write_text(text)
            return review_call(card, ("shared/a.py", "shared/b.py"), goal, criterion="review the module")
        return step

    script({
        "lead": [review_call(card, ("shared/a.py", "shared/b.py")),                       # 1: the review
                 review_call(card, ("shared/a.py", "shared/b.py"), "review again", criterion="review the module"),       # 2: unchanged -> reused
                 edit("def f():\n    return 2\n", "review the fix"),                    # 3: a.py changed -> follow-up
                 edit("def f():\n    return 3\n", "review the second fix"),             # 4: changed again -> refused
                 {"content": "done"}],
        "reviewer": [write_report("FAIL", seen=seen), {"content": "FAIL: f returns 1"},
                     write_report("PASS", seen=seen), {"content": "PASS"}],
    })
    rt.rooms.send(room["id"], "@lead ship it", background=False)
    outs = tool_outputs(rt, "lead")
    assert len(seen) == 2  # the review and the follow-up ran; the reuse and the refusal did not
    assert "at most 16 steps and 210 seconds" in seen[0]
    assert "at most 16 steps and 120 seconds" in seen[1]
    assert "CHANGE-ONLY REVIEW. Recheck only: shared/a.py" in seen[1] and "+    return 2" in seen[1]
    assert any('"status": "reused"' in t and "Review verdict: FAIL (reused" in t for t in outs)
    assert any("already had its review and its one follow-up" in t for t in outs)
    rec = rt.board.review_record(card)
    assert rec["round"] == 2 and rec["verdict"] == "pass"
    assert any(m["content"].startswith("↺ reused an earlier review") for m in rt.rooms.messages(room["id"]))


def test_a_second_unfinished_continuation_is_refused(rt, script):
    """A missing verdict gets one bounded continuation, even when the bytes are identical."""
    room = team(rt)
    (rt.rooms.shared_dir(room["id"]) / "a.py").write_text("x = 1\n")
    card = rt.board.add(room["id"], "review a", assignee="reviewer", created_by="lead")["id"]
    llm = script({"lead": [review_call(card), review_call(card, goal="continue", criterion="review the module"),
                            review_call(card, goal="another continuation", criterion="review the module"), {"content": "done"}],
                  "reviewer": [{"content": "I ran out of ideas"}]})  # no report: the review is incomplete
    rt.rooms.send(room["id"], "@lead review", background=False)
    assert [n for n, _ in llm.calls].count("reviewer") == 2
    assert any("already used its continuation" in t for t in tool_outputs(rt, "lead"))


def test_a_review_is_capped_at_16_steps(rt, script):
    room = team(rt)
    (rt.rooms.shared_dir(room["id"]) / "a.py").write_text("x = 1\n")
    looping = [{"tool_calls": [("read_file", {"path": "shared/a.py", "offset": i + 1})]} for i in range(40)]
    llm = script({"lead": [review_call(), {"content": "done"}], "reviewer": looping})
    rt.rooms.send(room["id"], "@lead review", background=False)
    # 16 loop steps, then at most one write-only call to save the missing report and the closing answer
    assert 0 < [n for n, _ in llm.calls].count("reviewer") <= 2 * (AgentSettings.fast_review_steps + 2)  # includes one bounded continuation


def test_a_review_is_stopped_at_its_time_limit(rt, script, monkeypatch):
    save_global_settings(rt.root, {"fast_review_seconds": 1})
    room = team(rt)
    (rt.rooms.shared_dir(room["id"]) / "a.py").write_text("x = 1\n")

    def slow(msgs, tools):
        time.sleep(1.5)
        return {"tool_calls": [("read_file", {"path": "shared/a.py"})]}

    script({"lead": [review_call(), {"content": "done"}], "reviewer": [slow, slow, write_report("PASS")]})
    t0 = time.time()
    rt.rooms.send(room["id"], "@lead review", background=False)
    assert time.time() - t0 < 8
    card = rt.board.list(room["id"])[0]
    assert rt.board.review_record(card["id"])["verdict"] != "pass"


@pytest.mark.parametrize("fast", [False, True])
def test_reviews_are_reused_across_cards_and_requests(rt, script, fast):
    room = team(rt, fast=fast)
    (rt.rooms.shared_dir(room["id"]) / "a.py").write_text("x = 1\n")
    script({"lead": [review_call(criterion="original requirement"), {"content": "done"}], "reviewer": [write_report("PASS"), {"content": "PASS"}]})
    rt.rooms.send(room["id"], "@lead review", background=False)
    llm = script({"lead": [review_call(goal="independent review once more", criterion="original requirement",
                                       report="shared/second-receipt.md"), {"content": "done"}],
                  "reviewer": [write_report("PASS"), {"content": "PASS again"}]})
    out = rt.rooms.send(room["id"], "@lead review once more", background=False)["result"]
    assert "reviewer" not in [n for n, _ in llm.calls]  # the second request reused the verdict
    cards = rt.board.list(room["id"])
    assert len(cards) == 2 and all(c["review"]["verdict"] == "pass" and c["status"] == "done" for c in cards)
    if fast:
        assert out["fast_mode"]["verified"] == ["shared/a.py"]


@pytest.mark.parametrize("fast", [False, True])
def test_planned_review_and_its_revision_share_one_card(rt, script, fast):
    rid = team(rt, fast=fast)["id"]
    folder = rt.rooms.shared_dir(rid)
    (folder / "metrics.csv").write_text("total,1\n")
    inputs = ["shared/metrics.csv"]
    card = rt.board.add(rid, "Reconcile totals", description="Check shared/metrics.csv",
                        assignee="reviewer", created_by="lead")["id"]
    seen = []

    def revise(messages, tools):
        (folder / "metrics.csv").write_text("total,2\n")
        return review_call(inputs=inputs, goal="Check the correction", criterion="Totals agree")

    script({"lead": [review_call(inputs=inputs, goal="Audit the figures", criterion="Totals agree"),
                     review_call(card, inputs, "Audit the figures", criterion="Totals agree"),
                     revise, {"content": "Delivered."}],
            "reviewer": [write_report("FAIL", seen=seen), {"content": "Wrong sum"},
                         write_report("PASS", seen=seen), {"content": "Sum is correct"}]})
    result = rt.rooms.send(rid, "@lead check the totals", background=False)["result"]
    assert any('"status": "rejected"' in out and card in out for out in tool_outputs(rt, "lead"))
    only, = rt.board.list(rid)
    assert only["id"] == card and only["review"]["verdict"] == "pass"
    assert len(seen) == 2 and "Prior failing review excerpt" in seen[1] and "+total,2" in seen[1]
    if fast:
        assert result["fast_mode"]["verified"] == inputs


def test_distinct_reviews_cannot_overwrite_each_others_report(rt, script):
    rid = team(rt)["id"]
    (rt.rooms.shared_dir(rid) / "a.py").write_text("original")
    first = rt.board.add(rid, "Coverage", assignee="reviewer", created_by="lead")["id"]
    second = rt.board.add(rid, "Documentation", assignee="reviewer", created_by="lead")["id"]
    script({"lead": [review_call(first, criterion="Coverage"), review_call(second, criterion="Documentation"),
                     review_call(second, criterion="Documentation", report="shared/docs.md"), {"content": "done"}],
            "reviewer": [write_report("PASS"), {"content": "covered"},
                         write_report("FAIL", "shared/docs.md"), {"content": "incomplete documentation"}]})
    rt.rooms.send(rid, "@lead verify", background=False)
    assert any('"status": "rejected"' in out and first in out for out in tool_outputs(rt, "lead"))
    assert rt.board.get(first)["review"]["verdict"] == "pass"
    assert rt.board.get(second)["review"]["verdict"] == "fail"


def test_unrelated_plans_allow_ad_hoc_reviews_and_exact_titles_bind(rt, script):
    rid = team(rt)["id"]
    shared = rt.rooms.shared_dir(rid)
    (shared / "a.py").write_text("module")
    (shared / "abstract.txt").write_text("research question")
    card = rt.board.add(rid, "Check the abstract", description="Read shared/abstract.txt",
                        assignee="reviewer", created_by="lead")["id"]
    first = review_call(inputs=["shared/abstract.txt"], goal="Check the abstract", report="shared/abstract-review.md")
    script({"lead": [review_call(criterion="API compatibility"), first, {"content": "done"}],
            "reviewer": [write_report("PASS"), {"content": "compatible"},
                         write_report("FAIL", "shared/abstract-review.md"), {"content": "unclear question"}]})
    rt.rooms.send(rid, "@lead check both", background=False)
    assert len(rt.board.list(rid)) == 2
    assert rt.board.get(card)["review"]["verdict"] == "fail"


def test_missing_id_does_not_merge_changed_context_or_ambiguous_plans(rt, script):
    rid = team(rt)["id"]
    (rt.rooms.shared_dir(rid) / "a.py").write_text("sample")
    plans = [rt.board.add(rid, title, description="Check shared/a.py", assignee="reviewer",
                          created_by="lead")["id"] for title in ["local environment", "production settings"]]
    revised = review_call(goal="Review again", criterion="Starts correctly")
    revised["tool_calls"][0][1]["tasks"][0]["context"] = "Use production settings."
    script({"lead": [review_call(criterion="Starts correctly"), review_call(plans[0], criterion="Starts correctly"),
                     revised, {"content": "done"}],
            "reviewer": [write_report("PASS"), {"content": "observed locally"}]})
    rt.rooms.send(rid, "@lead verify", background=False)
    refusals = [out for out in tool_outputs(rt, "lead") if '"status": "rejected"' in out]
    assert len(refusals) == 2 and all(tid in refusals[0] for tid in plans)
    assert rt.board.get(plans[0])["review"]["verdict"] == "pass"
    assert rt.board.get(plans[1])["status"] == "todo"


def test_inferred_card_and_report_alias_share_delegation_locks(rt, script):
    from pland.team.delegation import delegate

    rid = team(rt)["id"]
    shared = rt.rooms.shared_dir(rid)
    (shared / "a.py").write_text("module")
    (shared / "receipts").mkdir()
    (shared / "alias").symlink_to(shared / "receipts", target_is_directory=True)
    card = rt.board.add(rid, "Compatibility", description="Check shared/a.py",
                        assignee="reviewer", created_by="lead")["id"]
    ctx = rt.agent("lead", room_id=rid)._context()
    task = review_call(goal="Compatibility", report="shared/alias/check.md")["tool_calls"][0][1]["tasks"][0]
    for kind, key in [("report", str(shared / "receipts/check.md")), ("task", card)]:
        with rt.session_lock(f"review:{rid}:{kind}", key):
            result, = delegate(ctx, [task])
        assert result["status"] == "rejected" and "already running" in result["error"]
    assert rt.board.get(card)["status"] == "todo" and len(rt.board.list(rid)) == 1


@pytest.mark.parametrize("fast", [False, True])
def test_observation_survives_retry_and_controls_reuse(rt, script, fast):
    rid = team(rt, fast=fast)["id"]
    shared = rt.rooms.shared_dir(rid)
    (shared / "a.py").write_text("test input")
    observation = "Read back the generated archive."
    first = review_call(criterion="The archive is usable", report="shared/initial.md")
    required = review_call(criterion="The archive is usable")
    required["tool_calls"][0][1]["tasks"][0]["review"]["observation"] = observation
    seen = []

    def observe(messages, tools):
        seen.append(messages[-1]["content"])
        return {"tool_calls": [("write_file", {"path": "shared/review.md",
                "content": "Verdict: PASS\nEvidence: observed | Reopened the archive and compared the entries."})]}

    script({"lead": [first, required, {"content": "done"}],
            "reviewer": [write_report("PASS", "shared/initial.md"), {"content": "static inspection"},
                         write_report("PASS"), {"content": "no observation"}]})
    rt.rooms.send(rid, "@lead inspect", background=False)
    cards = rt.board.reviewed(rid)
    assert [c["review"]["verdict"] for c in cards] == ["pass", "incomplete"]
    assert observation in [m["content"] for m in rt.rooms.messages(rid) if m["kind"] == "message"][-1]
    retry = review_call(cards[-1]["id"], criterion="The archive is usable")
    del retry["tool_calls"][0][1]["tasks"][0]["to"]
    copy = review_call(criterion="The archive is usable", report="shared/receipt.md")
    copy["tool_calls"][0][1]["tasks"][0]["review"]["observation"] = observation
    script({"lead": [retry, copy, {"content": "done"}], "reviewer": [observe, {"content": "read back"}]})
    rt.rooms.send(rid, "@lead finish", background=False)
    assert len(seen) == 1 and observation in seen[0]
    assert rt.board.get(cards[-1]["id"])["review"]["verdict"] == "pass"
    assert (shared / "receipt.md").read_text().splitlines()[1].startswith("Evidence: observed |")


@pytest.mark.parametrize("header", ["Verdict: PASS", "VERDICT: PASS"])
def test_a_reused_review_writes_the_report_the_lead_asked_for(rt, script, header):
    room = team(rt)
    shared = rt.rooms.shared_dir(room["id"])
    (shared / "a.py").write_text("x = 1\n")
    script({"lead": [review_call(criterion="original requirement"), review_call(goal="second review", criterion="original requirement", report="shared/review-2.md"), {"content": "done"}],
            "reviewer": [{"tool_calls": [("write_file", {"path": "shared/review.md",
                                                        "content": f"{header}\nChecked the module."})]}, {"content": "PASS"}]})
    rt.rooms.send(room["id"], "@lead review twice", background=False)
    copy = (shared / "review-2.md").read_text()
    assert copy.splitlines()[0] == header and copy.lower().count("verdict:") == 1
    assert "(Reused from shared/review.md" in copy
    card = [c for c in rt.board.list(room["id"]) if c["title"] == "second review"][0]
    assert card["status"] == "done" and card["review"]["report"] == "shared/review-2.md"
    assert card["review"]["verdict"] == "pass"  # the copied report matches the record, so it is not stale


def test_review_ceilings_never_exceed_the_groups_own(rt, script, monkeypatch):
    from pland.team import delegation

    monkeypatch.setattr(delegation, "global_settings", lambda root: {"review_max_steps": 8, "review_timeout_seconds": 60})
    room = team(rt)
    (rt.rooms.shared_dir(room["id"]) / "a.py").write_text("x = 1\n")
    seen: list[str] = []
    script({"lead": [review_call(), {"content": "done"}], "reviewer": [write_report("PASS", seen=seen), {"content": "ok"}]})
    rt.rooms.send(room["id"], "@lead review", background=False)
    assert "at most 8 steps and 60 seconds" in seen[0]


# ---------------------------------------------------------------------- card checks and the summary
def test_card_checks_pass_reuse_and_summary(rt, script):
    room = team(rt)
    shared = rt.rooms.shared_dir(room["id"])
    (shared / "a.py").write_text("def f():\n    return 1\n")
    (shared / "b.py").write_text("Y = 2\n")
    script({
        "lead": [{"tool_calls": [("team_tasks", {"action": "add", "title": "a", "files": ["shared/a.py"],
                                                 "checks": ["grep -q 'def f' shared/a.py"]})]},
                 lambda m, t: {"tool_calls": [("team_tasks", {"action": "add", "title": "b", "files": ["shared/b.py"],
                                                              "checks": ["grep -q 'Z =' shared/b.py"]})]},
                 lambda m, t: {"tool_calls": [("run_checks", {"task_id": rt.board.list(room["id"])[0]["id"]})]},
                 lambda m, t: {"tool_calls": [("run_checks", {"task_id": rt.board.list(room["id"])[0]["id"]})]},
                 lambda m, t: {"tool_calls": [("run_checks", {"task_id": rt.board.list(room["id"])[1]["id"]})]},
                 {"content": "Done."}],
        "reviewer": [{"content": "[PASS]"}],
    })
    out = rt.rooms.send(room["id"], "@lead build", background=False)["result"]
    outs = tool_outputs(rt, "lead")
    assert any("files: shared/a.py" in t and "checks: grep -q 'def f' shared/a.py" in t for t in outs)  # board text
    checks = [t for t in outs if t.startswith("Checks of")]
    assert ": PASS" in checks[0]
    assert "reused, not run again" in checks[1]
    assert ": FAIL" in checks[2]
    assert out["fast_mode"]["verified"] == ["shared/a.py"]
    assert out["fast_mode"]["pending"] == ["shared/b.py: check `grep -q 'Z =' shared/b.py` failed"]
    summary = [m for m in rt.rooms.messages(room["id"]) if m["kind"] == "activity" and "Fast Mode" in m["content"]][-1]
    assert summary["content"].startswith("⚠ Fast Mode — files verified: 1 of 2. Deliverables present: 2 of 2.")
    assert "Still needs checking:\n- shared/b.py" in summary["content"]


def test_a_check_is_stale_after_the_file_changes(rt, script):
    room = team(rt)
    shared = rt.rooms.shared_dir(room["id"])
    (shared / "a.py").write_text("def f(): pass\n")
    tid = {}

    def add(m, t):
        return {"tool_calls": [("team_tasks", {"action": "add", "title": "a", "files": ["shared/a.py"],
                                               "checks": ["grep -q 'def f' shared/a.py"]})]}

    def check(m, t):
        tid["id"] = rt.board.list(room["id"])[0]["id"]
        return {"tool_calls": [("run_checks", {"task_id": tid["id"]})]}

    def change(m, t):
        (shared / "a.py").write_text("def f(): return 1\n")
        return {"content": "Done."}

    script({"lead": [add, check, change], "reviewer": [{"content": "[PASS]"}]})
    out = rt.rooms.send(room["id"], "@lead build", background=False)["result"]
    assert out["fast_mode"]["verified"] == []
    assert "passed, but the files changed afterwards" in out["fast_mode"]["pending"][0]


def test_running_out_of_time_lists_what_still_needs_checking(rt, script, fake_exec):
    room = team(rt)
    shared = rt.rooms.shared_dir(room["id"])
    for name in ("a.py", "b.py", "c.py", "d.py", "e.py"):
        (shared / name).write_text("x = 1\n")
    adds = [{"tool_calls": [("team_tasks", {"action": "add", "title": n, "files": [f"shared/{n}.py"],
                                            "checks": [f"check {n}"]})]} for n in "abcde"]
    runs = [(lambda i: lambda m, t: {"tool_calls": [("run_checks", {"task_id": rt.board.list(room["id"])[i]["id"]})]})(i)
            for i in range(5)]
    script({"lead": adds + runs + [{"content": "Out of time."}], "reviewer": [{"content": "[PASS]"}]})
    out = rt.rooms.send(room["id"], "@lead build", background=False)["result"]
    fm = out["fast_mode"]
    assert len(fake_exec) == 4 and fm["command_seconds"] == 90.0  # 25 + 25 + 25 + 15
    assert fm["verified"] == ["shared/a.py", "shared/b.py", "shared/c.py", "shared/d.py"]
    assert fm["pending"] == ["shared/e.py: check `check e` was not run"]
    summary = [m for m in rt.rooms.messages(room["id"]) if m["kind"] == "activity" and "Fast Mode" in m["content"]][-1]
    assert summary["content"].startswith("⚠ Fast Mode — files verified: 4 of 5; the command time ran out. Deliverables present: 5 of 5.")
    last = [t for t in tool_outputs(rt, "lead") if t.startswith("Checks of")][-1]
    assert "not run (Fast Mode: the team's 90s of command time is used up" in last


def test_run_checks_is_refused_outside_fast_mode(rt, script):
    room = team(rt, fast=False)
    card = rt.board.add(room["id"], "a", created_by="lead")["id"]
    script({"lead": [{"tool_calls": [("run_checks", {"task_id": card})]}, {"content": "ok"}], "reviewer": [{"content": "[PASS]"}]})
    rt.rooms.send(room["id"], "@lead go", background=False)
    assert any("run_checks" in t and ("unknown tool" in t.lower() or "not available" in t.lower() or "fast mode" in t.lower())
               for t in tool_outputs(rt, "lead"))


def test_fast_mode_is_a_group_setting_in_the_api(rt):
    from fastapi.testclient import TestClient

    from pland.server.app import create_app

    room = team(rt, fast=False)
    client = TestClient(create_app(rt))
    new = client.post("/api/rooms", json={"name": "New group", "members": ["lead"]}).json()
    assert new["fast_mode"] is True and rt.rooms.get(new["id"])["settings"]["fast_mode"] is True
    manual = client.post("/api/rooms", json={"name": "Normal group", "members": ["lead"], "fast_mode": False}).json()
    assert manual["fast_mode"] is False
    # Groups created before the setting was stored had no fast_mode key.
    rt.shared.execute("UPDATE rooms SET settings=json_remove(settings, '$.fast_mode') WHERE id=?", (room["id"],))
    assert client.get(f"/api/rooms/{room['id']}").json()["fast_mode"] is False
    res = client.patch(f"/api/rooms/{room['id']}", json={"fast_mode": True})
    assert res.status_code == 200 and res.json()["fast_mode"] is True
    assert rt.rooms.get(room["id"])["settings"]["fast_mode"] is True


def test_a_newer_pass_of_the_same_check_on_another_card_counts(rt, script):
    """Real run: card 1's check passed, the files changed, card 2 (same files, same check) passed on the final contents;
    the summary must not call the files unverified because card 1's result is stale."""
    room = team(rt)
    shared = rt.rooms.shared_dir(room["id"])
    (shared / "a.py").write_text("def f(): pass\n")
    scope = {"files": ["shared/a.py"], "checks": ["grep -q 'def f' shared/a.py"]}

    def add(title):
        return lambda m, t: {"tool_calls": [("team_tasks", {"action": "add", "title": title, **scope})]}

    def check(i):
        return lambda m, t: {"tool_calls": [("run_checks", {"task_id": rt.board.list(room["id"])[i]["id"]})]}

    def change(m, t):
        (shared / "a.py").write_text("def f(): return 1\n")
        return add("fix")(m, t)

    script({"lead": [add("build"), check(0), change, check(1), {"content": "Done."}]})
    out = rt.rooms.send(room["id"], "@lead build", background=False)["result"]
    assert out["fast_mode"]["verified"] == ["shared/a.py"] and out["fast_mode"]["pending"] == []


@pytest.mark.parametrize("message", [
    "Please review shared/a.py again",
    "新版已在共享目录，请直接回我 PASS 或 FAIL。",
    "Read the two files. " + "Background details. " * 24 + "Reply with PASS/FAIL and a reason.",
])
def test_asking_for_a_review_by_message_is_refused(rt, script, message):
    room = team(rt)
    llm = script({"lead": [{"tool_calls": [("message_agent", {"target": "reviewer", "message": message})]},
                           {"content": "done"}],
                  "reviewer": [{"content": "PASS"}]})
    rt.rooms.send(room["id"], "@lead review", background=False)
    assert any("reviews run only through delegate_task" in t for t in tool_outputs(rt, "lead"))
    assert "reviewer" not in [n for n, _ in llm.calls]


def test_question_about_verdict_format_is_allowed(rt, script):
    rid = team(rt)["id"]
    llm = script({"lead": [{"tool_calls": [("message_agent", {"target": "reviewer",
                   "message": "How are PASS/FAIL values encoded in the file format?"})]}, {"content": "Understood."}],
                  "reviewer": [{"content": "Stored as strings."}]})
    rt.rooms.send(rid, "@lead ask about encoding", background=False)
    assert "reviewer" in [name for name, _ in llm.calls]


def test_a_reviewers_mention_turn_gets_the_review_limits(rt, script):
    room = team(rt)
    shared = rt.rooms.shared_dir(room["id"])
    (shared / "a.py").write_text("x = 1\n")
    looping = [{"tool_calls": [("read_file", {"path": "shared/a.py", "offset": i + 1})]} for i in range(40)]
    llm = script({"lead": [{"content": "!handoff @reviewer take a look at shared/a.py\nBuilt it."}], "reviewer": looping})
    rt.rooms.send(room["id"], "@lead build", background=False)
    assert 0 < [n for n, _ in llm.calls].count("reviewer") <= AgentSettings.fast_review_steps + 1


@pytest.mark.parametrize("fast", [False, True])
def test_review_guidance_follows_the_assignment(rt, script, fast):
    from pland.prompts import OUTPUT_RULES

    room = team(rt, fast=fast)
    (rt.rooms.shared_dir(room["id"]) / "a.py").write_text("x = 1\n")
    work = {"to": "reviewer", "purpose": "work", "goal": "Summarize the inputs",
            "context": "The status API accepts at most 64 bytes per label. Keep the handoff brief.",
            "expected_output": "A status label and the evidence for it"}
    llm = script({"lead": [{"tool_calls": [("delegate_task", {"tasks": [work]})]},
                           review_call(), {"content": "Delivered."}],
                  "reviewer": [{"content": "One input."}, write_report("PASS"), {"content": "PASS"}]})
    rt.rooms.send(room["id"], "@lead finish", background=False)
    lead_prompt = next(msgs[-1]["content"] for who, msgs in llm.calls if who == "lead")
    assignments = [msgs[-1]["content"] for who, msgs in llm.calls
                   if who == "reviewer" and msgs[-1]["role"] == "user"
                   and "Task delegated to you" in msgs[-1]["content"]]
    work_prompt, review_prompt = assignments
    assert all(msgs[0]["content"].count(OUTPUT_RULES) == 1 for _, msgs in llm.calls)
    assert "Keep team estimates out of blocking checks" in lead_prompt
    assert work["context"] in work_prompt and work["expected_output"] in work_prompt
    for prompt in (lead_prompt, work_prompt, review_prompt):
        assert ("at most one optional shortening pass" in prompt) == fast
    assert "Original request posted in this group" in review_prompt and "@lead finish" in review_prompt
    assert "Original request posted in this group" not in work_prompt
    assert "one brief report" in review_prompt and "checkpoint" in review_prompt
    assert ("Make small, well-understood fixes yourself" in lead_prompt) == fast
    assert ("report material findings promptly" in work_prompt) == fast
    assert "record PASS and return immediately" not in work_prompt
    assert ("record PASS and return immediately" in review_prompt) == fast
    assert rt.board.reviewed(room["id"])[0]["review"]["verdict"] == "pass"

@pytest.mark.parametrize("fast", [True, False])
def test_review_requirements_remain_independent_on_the_same_file(rt, script, fast):
    room = team(rt, fast=fast)
    rid = room["id"]
    (rt.rooms.shared_dir(rid) / "a.py").write_text("first version")
    script({"lead": [review_call(goal="check totals", report="shared/totals.md"),
                     review_call(goal="check attribution", report="shared/credits.md"),
                     {"content": "Everything passed."}],
            "reviewer": [write_report("FAIL", "shared/totals.md"), {"content": "bad total"},
                         write_report("PASS", "shared/credits.md"), {"content": "correct attribution"}]})
    result = rt.rooms.send(rid, "@lead check both criteria", background=False)["result"]
    reviews = rt.board.reviewed(rid)
    assert [(x["review"]["criterion"], x["review"]["verdict"]) for x in reviews] == [
        ("check totals", "fail"), ("check attribution", "pass")]
    assert "Everything passed." not in rt.rooms.messages(rid)[-1]["content"]
    if fast:
        assert result["fast_mode"]["pending"] and not result["fast_mode"]["verified"]


def test_check_repeats_after_edits_but_caps_unchanged_requests(rt, script, fake_exec):
    rid = team(rt)["id"]
    item = rt.rooms.shared_dir(rid) / "item.csv"
    item.write_text("old")
    def run(messages, tools):
        tid = rt.board.list(rid)[0]["id"]
        return {"tool_calls": [("run_checks", {"task_id": tid})]}
    def change(messages, tools):
        item.write_text("new")
        return run(messages, tools)
    script({"lead": [{"tool_calls": [("team_tasks", {"action": "add", "title": "check data",
                                                      "files": ["shared/item.csv"], "checks": ["check"]})]},
                     run, run, change, run, run, {"content": "done"}]})
    rt.rooms.send(rid, "@lead validate", background=False)
    assert len(fake_exec) == 2
    assert sum("already made this exact run_checks" in t for t in tool_outputs(rt, "lead")) == 1


@pytest.mark.parametrize("changed", [False, True])
def test_unfinished_review_resumes_once_on_same_card(rt, script, changed):
    rid = team(rt)["id"]
    artifact = rt.rooms.shared_dir(rid) / "a.py"
    artifact.write_text("v1")
    card = rt.board.add(rid, "check output", assignee="reviewer", created_by="lead")["id"]
    def retry(messages, tools):
        if changed:
            artifact.write_text("v2")
        return review_call(card)
    script({"lead": [review_call(card), retry, {"content": "done"}],
            "reviewer": [write_report("INCOMPLETE"), {"content": "one check remains"},
                         write_report("PASS"), {"content": "finished"}]})
    rt.rooms.send(rid, "@lead verify", background=False)
    rec = rt.board.review_record(card)
    assert rec["verdict"] == "pass" and rec["resumes"] == 1 and rec["round"] == 1

def test_check_script_change_invalidates_cache_and_is_not_a_deliverable(rt, script, fake_exec):
    from fastapi.testclient import TestClient
    from pland.server.app import create_app

    rid = team(rt)["id"]
    shared = rt.rooms.shared_dir(rid)
    (shared / "data.txt").write_text("record")
    checker = shared / "checker.sh"
    checker.write_text("exit 0")
    def run(m, t):
        return {"tool_calls": [("run_checks", {"task_id": rt.board.list(rid)[0]["id"]})]}
    def change(m, t):
        checker.write_text("exit 1")
        return run(m, t)
    script({"lead": [{"tool_calls": [("team_tasks", {"action":"add", "title":"Validate records",
                "files":["shared/data.txt"], "check_inputs":["shared/checker.sh"], "checks":["sh shared/checker.sh"]})]},
                     run, run, change, {"content":"done"}]})
    result = rt.rooms.send(rid, "@lead validate", background=False)["result"]["fast_mode"]
    assert len(fake_exec) == 2
    assert result["verified"] == ["shared/data.txt"]
    assert result["requirements"][0]["criterion"] == "Validate records"
    checker.write_text("exit 2")
    card, = TestClient(create_app(rt)).get(f"/api/rooms/{rid}/tasks").json()
    assert card["acceptance_checks"] == [{"command":"sh shared/checker.sh", "state":"stale"}]


def test_distinct_phase_limits_and_preserved_review_scope(rt, script):
    save_global_settings(rt.root, {"fast_review_seconds": 210, "fast_followup_seconds": 120, "fast_review_steps": 24})
    rid = team(rt)["id"]
    shared = rt.rooms.shared_dir(rid)
    (shared/"a.py").write_text("bad")
    (shared/"guide.md").write_text("same")
    card = rt.board.add(rid, "agreement", created_by="lead", assignee="reviewer")["id"]
    seen = []
    def revise(m,t):
        (shared/"a.py").write_text("fixed")
        return review_call(card, inputs=["shared/a.py"], criterion="agreement")
    script({"lead": [review_call(card, inputs=["shared/a.py","shared/guide.md"], criterion="agreement"), revise,
                     {"content":"done"}],
            "reviewer":[write_report("FAIL", seen=seen), {"content":"fix implementation"},
                        write_report("PASS", seen=seen), {"content":"done"}]})
    rt.rooms.send(rid,"@lead verify",background=False)
    assert "24 steps and 210 seconds" in seen[0] and "24 steps and 120 seconds" in seen[1]
    assert "CHANGE-ONLY REVIEW. Recheck only: shared/a.py." in seen[1]
    assert set(rt.board.review_record(card)["inputs"]) == {"shared/a.py","shared/guide.md"}


@pytest.mark.parametrize("fast", [True, False])
def test_revision_with_new_instructions_keeps_diff_and_rechecks_context(rt, script, fast):
    rid = team(rt, fast=fast)["id"]
    root = rt.rooms.shared_dir(rid)
    (root / "a.py").write_text("old")
    (root / "policy.txt").write_text("unchanged")
    card = rt.board.add(rid, "compatibility", assignee="reviewer", created_by="lead")["id"]
    seen = []

    def revise(messages, tools):
        (root / "a.py").write_text("new")
        request = review_call(card, criterion="compatibility")
        request["tool_calls"][0][1]["tasks"][0]["context"] = "Check the unchanged policy against the new target."
        return request

    script({"lead": [review_call(card, inputs=["shared/a.py", "shared/policy.txt"], criterion="compatibility"),
                     revise, {"content": "Done."}],
            "reviewer": [write_report("FAIL", seen=seen), {"content": "failed"},
                         write_report("PASS", seen=seen), {"content": "checked again"}]})
    rt.rooms.send(rid, "@lead check", background=False)
    assert len(seen) == 2
    assert "Diff for shared/a.py" in seen[1] and "Prior failing review excerpt" in seen[1]
    assert "recipient's starting point" in seen[0] and "recipient's starting point" not in seen[1]
    assert "trace its effect from the prerequisite through the next use" in seen[1]
    assert "Check the unchanged policy against the new target." in seen[1]
    assert "Recheck only:" not in seen[1]
    assert set(rt.board.review_record(card)["inputs"]) == {"shared/a.py", "shared/policy.txt"}


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("extra", [False, True])
def test_review_attachments_only_count_when_they_add_context(rt, script, fast, extra):
    rid = team(rt, fast=fast)["id"]
    shared = rt.rooms.shared_dir(rid)
    (shared / "a.py").write_text("old")
    (shared / "guide.md").write_text("unchanged")
    (rt.profiles.get("lead").workspace / "notes.md").write_text("extra instructions")
    card = rt.board.add(rid, "review", created_by="lead")["id"]
    inputs = ["shared/a.py", "shared/guide.md"]
    seen = []

    def request():
        call = review_call(card, inputs=inputs, criterion="compatibility")
        call["tool_calls"][0][1]["tasks"][0]["files"] = inputs + (["notes.md"] if extra else [])
        return call

    def revise(messages, tools):
        (shared / "a.py").write_text("new")
        return request()

    script({"lead": [request(), revise, {"content": "done"}],
            "reviewer": [write_report("FAIL", seen=seen), {"content": "failed"},
                         write_report("PASS", seen=seen), {"content": "checked again"}]})
    rt.rooms.send(rid, "@lead review", background=False)
    assert len(seen) == 2
    assert ("Diff for shared/a.py" in seen[1]) == (not extra)
    assert ("Prior failing review excerpt" in seen[1]) == (not extra)
    assert rt.board.review_record(card)["attached_context"] == extra
    if not extra:
        llm = script({"lead": [request(), {"content": "done"}]})
        rt.rooms.send(rid, "@lead verify again", background=False)
        assert all(name != "reviewer" for name, _ in llm.calls)
        assert any('"status": "reused"' in msg for msg in tool_outputs(rt, "lead"))


@pytest.mark.parametrize("fast,request_again", [(False, False), (True, True)])
def test_moving_report_during_handoff_preserves_signed_bytes(rt, script, fast, request_again):
    rid = team(rt, fast=fast)["id"]
    shared = rt.rooms.shared_dir(rid)
    (shared / "a.py").write_text("deliverable")
    card = rt.board.add(rid, "review", created_by="lead")["id"]
    seen = []
    report = "shared/evidence/review.md"

    def move_report(messages, tools):
        (shared / "evidence").rename(shared / "archive")
        return review_call(card, report=report) if request_again else {"content": "done"}

    script({"lead": [review_call(card, report=report), move_report, {"content": "done"}],
            "reviewer": [write_report("PASS", report=report, seen=seen), {"content": "accepted"}]})
    rt.rooms.send(rid, "@lead review", background=False)
    assert (shared / "evidence/review.md").read_bytes() == (shared / "archive/review.md").read_bytes()
    assert rt.board.get(card)["review"]["verdict"] == "pass" and len(seen) == 1
    if request_again:
        assert any('"status": "reused"' in msg for msg in tool_outputs(rt, "lead"))


def test_automatic_recheck_preserves_private_attachment(rt, script):
    rid = team(rt)["id"]
    shared = rt.rooms.shared_dir(rid)
    (shared / "a.py").write_text("draft")
    (rt.profiles.get("lead").workspace / "notes.md").write_text("other criteria")
    card = rt.board.add(rid, "review", created_by="lead")["id"]
    request = review_call(card)
    request["tool_calls"][0][1]["tasks"][0]["files"] = ["notes.md"]
    seen = []

    def edit(messages, tools):
        (shared / "a.py").write_text("revised")
        return {"content": "done"}

    script({"lead": [request, edit],
            "reviewer": [write_report("PASS", seen=seen), {"content": "accepted"},
                         write_report("PASS", seen=seen), {"content": "rechecked"}]})
    rt.rooms.send(rid, "@lead review", background=False)
    assert len(seen) == 2 and all("notes.md" in message for message in seen)
    assert rt.board.get(card)["review"]["verdict"] == "pass"


@pytest.mark.parametrize("case", ["edited report", "changed input", "later turn"])
def test_handoff_preserves_edits_and_stale_evidence(rt, script, case):
    rid = team(rt)["id"]
    shared = rt.rooms.shared_dir(rid)
    (shared / "a.py").write_text("draft")
    card = rt.board.add(rid, "review", created_by="lead")["id"]

    def cleanup(messages, tools):
        if case == "edited report":
            (shared / "review.md").write_text("replacement")
        else:
            (shared / "review.md").unlink()
            if case == "changed input":
                (shared / "a.py").write_text("revised")
        return {"content": "done"}

    script({"lead": [review_call(card), cleanup if case != "later turn" else {"content": "done"}],
            "reviewer": [write_report("PASS"), {"content": "accepted"}]})
    rt.rooms.send(rid, "@lead review", background=False)
    if case == "later turn":
        cleanup(None, None)
    assert rt.board.get(card)["review"]["verdict"] != "pass"
    if case == "edited report":
        assert (shared / "review.md").read_text() == "replacement"
    else:
        assert not (shared / "review.md").exists()


@pytest.mark.parametrize("also_delivered", [False, True])
def test_review_counts_deliverables_but_tracks_its_reference(rt, script, also_delivered):
    rid = team(rt)["id"]
    root = rt.rooms.shared_dir(rid)
    for name in ["draft.csv", "guide.txt", "source.csv"]:
        (root / name).write_text(name)
    outputs = ["shared/draft.csv", "shared/guide.txt"]
    inputs = outputs + ["shared/source.csv"]
    tasks = [{"action": "add", "title": "Deliver files", "files": outputs, "check_inputs": ["shared/source.csv"]}]
    if also_delivered:
        tasks.append({"action": "add", "title": "Deliver source data", "files": ["shared/source.csv"]})
    script({"lead": [{"tool_calls": [("team_tasks", task) for task in tasks]}, {"content": "Drafted."}]})
    rt.rooms.send(rid, "@lead draft", background=False)
    prerequisites = [task["id"] for task in rt.board.list(rid)]
    for tid in prerequisites:
        rt.board.update(tid, status="done")
    card = rt.board.add(rid, "verify", assignee="reviewer", created_by="lead", depends_on=prerequisites)["id"]
    script({"lead": [review_call(card, inputs=inputs), {"content": "Done."}],
            "reviewer": [write_report("FAIL"), {"content": "Two differences."}]})
    result = rt.rooms.send(rid, "@lead verify", background=False)["result"]["fast_mode"]
    expected = inputs if also_delivered else outputs
    assert len(result["pending"]) == len(expected) and not result["verified"]
    assert result["present"] == expected
    assert set(rt.board.review_record(card)["inputs"]) == set(inputs)
    (root / "source.csv").write_text("updated source")
    assert rt.board.get(card)["review"]["verdict"] == "stale"


@pytest.mark.parametrize("changed", ["report", "context", "fresh"])
def test_reuse_requires_current_matching_evidence(rt, script, changed):
    rid = team(rt)["id"]
    shared = rt.rooms.shared_dir(rid)
    (shared/"a.py").write_text("same")
    def next_request(m,t):
        second = review_call(criterion="coverage", report="shared/new.md")
        task = second["tool_calls"][0][1]["tasks"][0]
        if changed == "report":
            (shared/"review.md").write_text("replaced")
        elif changed == "context":
            task["context"] = "Assess the new environment."
        else:
            task["review"]["fresh"] = True
        return second
    script({"lead":[review_call(criterion="coverage"), next_request, {"content":"done"}],
            "reviewer":[write_report("PASS"), {"content":"first"}, write_report("FAIL","shared/new.md"), {"content":"second"}]})
    rt.rooms.send(rid,"@lead verify both",background=False)
    assert rt.board.reviewed(rid)[-1]["review"]["verdict"] == "fail"

@pytest.mark.parametrize("fast", [False, True])
def test_file_acceptance_to_qa_uses_the_board_in_both_modes(rt, script, fast):
    rid = team(rt, fast=fast)["id"]
    (rt.rooms.shared_dir(rid)/"a.py").write_text("version")
    def handoff(goal, **extra):
        return {"tool_calls":[("delegate_task", {"tasks":[{"to":"reviewer","goal":goal, **extra}]})]}
    script({"lead":[handoff("Independently verify shared/a.py against the requested behaviour."),
                    review_call(criterion="behaviour"),
                    handoff("Write a checklist for shared/a.py", expected_output="shared/list.md"), {"content":"done"}],
            "reviewer":[write_report("PASS"), {"content":"checked"},
                        {"tool_calls":[("write_file", {"path":"shared/list.md","content":"checklist"})]}, {"content":"written"}]})
    rt.rooms.send(rid,"@lead verify",background=False)
    assert any("supply the review field" in t for t in tool_outputs(rt,"lead"))
    card, = rt.board.reviewed(rid)
    assert card["review"]["verdict"] == "pass"
    assert (rt.rooms.shared_dir(rid)/"list.md").read_text() == "checklist"

def test_unversioned_commands_are_live_observations(rt, script, fake_exec):
    rid = team(rt)["id"]
    def run(m,t):
        return {"tool_calls":[("run_checks", {"task_id":rt.board.list(rid)[0]["id"]})]}
    script({"lead":[{"tool_calls":[("team_tasks",{"action":"add","title":"Observe service state","checks":["probe"]})]},
                    run, run, {"content":"observed"}]})
    out = rt.rooms.send(rid,"@lead observe",background=False)["result"]["fast_mode"]
    assert len(fake_exec) == 2 and out["requirements"][0]["verdict"] == "pass"
    assert "0 of 0" not in rt.rooms.messages(rid)[-1]["content"]
    script({"lead":[run, {"content":"again"}]})
    rt.rooms.send(rid,"@lead observe again",background=False)
    assert len(fake_exec) == 3


def test_legacy_card_gets_a_full_review_before_its_verdict_can_be_reused(rt, script):
    from pland.team.review import prepare_review, finish_review
    rid = team(rt)["id"]
    shared = rt.rooms.shared_dir(rid)
    (shared/"a.py").write_text("legacy")
    card = rt.board.add(rid,"old card",assignee="reviewer",created_by="lead")["id"]
    spec = {"inputs":["shared/a.py"],"report":"shared/review.md"}
    old = prepare_review(shared,spec)
    (shared/"review.md").write_text("Verdict: PASS\nOld evidence")
    legacy = finish_review(shared,old,"completed")
    legacy.pop("criterion")
    rt.board.record_review(card,{**legacy,"round":2})
    rt.board.update(card,status="done")
    script({"lead":[review_call(card,criterion="new scope"),{"content":"done"}],
            "reviewer":[write_report("FAIL"),{"content":"wrong"}]})
    rt.rooms.send(rid,"@lead check",background=False)
    assert rt.board.review_record(card)["verdict"] == "fail"


@pytest.mark.parametrize("fast", [False, True])
def test_added_shared_attachment_gets_a_focused_review_and_stales_afterwards(rt, script, fast):
    rid = team(rt, fast=fast)["id"]
    root = rt.rooms.shared_dir(rid)
    (root / "a.py").write_text("original payload")
    (root / "reference.txt").write_text("reference")
    tid = rt.board.add(rid, "works offline", created_by="lead")["id"]
    seen = []

    def request(extra=()):
        call = review_call(tid, goal="check affected behavior", criterion=None if extra else "works offline")
        task = call["tool_calls"][0][1]["tasks"][0]
        task["files"] = ["shared/reference.txt", *extra]
        if not extra:
            task["review"]["observation"] = "Exercise the package with the network disconnected."
        return call

    def report(messages, tools):
        seen.append(messages[-1]["content"])
        return {"tool_calls": [("write_file", {"path": "shared/review.md", "content":
                f"Verdict: PASS\nEvidence: observed | check {len(seen)}: offline output appeared.\n"})]}

    def handoff(messages, tools):
        (root / "usage.md").write_text("New instructions")
        return request(["shared/usage.md"])

    script({"lead": [request(), handoff, {"content": "delivered"}],
            "reviewer": [report, {"content": "passed"}, report, {"content": "passed"}]})
    rt.rooms.send(rid, "@lead build", background=False)
    assert len(seen) == 2 and "CHANGE-ONLY REVIEW. Recheck only: shared/usage.md." in seen[1]
    assert "Prior observation for the previous version" in seen[1]
    assert "Requirement covered by the previous observation: Exercise the package with the network disconnected." in seen[1]
    card = rt.board.get(tid)
    assert card["review"]["verdict"] == "pass"
    assert card["review"]["supporting_files"] == ["shared/reference.txt", "shared/usage.md"]
    (root / "usage.md").write_text("Different instructions")
    assert rt.board.get(tid)["review"]["changed_inputs"] == ["shared/usage.md"]


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("outcome", ["clean", "open", "unsupported", "resolved"])
def test_disputes_gate_delivery_and_learning_for_only_the_affected_request(rt, script, fast, outcome):
    from pland.memory import NotesMemory

    rid = team(rt, fast=fast)["id"]
    root = rt.rooms.shared_dir(rid)
    (root / "a.py").write_text("export new header")
    source = "shared/format.txt"
    (root / "format.txt").write_text("Revision B requires header B.")
    lead = rt.profiles.get("lead")
    resolution = f"{source} section 2 requires header B."
    steps = [{"tool_calls": [("memory", {"action": "add", "target": "memory", "content": "Provisional lesson."}),
                             ("memory", {"action": "add", "target": "user", "content": "Use short replies."}),
                             ("skill_save", {"name": "procedure", "description": "format", "content": "Assume header A."})]}]
    def card_id():
        return next(c["id"] for c in rt.board.list(rid) if c["conflict_source"])

    def request(messages, tools):
        assert not NotesMemory(lead).entries("memory")
        return review_call(card_id(), goal="verify which header is supported")

    def remember(messages, tools):
        return {"tool_calls": [("memory", {"action": "add", "target": "memory", "verified_task_id": card_id(),
                                           "content": "This caller-supplied claim is not verified."})]}
    if outcome != "clean":
        steps.append({"tool_calls": [("team_tasks", {"action": "flag_conflict", "title": "Which header applies?",
                     "description": "Plan says A, the requested revision specifies B.", "source": source})]})
    if outcome in {"resolved", "unsupported"}:
        steps += [request, remember]
    steps += [{"content": "finished"}]
    body = "Verdict: PASS\nEvidence: observed | Parsed the fixture; A was rejected and B accepted."
    if outcome == "resolved":
        body += "\nResolution: " + resolution
    script({"lead": steps, "reviewer": [{"tool_calls": [("write_file", {"path": "shared/review.md", "content": body})]},
                                        {"content": "complete"}]})
    result = rt.rooms.send(rid, "@lead verify the format. Use short replies.", background=False)
    messages = [m["content"] for m in rt.rooms.messages(rid) if m["speaker"] == "lead" and m["kind"] == "message"]
    unresolved = outcome in {"open", "unsupported"}
    assert ("Unresolved evidence conflicts" in messages[-1]) == unresolved
    notes = NotesMemory(lead)
    assert notes.entries("memory") == (["Provisional lesson."] if outcome == "clean" else
                                       [resolution] if outcome == "resolved" else [])
    assert notes.entries("user") == ["Use short replies."]
    assert (lead.skills_dir / "procedure.md").exists() == (outcome == "clean")
    if fast and outcome == "open":
        assert result["result"]["fast_mode"]["requirements"][0]["verdict"] == "incomplete"
    if outcome != "clean":
        if unresolved:
            notes.add("memory", "Known obsolete rule.")
            script({"lead": [{"tool_calls": [
                ("memory", {"action": "remove", "target": "memory", "old_text": "Known obsolete rule."}),
                ("memory", {"action": "add", "target": "memory", "content": "Unverified prior conclusion."}),
                ("memory", {"action": "replace", "target": "user", "old_text": "missing preference", "content": "X"})]},
                {"content": "Everything was verified."}]})
            followup = rt.rooms.send(rid, "@lead finish the earlier request and remember the outcome", background=False)
            assert "Unresolved evidence conflicts" in [m["content"] for m in rt.rooms.messages(rid) if m["kind"] == "message"][-1]
            assert notes.entries("memory") == []
            assert any("no user entry contains" in line for line in tool_outputs(rt, "lead"))
            if fast:
                assert any(r["task_id"] == card_id() for r in followup["result"]["fast_mode"]["requirements"])
        separate = [{"tool_calls": [("team_tasks", {"action": "separate_request", "task_id": card_id(),
                                                  "description": "The new request is about the calendar."})]}] if unresolved else []
        script({"lead": [*separate, {"content": "Independent answer."}]})
        rt.rooms.send(rid, "@lead unrelated question", background=False)
        assert "Independent answer." in rt.rooms.messages(rid)[-1]["content"]
        if unresolved:
            assert rt.board.get(card_id())["status"] == "blocked"


@pytest.mark.parametrize("fast", [False, True])
def test_renamed_artifact_can_be_reviewed_on_its_original_card(rt, script, fast):
    rid = team(rt, fast=fast)["id"]
    shared = rt.rooms.shared_dir(rid)
    (shared / "a.py").write_text("logic")
    (shared / "old.md").write_text("instructions")
    tid = rt.board.add(rid, "package contents", created_by="lead")["id"]
    seen = []

    def rename(messages, tools):
        (shared / "old.md").rename(shared / "new.md")
        return review_call(tid, inputs=["shared/new.md"])

    script({"lead": [review_call(tid, inputs=["shared/a.py", "shared/old.md"]), rename, {"content": "done"}],
            "reviewer": [write_report("PASS", seen=seen), {"content": "ok"},
                         write_report("PASS", seen=seen), {"content": "ok"}]})
    run = rt.rooms.send(rid, "@lead check package contents", background=False)["result"]
    assert len(seen) == 2 and "Removed since sign-off: shared/old.md" in seen[1]
    assert "Recheck only: shared/new.md, shared/old.md" in seen[1]
    assert rt.board.get(tid)["review"]["verdict"] == "pass"
    if fast:
        assert "shared/old.md" not in run["fast_mode"]["verified"]
    (shared / "old.md").write_text("accidentally restored")
    assert rt.board.get(tid)["review"]["verdict"] == "stale"


@pytest.mark.parametrize("fast", [False, True])
def test_reuse_keeps_card_ownership_file_roles_and_review_allowance(rt, script, fast):
    rid = team(rt, fast=fast)["id"]
    shared = rt.rooms.shared_dir(rid)
    (shared / "a.py").write_text("v1")
    (shared / "guide.md").write_text("guide")
    first, second, promoted = [rt.board.add(rid, title, created_by="lead")["id"]
                               for title in ("original", "independent", "guide as deliverable")]
    seen = []

    def request(tid, out, include_guide=False):
        call = review_call(tid, inputs=["shared/a.py", "shared/guide.md"] if include_guide else ["shared/a.py"],
                           criterion="package works", report="shared/" + out)
        call["tool_calls"][0][1]["tasks"][0]["files"] = ["shared/guide.md"]
        return call

    def revise(messages, tools):
        (shared / "a.py").write_text("v2")
        return request(first, "r1")

    script({"lead": [request(first, "r1"), revise, request(second, "r2"), request(promoted, "r3", True),
                     {"content": "finished"}],
            "reviewer": [write_report("PASS", "shared/r1", seen), {"content": "ok"},
                         write_report("PASS", "shared/r1", seen), {"content": "ok"},
                         write_report("PASS", "shared/r3", seen), {"content": "ok"}]})
    rt.rooms.send(rid, "@lead check", background=False)
    assert len(seen) == 3
    assert rt.board.review_record(second)["round"] == 1
    assert rt.board.review_record(promoted)["supporting_files"] == []


@pytest.mark.parametrize("fast", [False, True])
def test_live_dispute_rechecks_source_on_each_card(rt, script, fast):
    rid = team(rt, fast=fast)["id"]
    shared = rt.rooms.shared_dir(rid)
    (shared / "a.py").write_text("same artifact")
    source = "Service availability bulletin, current edition"
    seen = []
    def flag():
        return {"tool_calls": [("team_tasks", {"action": "flag_conflict", "title": "Service availability",
                             "source": source, "description": "The plan assumes the service is open; maintenance may apply."})]}
    def verify(messages, tools):
        tid = rt.board.list(rid)[-1]["id"]
        return review_call(tid, report="shared/" + tid + ".md", criterion="Service availability")
    def report(verdict):
        def write(messages, tools):
            seen.append(messages[-1]["content"])
            tid = rt.board.list(rid)[-1]["id"]
            body = f"Verdict: {verdict}\nEvidence: observed | polled the service\nResolution: bulletin section 3 confirms availability."
            return {"tool_calls": [("write_file", {"path": "shared/" + tid + ".md", "content": body})]}
        return write
    script({"lead": [flag(), verify, flag(), verify, {"content": "done"}],
            "reviewer": [report("PASS"), {"content": "open"}, report("FAIL"), {"content": "closed"}]})
    rt.rooms.send(rid, "@lead check twice", background=False)
    cards = rt.board.list(rid)
    assert len(seen) == 2
    assert cards[0]["review"]["resolution"].endswith(f"[Source: {source}]")
    assert cards[1]["review"]["verdict"] == "fail" and cards[1]["status"] == "blocked"


def test_unfinished_command_check_cannot_supply_a_durable_conclusion(rt, script):
    from pland.memory import NotesMemory

    rid = team(rt)["id"]
    script({"lead": [{"tool_calls": [("team_tasks", {"action": "add", "title": "Export works", "checks": ["check-export"]}),
                                    ("memory", {"action": "add", "target": "memory", "content": "Export is available."})]},
                     {"content": "Export works."}]})
    result = rt.rooms.send(rid, "@lead verify export", background=False)["result"]
    assert result["fast_mode"]["requirements"][0]["verdict"] == "incomplete"
    assert not NotesMemory(rt.profiles.get("lead")).entries("memory")


@pytest.mark.parametrize("fast", [False, True])
def test_explicit_preference_has_its_own_source_and_is_available_during_the_run(rt, script, fast):
    from pland.memory import NotesMemory

    rid = team(rt, fast=fast)["id"]
    def check(messages, tools):
        assert NotesMemory(rt.profiles.get("lead")).entries("user") == ["Keep the handover short"]
        return {"content": "Acknowledged."}
    script({"lead": [{"tool_calls": [("team_tasks", {"action": "flag_conflict", "title": "Which edition?",
                    "source": "Publisher's catalog", "description": "The catalog and the dispatch name different editions."})]},
                    {"tool_calls": [("memory", {"action": "add", "target": "user", "user_quote": "Invented preference"}),
                                    ("memory", {"action": "add", "target": "user", "user_quote": "Keep the handover short",
                                                "content": "Paraphrase plus an unverified edition."})]}, check]})
    rt.rooms.send(rid, "@lead check. Keep the handover short please.", background=False)
    assert any("copy an exact preference" in t for t in tool_outputs(rt, "lead"))


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("amended", [False, True])
def test_fresh_observation_repeats_the_live_condition_without_discarding_unaffected_evidence(rt, script, fast, amended):
    rid = team(rt, fast=fast)["id"]
    root = rt.rooms.shared_dir(rid)
    (root / "a.py").write_text("published artifact")
    (root / "policy.md").write_text("first edition")
    card = rt.board.add(rid, "publication online", created_by="lead")["id"]
    def request():
        call = review_call(card, inputs=["shared/a.py", "shared/policy.md"])
        call["tool_calls"][0][1]["tasks"][0]["review"].update(observation="Observe public availability", fresh=True)
        return call
    def refresh(messages, tools):
        if amended:
            (root / "policy.md").write_text("correct an attribution")
        return request()
    seen = []
    def observed(messages, tools):
        seen.append(messages[-1]["content"])
        return {"tool_calls": [("write_file", {"path": "shared/review.md", "content":
                    "Verdict: PASS\nEvidence: observed | online; packaged file passed checksum."})]}
    def no_observation(messages, tools):
        seen.append(messages[-1]["content"])
        return {"tool_calls": [("write_file", {"path": "shared/review.md", "content": "Verdict: PASS\nold receipt only"})]}
    script({"lead": [request(), refresh, {"content": "done"}],
            "reviewer": [observed, {"content": "done"}, no_observation, {"content": "done"}]})
    rt.rooms.send(rid, "@lead verify availability twice", background=False)
    assert len(seen) == 2 and "Keep earlier evidence for unaffected checks" in seen[1]
    assert ("Recheck only: shared/policy.md" if amended else "all recorded file versions match") in seen[1]
    assert rt.board.get(card)["review"]["verdict"] == "incomplete"


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("with_id", [False, True])
def test_work_handoff_uses_planned_owner_and_one_card(rt, script, fast, with_id):
    rid = team(rt, fast=fast)["id"]
    filename = "shared/summary.csv"

    def dispatch(msgs, tools):
        card = next(c for c in rt.board.list(rid) if c["assignee"] == "reviewer")
        task = {"goal": "Produce the aggregate", "expected_output": filename}
        if with_id:
            task["task_id"] = card["id"]
        return {"tool_calls": [("delegate_task", {"tasks": [task]})]}

    script({"lead": [{"tool_calls": [("team_tasks", {"action": "add", "title": "Make aggregate",
                    "files": [filename], "assignee": "reviewer"}), ("team_tasks", {"action": "add", "title": "Assemble package",
                    "files": [filename, "shared/package.zip"], "assignee": "lead"})]}, dispatch, {"content": "Ready."}],
            "reviewer": [{"tool_calls": [("write_file", {"path": filename, "content": "count\n3"})]}, {"content": "Ready."}]})
    rt.rooms.send(rid, "@lead prepare the aggregate", background=False)
    cards = rt.board.list(rid)
    assert len(cards) == 2
    card = next(c for c in cards if c["assignee"] == "reviewer")
    assert (card["status"], card["assignee"]) == ("done", "reviewer")
    assert rt.shared.one("SELECT target FROM deliveries WHERE kind='delegation'")["target"] == "reviewer"
    assert (rt.rooms.shared_dir(rid) / "summary.csv").read_text() == "count\n3"


def test_ambiguous_output_requires_card_id_and_unowned_work_can_use_a_helper(rt, script):
    rid = team(rt)["id"]
    path = "shared/account.csv"
    plan = [("team_tasks", {"action": "add", "title": title, "assignee": owner, "files": [path]})
            for title, owner in [("draft", "lead"), ("revise", "reviewer")]]
    def dispatch(p):
        return {"tool_calls": [("delegate_task", {"tasks": [{"goal": "Produce data", "expected_output": p}]})]}
    script({"lead": [{"tool_calls": plan}, dispatch(path), dispatch("shared/other.csv"),
                     {"content": "helper report"}, {"content": "finished"}]})
    rt.rooms.send(rid, "@lead prepare records", background=False)
    assert any("Pass the intended task_id" in msg for msg in tool_outputs(rt, "lead"))
    assert [r["target"] for r in rt.shared.query("SELECT target FROM deliveries")] == ["lead/subagent"]


@pytest.mark.parametrize(("user_prompt", "expectation", "source", "accepted"), [
    ("Prepare the digest", "≤1,000 words", "", False),
    ("Prepare the digest", "不超过 500 字", "", False),
    ("Read the 500 words of source material", "at most 500 words", "", False),
    ("Prepare a digest of at most 1,000 words", "≤1000 words", "", True),
    ("Use the submission form", "up to 240 characters", "Submission form field 'abstract': 240 characters", True),
    ("Prepare the digest", "3 sections and up to 500 records", "", True),
])
def test_fast_handoff_distinguishes_sourced_limits(rt, script, user_prompt, expectation, source, accepted):
    rid = team(rt)["id"]
    assignment = {"to": "reviewer", "goal": "Create a digest", "expected_output": expectation}
    if source:
        assignment["requirement_source"] = source
    models = script({"lead": [{"tool_calls": [("delegate_task", {"tasks": [assignment]})]}, {"content": "Finished."}],
                     "reviewer": [{"content": "Digest ready."}]})
    rt.rooms.send(rid, "@lead " + user_prompt, background=False)
    deliveries = rt.shared.query("SELECT target FROM deliveries WHERE kind='delegation'")
    assert bool(deliveries) == accepted
    if not accepted:
        assert any("requirement_source" in msg for msg in tool_outputs(rt, "lead"))
    elif source:
        assert any(source in msgs[-1]["content"] for who, msgs in models.calls if who == "reviewer" and msgs[-1]["role"] == "user")
