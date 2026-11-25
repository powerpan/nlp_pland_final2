"""Validate suites with the real harness check code, without running any agent/model.

For every task: build the workspace exactly like the runner's `_prepare` (setup files incl. shared/ and @bot/
paths, setup commands with the same env), run all checks against the UNSOLVED state, then apply a scripted
reference solution (and simulated run records: answer, HITL log, delegation events, board) and run the checks
again. Expected: every check passes on the solution; required deliverable checks fail on the unsolved setup.
Optional extras returned by a reference solution: `negatives` (wrong variants; each must fail the checks it lists in
`expect_fail`, or at least one required check) and `alternatives` (other correct solution paths; each must pass every
check).
"""

from __future__ import annotations

import importlib
import shutil
import subprocess
import tempfile
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pland.eval.checks import CheckEnv, run_check  # noqa: E402
from pland.eval.tasks import load_suite  # noqa: E402
from pland.sandbox.backends import scrub_env  # noqa: E402

SCRATCH = Path(tempfile.gettempdir()) / "pland_validate_runs"


class StubProfiles:
    def __init__(self, root: Path, names: list[str]):
        self.root = root
        self.names = names

    def get(self, name):
        home = self.root / "profiles" / name
        ws = home / "workspace"
        ws.mkdir(parents=True, exist_ok=True)
        mem = home / "memories"
        mem.mkdir(parents=True, exist_ok=True)
        from pland.store import profile_db
        return SimpleNamespace(name=name, home=home, workspace=ws, memories_dir=mem, skills_dir=home / "skills",
                               db=profile_db(home))

    def list(self):
        return [self.get(n) for n in self.names]


class StubRooms:
    def __init__(self, root: Path):
        self.root = root

    def shared_dir(self, rid):
        p = self.root / "rooms" / rid / "shared"
        p.mkdir(parents=True, exist_ok=True)
        return p


class StubBoard:
    def __init__(self):
        self.tasks: list[dict] = []

    def list(self, scope):
        return [t for t in self.tasks if t.get("room_id") == scope]


class Ctx:
    """What a reference solution gets: paths + shell helpers."""

    def __init__(self, env: CheckEnv, room_id: str | None):
        self.env = env
        self.ws = env.workspace
        self.room_id = room_id

    def path(self, p: str) -> Path:
        return self.env.path(p)

    def write(self, p: str, text: str) -> Path:
        f = self.path(p)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
        return f

    def sh(self, cmd: str, cwd: str = ".", check: bool = True) -> subprocess.CompletedProcess:
        env = scrub_env({"GIT_AUTHOR_NAME": "ref", "GIT_AUTHOR_EMAIL": "ref@x", "GIT_COMMITTER_NAME": "ref",
                         "GIT_COMMITTER_EMAIL": "ref@x"})
        r = subprocess.run(cmd, shell=True, cwd=str(self.path(cwd)), capture_output=True, text=True, env=env,
                           executable="/bin/bash", timeout=300)
        if check and r.returncode != 0:
            raise RuntimeError(f"ref command failed: {cmd}\n{r.stdout}\n{r.stderr}")
        return r


def build_env(task, root: Path):
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    if task.mode == "team":
        names = [b["name"] for b in task.team["bots"]]
        primary = task.team.get("lead") or names[0]
        room_id = "room_test"
    else:
        names = ["default"]
        primary = "default"
        room_id = None
    rt = SimpleNamespace(profiles=StubProfiles(root, names), rooms=StubRooms(root), board=StubBoard())
    ws = rt.profiles.get(primary).workspace
    env = CheckEnv(rt, primary, ws, "", room_id, room_id or f"dm:{primary}", [], [])
    for rel, content in (task.setup.get("files") or {}).items():
        p = env.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content if isinstance(content, str) else __import__("json").dumps(content, indent=2), encoding="utf-8")
    for cmd in task.setup.get("commands") or []:
        r = subprocess.run(cmd, shell=True, cwd=str(ws), capture_output=True, text=True, timeout=120,
                           env=scrub_env({"GIT_AUTHOR_NAME": "setup", "GIT_AUTHOR_EMAIL": "setup@eval",
                                          "GIT_COMMITTER_NAME": "setup", "GIT_COMMITTER_EMAIL": "setup@eval"}),
                           executable="/bin/bash")
        if r.returncode != 0:
            raise RuntimeError(f"setup command failed: {cmd}: {r.stderr[-400:]}")
    return env, room_id


def run_checks(task, env):
    return [run_check(env, c) for c in task.checks]


def main(suites: list[str], only: set[str] | None = None) -> int:
    problems = 0
    for suite in suites:
        meta, tasks = load_suite(REPO / "pland/eval/suites" / suite)
        refs = importlib.import_module(f"ref_{suite}").REFS
        print(f"\n=== suite {suite}: {len(tasks)} tasks — {meta.get('description', '')[:70]}...")
        for task in tasks:
            if only and task.id not in only:
                continue
            req = set(task.required_ids)
            # unsolved
            env, room_id = build_env(task, SCRATCH / suite / task.id / "unsolved")
            before = run_checks(task, env)
            # solved
            env2, room_id = build_env(task, SCRATCH / suite / task.id / "solved")
            ref = refs.get(task.id)
            if ref is None:
                print(f"  !! {task.id}: no reference solution")
                problems += 1
                continue
            try:
                rec = ref(Ctx(env2, room_id)) or {}
            except Exception:
                print(f"  !! {task.id}: reference solution crashed\n{traceback.format_exc()}")
                problems += 1
                continue
            env2.answer = rec.get("answer", "")
            env2.hitl_log = rec.get("hitl", [])
            env2.events = rec.get("events", [])
            env2.runtime.board.tasks = [dict(t, room_id=env2.board_scope) for t in rec.get("board", [])]
            after = run_checks(task, env2)
            bad_after = [c for c in after if not c["passed"]]
            pass_before_req = [c for c in before if c["passed"] and c["id"] in req]
            status = "OK " if not bad_after else "FAIL"
            print(f"  {status} {task.id:<34} checks={len(task.checks):>2} required={len(req):>2} "
                  f"| unsolved: {sum(c['passed'] for c in before)}/{len(before)} pass "
                  f"(required passing unsolved: {[c['id'] for c in pass_before_req]})")
            for c in bad_after:
                problems += 1
                print(f"       ✗ {c['id']}: {c['message'][:900]}")
            # sanity: unsolved must not satisfy all required checks
            if all(c["passed"] for c in before if c["id"] in req):
                problems += 1
                print("       ✗ unsolved setup already satisfies all required checks!")
            # optional negative variants
            for name, neg in (rec.get("negatives") or {}).items():
                env3, room_id3 = build_env(task, SCRATCH / suite / task.id / f"neg-{name}")
                nrec = neg(Ctx(env3, room_id3)) or {}
                env3.answer = nrec.get("answer", "")
                env3.hitl_log = nrec.get("hitl", [])
                env3.events = nrec.get("events", [])
                env3.runtime.board.tasks = [dict(t, room_id=env3.board_scope) for t in nrec.get("board", [])]
                res = run_checks(task, env3)
                failed = [c["id"] for c in res if not c["passed"]]
                expect = set(nrec.get("expect_fail", []))
                ok = expect <= set(failed) if expect else bool(set(failed) & req)
                print(f"       {'ok' if ok else '✗!'} negative '{name}': failing={failed}")
                if not ok:
                    problems += 1
            # optional alternative correct solutions (e.g. another valid collaboration path)
            for name, alt in (rec.get("alternatives") or {}).items():
                env4, room_id4 = build_env(task, SCRATCH / suite / task.id / f"alt-{name}")
                arec = alt(Ctx(env4, room_id4)) or {}
                env4.answer = arec.get("answer", "")
                env4.hitl_log = arec.get("hitl", [])
                env4.events = arec.get("events", [])
                env4.runtime.board.tasks = [dict(t, room_id=env4.board_scope) for t in arec.get("board", [])]
                failed = [c for c in run_checks(task, env4) if not c["passed"]]
                print(f"       {'ok' if not failed else '✗!'} alternative '{name}': "
                      f"{'all checks pass' if not failed else 'failing=' + str([c['id'] for c in failed])}")
                for c in failed:
                    problems += 1
                    print(f"           ✗ {c['id']}: {c['message'][:600]}")
    print(f"\nproblems: {problems}")
    return 1 if problems else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    only = None
    if "--only" in args:
        i = args.index("--only")
        only = set(args[i + 1].split(","))
        args = args[:i] + args[i + 2:]
    sys.exit(main(args or ["dev", "midterm", "final", "memory_evolution", "hard"], only))
