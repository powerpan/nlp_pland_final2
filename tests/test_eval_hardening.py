"""Evaluation harness hardening: checks run in the task's sandbox (S6), timed-out tasks cannot leak into the next
task (R1). Scripted models only; no network, no keys."""

from __future__ import annotations

import os
import subprocess
import textwrap
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from pland.config import SandboxConfig
from pland.eval.checks import CheckEnv, run_check
from pland.eval.runner import RunOptions, SuiteRunner
from pland.eval.tasks import load_suite, resolve_suite
from pland.llm.factory import set_client_override
from pland.sandbox import DockerBackend, LocalBackend
from pland.store import DB

from .conftest import RoutingLLM

SEATBELT = os.path.exists("/usr/bin/sandbox-exec")
needs_seatbelt = pytest.mark.skipif(not SEATBELT, reason="macOS Seatbelt only")
REPO = Path(__file__).resolve().parents[1]


class _Rooms:
    def __init__(self, root: Path):
        self.root = root

    def shared_dir(self, rid):
        p = self.root / "rooms" / rid / "shared"
        p.mkdir(parents=True, exist_ok=True)
        return p


class _Profiles:
    def __init__(self, profiles: dict[str, Path] | None = None):
        self.profiles = profiles or {}

    def list(self):
        return [SimpleNamespace(name=n, workspace=w) for n, w in self.profiles.items()]

    def get(self, name):
        return SimpleNamespace(name=name, workspace=self.profiles[name])


def _env(ws: Path, root: Path, *, backend=None, room_id=None, profiles=None, answer="") -> CheckEnv:
    rt = SimpleNamespace(rooms=_Rooms(root), profiles=_Profiles(profiles))
    return CheckEnv(rt, "default", ws, answer, room_id, room_id or "dm:default", [], [], backend=backend)


def _confined(tmp_path: Path):
    """A workspace, a folder the sandbox denies (standing in for the user's home / PLAND_HOME), and the backend."""
    ws = tmp_path / "ws"
    outside = tmp_path / "outside"
    ws.mkdir()
    outside.mkdir()
    return ws, outside, LocalBackend(SandboxConfig(), workspace=ws, deny_roots=[outside], home_dir=tmp_path / "bothome")


# ---------------------------------------------------------------------------------------------- S6: sandboxed checks
@needs_seatbelt
def test_python_check_runs_agent_code_inside_the_sandbox(tmp_path):
    ws, outside, backend = _confined(tmp_path)
    marker = outside / "pwned.txt"
    # an agent-planted module whose import writes outside the workspace
    (ws / "solution.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('x')\nVALUE = 1\n")
    env = _env(ws, tmp_path, backend=backend)
    res = run_check(env, {"id": "imp", "type": "python", "code": "import solution\nassert solution.VALUE == 1"})
    assert not res["passed"] and ("PermissionError" in res["message"] or "Operation not permitted" in res["message"])
    assert not marker.exists()
    # the check code itself cannot write there either, but the workspace stays writable
    res = run_check(env, {"id": "w", "type": "python", "code": f"Path({str(marker)!r}).write_text('x')"})
    assert not res["passed"] and not marker.exists()
    res = run_check(env, {"id": "ok", "type": "python", "code": "path('note.txt').write_text('fine')\nreturn True"})
    assert res["passed"], res["message"]
    # the backend is really the one that ran it (Seatbelt-confined)
    assert backend.seatbelt and backend.name == "local+seatbelt"


@needs_seatbelt
def test_command_and_git_checks_run_inside_the_sandbox(tmp_path):
    ws, outside, backend = _confined(tmp_path)
    marker = outside / "cmd.txt"
    env = _env(ws, tmp_path, backend=backend)
    res = run_check(env, {"id": "c", "type": "command", "run": f"touch {marker}"})
    assert not res["passed"] and not marker.exists()
    assert res["message"].startswith(f"`touch {marker}` exit 1 (expected 0)")
    # A repository config can make `git status` run a command (core.fsmonitor): on the host that is code execution.
    repo = ws / "repo"
    hook = f"touch {tmp_path / 'outside' / 'git.txt'} #"  # '#' drops the arguments git appends
    genv = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@x"}
    subprocess.run(f"git init -q {repo} && cd {repo} && echo a > a && git add a && git commit -qm 'feat: a'",
                   shell=True, check=True, env=genv, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "core.fsmonitor", hook], check=True)
    subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True)  # the vector is real ...
    if not (outside / "git.txt").exists():
        pytest.skip("this git does not run core.fsmonitor commands")
    (outside / "git.txt").unlink()
    res = run_check(env, {"id": "g", "type": "git_clean", "repo": "repo"})  # ... but not from a check
    assert not (outside / "git.txt").exists()
    assert res["passed"], res["message"]
    res = run_check(env, {"id": "l", "type": "git_commits", "repo": "repo", "min": 1, "message_pattern": "^feat"})
    assert res["passed"] and res["message"].startswith("1 matching commit(s)"), res["message"]
    res = run_check(env, {"id": "m", "type": "git_commits", "repo": "nope"})
    assert not res["passed"] and "FileNotFoundError" in res["message"] and not (ws / "nope").exists()


@needs_seatbelt
def test_default_check_sandbox_denies_the_users_home(tmp_path):
    """Without a backend from the runner (e.g. the suite validator), checks still get a confined local backend."""
    ws = tmp_path / "ws"
    ws.mkdir()
    env = _env(ws, tmp_path)
    assert env.sandbox().name == "local+seatbelt"
    if not str(REPO).startswith("/Users/"):
        pytest.skip("repository is not under /Users")
    res = run_check(env, {"id": "r", "type": "python", "code": f"open({str(REPO / 'CLAUDE.md')!r}).read()"})
    assert not res["passed"] and ("PermissionError" in res["message"] or "Operation not permitted" in res["message"])


def test_check_code_is_never_written_to_disk(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("1")
    env = _env(ws, tmp_path, backend=LocalBackend(SandboxConfig(), workspace=ws, home_dir=tmp_path / "h"))
    before = sorted(p.relative_to(ws) for p in ws.rglob("*"))
    secret = "EXPECTED-VALUE-91731"
    res = run_check(env, {"id": "s", "type": "python", "code": f"assert path('a.txt').read_text() == '1', {secret!r}"})
    assert res["passed"], res["message"]
    assert sorted(p.relative_to(ws) for p in ws.rglob("*")) == before
    assert not any(secret in f.read_text(errors="replace") for f in tmp_path.rglob("*") if f.is_file())


def test_host_check_does_not_import_from_the_workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "planted.py").write_text("raise SystemExit('planted module imported')\n")
    (ws / "os.py").write_text("raise SystemExit('planted os imported')\n")
    env = _env(ws, tmp_path)
    code = "import os\nassert path('planted.py').is_file()\ntry:\n    import planted\nexcept ImportError:\n    pass"
    res = run_check(env, {"id": "h", "type": "python", "host": True, "code": code})
    assert res["passed"], res["message"]
    # a sandboxed check imports the agent's modules, as it always did
    res = run_check(env, {"id": "s", "type": "python", "code": "import planted"})
    assert not res["passed"] and "planted module imported" in res["message"]


def _clamp_task():
    _, tasks = load_suite(REPO / "pland/eval/suites/dev")
    return next(t for t in tasks if t.id == "dev-code-clamp")


GOOD_CLAMP = "def clamp(x, lo, hi):\n    if lo > hi:\n        raise ValueError('lo > hi')\n    return max(lo, min(x, hi))\n"
CLAMP_TESTS = textwrap.dedent("""
    import pytest
    from mathx import clamp
    def test_in(): assert clamp(5, 0, 10) == 5
    def test_low(): assert clamp(-1, 0, 10) == 0
    def test_err():
        with pytest.raises(ValueError):
            clamp(1, 5, 0)
""")


def test_dev_suite_check_results_unchanged(tmp_path):
    task = _clamp_task()
    ws = tmp_path / "ws"
    (ws / "tests").mkdir(parents=True)
    (ws / "mathx.py").write_text(GOOD_CLAMP)
    (ws / "tests" / "test_mathx.py").write_text(CLAMP_TESTS)
    env = _env(ws, tmp_path)
    res = {c["id"]: run_check(env, c) for c in task.checks}
    assert all(r["passed"] for r in res.values()), res
    assert res["hidden-tests"]["message"] == "python check passed"
    # a wrong solution fails with the same message as before
    (ws / "mathx.py").write_text("def clamp(x, lo, hi):\n    return x\n")
    res = {c["id"]: run_check(env, c) for c in task.checks}
    assert res["module-exists"]["passed"] and not res["hidden-tests"]["passed"]
    assert res["hidden-tests"]["message"] == "python check failed: ASSERTION FAILED: clamp(-1, 0, 10) returned -1, expected 0"
    assert not res["agent-tests-pass"]["passed"] and "2 failed, 1 passed" in res["agent-tests-pass"]["message"]
    # timeouts keep their message
    r = run_check(env, {"id": "t", "type": "python", "code": "import time; time.sleep(5)", "timeout": 1})
    assert not r["passed"] and r["message"] == "python check timed out"
    r = run_check(env, {"id": "t2", "type": "command", "run": "sleep 5", "timeout": 1})
    assert not r["passed"] and r["message"] == "`sleep 5` timed out"


def test_shared_and_bot_paths_resolve_in_the_sandbox(tmp_path):
    ws = tmp_path / "p" / "lead" / "workspace"
    other = tmp_path / "p" / "coder" / "workspace"
    ws.mkdir(parents=True)
    other.mkdir(parents=True)
    (other / "x.txt").write_text("coder")
    env = _env(ws, tmp_path, room_id="r1", profiles={"lead": ws, "coder": other})
    env.runtime.rooms.shared_dir("r1").joinpath("s.txt").write_text("team")
    code = "assert path('shared/s.txt').read_text() == 'team'\nassert path('@coder/x.txt').read_text() == 'coder'"
    res = run_check(env, {"id": "p", "type": "python", "code": code})
    assert res["passed"], res["message"]
    res = run_check(env, {"id": "c", "type": "command", "run": "cat x.txt", "cwd": "@coder/", "expect_stdout": "coder"})
    assert res["passed"], res["message"]


@pytest.mark.skipif(not DockerBackend.available() or os.environ.get("PLAND_SKIP_DOCKER"), reason="docker not available")
def test_checks_run_in_the_tasks_docker_container(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "mod.py").write_text("import os\nWHERE = os.path.exists('/.dockerenv')\n")
    b = DockerBackend(SandboxConfig(backend="docker", docker_network="none"), "pytest-checks", ws)
    try:
        env = _env(ws, tmp_path, backend=b, room_id="r1")
        env.runtime.rooms.shared_dir("r1").joinpath("s.txt").write_text("team")
        code = "import mod\nassert mod.WHERE and str(ws) == '/workspace'\nassert path('shared/s.txt').read_text() == 'team'"
        res = run_check(env, {"id": "d", "type": "python", "code": code})
        assert res["passed"], res["message"]
        res = run_check(env, {"id": "c", "type": "command", "run": "test -f /.dockerenv && pwd", "expect_stdout": "^/workspace"})
        assert res["passed"], res["message"]
    finally:
        b.shutdown()


# ---------------------------------------------------------------------------------------------- R1: cancel race
def _suite(tmp_path: Path, tasks: list[dict]) -> Path:
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "suite.yaml").write_text(yaml.safe_dump({"description": "straggler test"}))
    for i, t in enumerate(tasks, 1):
        (suite / f"{i:02d}.yaml").write_text(yaml.safe_dump(t))
    return suite


SOLO = {"mode": "team", "team": {"room": False, "lead": "solo", "bots": [{"name": "solo", "title": "Solo"}]}}


def _run(tmp_path, monkeypatch, tasks, scripts, grace):
    monkeypatch.setenv("PLAND_HOME", str(tmp_path / "home"))
    runner = SuiteRunner(resolve_suite(str(_suite(tmp_path, tasks))), RunOptions(out_dir=tmp_path / "runs", cancel_grace_s=grace))
    llm = RoutingLLM(scripts(runner))
    set_client_override(llm)
    return runner


def _finish(runner):
    try:
        runner.run()
    finally:
        set_client_override(None)
    return {r["task_id"]: r for r in runner.records}


def test_cancel_flag_stays_set_while_the_timed_out_thread_winds_down(tmp_path, monkeypatch):
    seen: dict = {}

    def scripts(runner):
        def slow(messages, tools):  # a model call that ignores cancellation for a while
            time.sleep(1.0)
            seen["cancel_all_at_end"] = runner.rt._cancel_all
            return {"content": "late"}

        return {"default": [slow, {"content": "second task done"}]}

    tasks = [{"id": "slow", "prompt": "do it", "timeout": 0.3, "checks": [{"id": "a", "type": "answer_contains", "pattern": "x"}]},
             {"id": "next", "prompt": "next", "checks": [{"id": "a", "type": "answer_contains", "pattern": "second"}]}]
    runner = _run(tmp_path, monkeypatch, tasks, scripts, grace=20)
    recs = _finish(runner)
    try:
        assert seen["cancel_all_at_end"] is True  # not cleared after a fixed wait while the thread was alive
        assert recs["slow"]["outcome"] == "timeout" and recs["slow"]["straggler"] is None
        assert recs["next"]["outcome"] == "success" and recs["next"]["straggler"] is None
        # the slow call's ledger row is the slow task's, not the next one's
        assert recs["slow"]["usage"]["calls"] >= 1
        rows = runner.rt.ledger.db.query("SELECT session_id FROM llm_calls WHERE profile='default'")
        assert recs["next"]["usage"]["calls"] == sum(1 for r in rows if r["session_id"] != recs["slow"]["sessions"][0][1])
    finally:
        DB.close_all()


def test_straggler_usage_and_events_stay_out_of_the_next_task(tmp_path, monkeypatch):
    release = threading.Event()
    seen: dict = {}

    def scripts(runner):
        def stuck(messages, tools):  # blocks past the grace period, until the next task releases it
            release.wait(15)
            seen["straggler_still_cancelled"] = any(p == "default" for p, _ in runner.rt._cancelled)
            return {"tool_calls": [("write_file", {"path": "late.txt", "content": "x"})]}

        def solo(messages, tools):  # runs while the straggler is alive
            seen["global_flag_during_next"] = runner.rt._cancel_all
            before = runner.rt.ledger.db.one("SELECT COUNT(*) n FROM llm_calls WHERE profile='default'")["n"]
            release.set()
            deadline = time.time() + 10
            while time.time() < deadline:  # wait until the straggler's call lands in the ledger, mid-task
                if runner.rt.ledger.db.one("SELECT COUNT(*) n FROM llm_calls WHERE profile='default'")["n"] > before:
                    break
                time.sleep(0.02)
            seen["straggler_row_during_next"] = runner.rt.ledger.db.one(
                "SELECT COUNT(*) n FROM llm_calls WHERE profile='default'")["n"] > before
            return {"content": "solo done"}

        return {"default": [stuck, {"content": "third task done"}], "solo": [solo]}

    tasks = [{"id": "stuck", "prompt": "do it", "timeout": 0.3, "checks": [{"id": "a", "type": "answer_contains", "pattern": "x"}]},
             {"id": "solo", "prompt": "go", **SOLO, "checks": [{"id": "a", "type": "answer_contains", "pattern": "solo done"}]},
             {"id": "third", "prompt": "third", "checks": [{"id": "a", "type": "answer_contains", "pattern": "third"}]}]
    runner = _run(tmp_path, monkeypatch, tasks, scripts, grace=1.0)
    recs = _finish(runner)
    try:
        assert recs["stuck"]["outcome"] == "timeout"
        strag = recs["stuck"]["straggler"]
        assert strag and strag["sessions"] and strag["sessions"][0][0] == "default"
        straggler_sid = strag["sessions"][0][1]
        assert seen["global_flag_during_next"] is False  # the next task runs normally ...
        assert seen["straggler_still_cancelled"] is True  # ... while the straggler stays cancelled
        assert seen["straggler_row_during_next"] is True
        solo = recs["solo"]
        assert solo["outcome"] == "success", solo
        solo_rows = runner.rt.ledger.db.query("SELECT session_id FROM llm_calls WHERE profile='solo'")
        assert solo["usage"]["calls"] == len(solo_rows)  # the straggler's call landed meanwhile but is not counted
        assert all(s[0] == "solo" for s in solo["sessions"])
        assert straggler_sid not in {s[1] for s in solo["sessions"]}
        # the third task (same workspace as the straggler) only started once the straggler had exited
        third = recs["third"]
        assert third["outcome"] == "success", third
        assert straggler_sid not in {s[1] for s in third["sessions"]}
        assert not (runner.run_dir / "tasks" / "third" / "workspace" / "default" / "late.txt").exists()
    finally:
        release.set()
        DB.close_all()


def test_no_task_starts_in_a_workspace_a_straggler_still_uses(tmp_path, monkeypatch):
    release = threading.Event()

    def scripts(runner):
        def stuck(messages, tools):
            release.wait(15)
            return {"content": "late"}

        return {"default": [stuck]}

    tasks = [{"id": "stuck", "prompt": "do it", "timeout": 0.2, "checks": [{"id": "a", "type": "answer_contains", "pattern": "x"}]},
             {"id": "blocked", "prompt": "next", "checks": [{"id": "a", "type": "answer_contains", "pattern": "y"}]}]
    runner = _run(tmp_path, monkeypatch, tasks, scripts, grace=0.3)
    try:
        recs = _finish(runner)
        assert recs["stuck"]["straggler"]
        b = recs["blocked"]
        assert b["outcome"] == "crashed" and "still running in the workspace of @default" in b["error"], b
    finally:
        release.set()
        DB.close_all()
