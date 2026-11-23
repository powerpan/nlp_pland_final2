from __future__ import annotations

import textwrap

import yaml

from pland.eval.runner import RunOptions, run_suite
from pland.eval.tasks import load_suite
from pland.llm.factory import set_client_override

from .conftest import RoutingLLM


def write_suite(tmp_path):
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "suite.yaml").write_text(yaml.safe_dump({"description": "self-test", "defaults": {"timeout": 30}}))
    (suite / "01-file.yaml").write_text(textwrap.dedent("""
        id: file-task
        category: files
        prompt: Write the sum of data/n.txt numbers into out.txt
        setup:
          files:
            data/n.txt: "1 2 3"
        hitl:
          replies:
            - match: "(?i)format"
              reply: "just the number"
        checks:
          - {id: exists, type: file_exists, path: out.txt}
          - {id: value, type: python, code: "assert path('out.txt').read_text().strip() == '6', 'wrong sum'"}
          - {id: asked, type: hitl, kind: clarify, min: 1}
    """))
    (suite / "02-fail.yaml").write_text(textwrap.dedent("""
        id: fail-task
        category: coding
        prompt: create missing.py
        checks:
          - {id: exists, type: file_exists, path: missing.py}
          - {id: cmd, type: command, run: "test -f missing.py"}
    """))
    (suite / "03-team.yaml").write_text(textwrap.dedent("""
        id: team-task
        category: team
        mode: team
        team:
          lead: boss
          bots:
            - {name: boss, title: Boss, description: plans}
            - {name: dev, title: Dev, description: codes}
        prompt: Put hello in shared/hello.txt using the dev
        checks:
          - {id: shared, type: file_contains, path: shared/hello.txt, pattern: hello}
          - {id: deleg, type: delegated, min: 1, to: [dev]}
          - {id: board, type: board_tasks, min: 1, status: done}
    """))
    return suite


def test_suite_loading(tmp_path):
    meta, tasks = load_suite(write_suite(tmp_path))
    assert meta["description"] == "self-test"
    assert [t.id for t in tasks] == ["file-task", "fail-task", "team-task"]
    assert tasks[0].timeout == 30 and tasks[0].required_ids == ["exists", "value", "asked"]


def test_runner_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAND_HOME", str(tmp_path / "home"))
    suite = write_suite(tmp_path)
    llm = RoutingLLM({
        "default": [
            {"tool_calls": [("ask_user", {"question": "What output format do you want?"})]},
            {"tool_calls": [("read_file", {"path": "data/n.txt"})]},
            {"tool_calls": [("write_file", {"path": "out.txt", "content": "6\n"})]},
            {"content": "out.txt contains 6"},
            {"content": "I could not do it"},  # fail-task
        ],
        "dev": [{"content": "[PASS]"},  # round-1 discussion turn
                {"tool_calls": [("write_file", {"path": "shared/hello.txt", "content": "hello"})]}, {"content": "written"}],
        "boss": [{"tool_calls": [("delegate_task", {"tasks": [{"to": "dev", "goal": "write hello into shared/hello.txt"}]})]},
                 {"content": "dev wrote it"}],
    })
    set_client_override(llm)
    try:
        runner, summary = run_suite(suite, RunOptions(out_dir=tmp_path / "runs"))
    finally:
        set_client_override(None)
    by_id = {r["task_id"]: r for r in runner.records}
    assert by_id["file-task"]["outcome"] == "success", by_id["file-task"]["checks"]
    assert by_id["fail-task"]["outcome"] == "failed"
    assert by_id["fail-task"]["failure_mode"] == "deliverable missing"
    assert by_id["team-task"]["outcome"] == "success", by_id["team-task"]["checks"]
    assert summary["goal_completion_rate"] == round(100 * 2 / 3, 1)
    assert summary["subtask_completion_rate"] == round(100 * 6 / 8, 1)
    assert (runner.run_dir / "report.md").read_text().startswith("# 評測報告")
    assert (runner.run_dir / "tasks" / "team-task" / "workspace" / "shared" / "hello.txt").exists()
    # verified outcome was written back into the experience store
    from pland.memory import ExperienceStore

    exps = ExperienceStore(runner.rt.profiles.get("default")).all()
    assert any("[verified: eval fail-task: failed]" in e.summary and e.outcome == "failure" for e in exps)


def test_closed_set_aliases(tmp_path):
    f = tmp_path / "closed.jsonl"
    f.write_text('{"task_id": "q1", "instruction": "What is the capital of France?", "expected_answer": "Paris"}\n'
                 '{"name": "q2", "question": "2+2?"}\n')
    _, tasks = load_suite(f)
    assert tasks[0].id == "q1" and tasks[0].prompt.startswith("What")
    assert tasks[0].checks[0]["type"] == "answer_contains" and "Paris" in tasks[0].checks[0]["pattern"]
    assert tasks[1].id == "q2" and tasks[1].checks == []


def test_python_check_return_and_multiline_strings(tmp_path):
    from pland.eval.checks import CheckEnv, run_check

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("line1\nline2\n")

    class _Rooms:
        def shared_dir(self, rid):
            return tmp_path

    class _Profiles:
        def list(self):
            return []

    class _RT:
        rooms, profiles = _Rooms(), _Profiles()

    env = CheckEnv(_RT(), "default", ws, "ans", None, "dm:default", [], [])
    code_ok = 'expected = """line1\nline2\n"""\nreturn path("a.txt").read_text() == expected'
    assert run_check(env, {"id": "x", "type": "python", "code": code_ok})["passed"]
    assert not run_check(env, {"id": "y", "type": "python", "code": "return False"})["passed"]
    assert run_check(env, {"id": "z", "type": "python", "code": "assert answer == 'ans'"})["passed"]
