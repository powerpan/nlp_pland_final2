"""Objective verifiers. Every check returns (passed, message); none of them trusts the agent's claims."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from ..memory import ExperienceStore, NotesMemory
from ..sandbox.backends import scrub_env

if TYPE_CHECKING:
    from ..runtime import Runtime


@dataclass
class CheckEnv:
    runtime: "Runtime"
    primary_profile: str
    workspace: Path
    answer: str
    room_id: str | None
    board_scope: str
    hitl_log: list[dict[str, Any]]
    events: list[dict[str, Any]]
    result: dict[str, Any] = field(default_factory=dict)

    def path(self, raw: str) -> Path:
        raw = str(raw).strip()
        if raw.startswith("shared/") or raw == "shared":
            if not self.room_id:
                raise ValueError("shared/ paths need a team task with a room")
            return self.runtime.rooms.shared_dir(self.room_id) / raw[len("shared/"):]
        if raw.startswith("@"):
            bot, _, rest = raw[1:].partition("/")
            return self.runtime.profiles.get(bot).workspace / rest
        return self.workspace / raw


def _read(env: CheckEnv, c: dict) -> tuple[Path, str | None]:
    p = env.path(c["path"])
    if not p.is_file():
        return p, None
    return p, p.read_text(encoding="utf-8", errors="replace")


def check_file_exists(env, c):
    p = env.path(c["path"])
    ok = p.exists() and (p.is_dir() or p.stat().st_size > 0 or c.get("allow_empty"))
    return ok, f"{c['path']} {'exists' if ok else 'is missing or empty'}"


def check_file_absent(env, c):
    p = env.path(c["path"])
    return not p.exists(), f"{c['path']} {'absent' if not p.exists() else 'still exists'}"


def check_file_contains(env, c):
    p, text = _read(env, c)
    if text is None:
        return False, f"{c['path']} missing"
    ok = re.search(c["pattern"], text, re.MULTILINE) is not None
    return ok, f"pattern {c['pattern']!r} {'found' if ok else 'not found'} in {c['path']}"


def check_file_not_contains(env, c):
    p, text = _read(env, c)
    if text is None:
        return False, f"{c['path']} missing"
    ok = re.search(c["pattern"], text, re.MULTILINE) is None
    return ok, f"pattern {c['pattern']!r} {'absent' if ok else 'present'} in {c['path']}"


def _run(cmd: list[str] | str, cwd: Path, timeout: float, *, shell: bool = False, stdin: str | None = None):
    return subprocess.run(cmd, cwd=str(cwd), shell=shell, input=stdin, capture_output=True, text=True,
                          errors="replace", timeout=timeout, env=scrub_env(), executable="/bin/bash" if shell else None)


def check_command(env, c):
    cwd = env.path(c.get("cwd") or ".")
    if not cwd.is_dir():
        return False, f"cwd {c.get('cwd')} missing"
    try:
        r = _run(c["run"], cwd, float(c.get("timeout") or 120), shell=True)
    except subprocess.TimeoutExpired:
        return False, f"`{c['run']}` timed out"
    exp = int(c.get("expect_exit", 0))
    ok = r.returncode == exp
    msg = f"`{c['run']}` exit {r.returncode} (expected {exp})"
    if ok and c.get("expect_stdout"):
        ok = re.search(c["expect_stdout"], r.stdout + r.stderr, re.MULTILINE) is not None
        msg += f"; output {'matches' if ok else 'does not match'} {c['expect_stdout']!r}"
    if not ok:
        msg += "\n" + (r.stdout + r.stderr)[-800:]
    return ok, msg


_PY_HARNESS = r'''
import json, sys, traceback
from pathlib import Path
_ctx = json.load(open(sys.argv[1]))
ws = Path(_ctx["ws"]); answer = _ctx["answer"]; result = _ctx["result"]
_roots = _ctx["roots"]
def path(p):
    p = str(p).strip()
    if p.startswith("shared/") or p == "shared":
        return Path(_roots["shared"]) / p[len("shared/"):]
    if p.startswith("@"):
        bot, _, rest = p[1:].partition("/")
        return Path(_roots["bots"][bot]) / rest
    return ws / p
sys.path.insert(0, str(ws))
try:
    import ast
    _tree = ast.parse(_ctx["code"], "<check>")
    if any(isinstance(n, ast.Return) for n in ast.walk(_tree)):
        # Top-level `return x` is allowed: wrap the parsed body in a function (no textual re-indent,
        # so multi-line string literals stay intact).
        _fn = ast.FunctionDef(name="_check", args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[],
                              defaults=[]), body=_tree.body or [ast.Pass()], decorator_list=[], returns=None, type_params=[])
        _call = ast.Assign(targets=[ast.Name("_return", ast.Store())], value=ast.Call(ast.Name("_check", ast.Load()), [], []))
        _tree = ast.fix_missing_locations(ast.Module(body=[_fn, _call], type_ignores=[]))
    _ns = dict(ws=ws, answer=answer, result=result, path=path, Path=Path)
    exec(compile(_tree, "<check>", "exec"), _ns)
    _out = _ns.get("_return")
except AssertionError as e:
    print("ASSERTION FAILED: " + (str(e) or "assert"), file=sys.stderr); sys.exit(1)
except Exception:
    traceback.print_exc(limit=3); sys.exit(2)
sys.exit(0 if _out in (None, True) else 1)
'''


def check_python(env, c):
    code = c["code"]
    roots = {"shared": str(env.runtime.rooms.shared_dir(env.room_id)) if env.room_id else "",
             "bots": {p.name: str(p.workspace) for p in env.runtime.profiles.list()}}
    with tempfile.TemporaryDirectory() as tmp:
        ctx_file = Path(tmp) / "ctx.json"
        ctx_file.write_text(json.dumps({"ws": str(env.workspace), "answer": env.answer, "result": env.result,
                                        "roots": roots, "code": code}, default=str), encoding="utf-8")
        script = Path(tmp) / "check.py"
        script.write_text(_PY_HARNESS, encoding="utf-8")
        try:
            r = _run([sys.executable, str(script), str(ctx_file)], env.workspace if env.workspace.is_dir() else Path(tmp),
                     float(c.get("timeout") or 120))
        except subprocess.TimeoutExpired:
            return False, "python check timed out"
    ok = r.returncode == 0
    detail = (r.stderr or r.stdout).strip()[-800:]
    return ok, "python check passed" if ok else f"python check failed: {detail}"


def check_answer_contains(env, c):
    ok = re.search(c["pattern"], env.answer or "", re.MULTILINE) is not None
    return ok, f"answer {'matches' if ok else 'does not match'} {c['pattern']!r}"


def check_answer_not_contains(env, c):
    ok = re.search(c["pattern"], env.answer or "", re.MULTILINE) is None
    return ok, f"answer {'does not contain' if ok else 'contains'} {c['pattern']!r}"


def _git(cwd: Path, *args: str):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=60)


def check_git_commits(env, c):
    repo = env.path(c.get("repo") or ".")
    r = _git(repo, "log", "--format=%s", c.get("ref") or "HEAD")
    if r.returncode != 0:
        return False, f"not a git repo or no commits: {r.stderr.strip()[:200]}"
    msgs = [m for m in r.stdout.splitlines() if m.strip()]
    if c.get("message_pattern"):
        matching = [m for m in msgs if re.search(c["message_pattern"], m)]
    else:
        matching = msgs
    need = int(c.get("min", 1))
    ok = len(matching) >= need
    return ok, f"{len(matching)} matching commit(s) (need ≥{need}): {msgs[:5]}"


def check_git_clean(env, c):
    repo = env.path(c.get("repo") or ".")
    r = _git(repo, "status", "--porcelain")
    if r.returncode != 0:
        return False, "not a git repository"
    dirty = [l for l in r.stdout.splitlines() if l.strip()]
    return not dirty, "working tree clean" if not dirty else f"uncommitted changes: {dirty[:5]}"


def check_hitl(env, c):
    kind = c.get("kind", "clarify")
    n = sum(1 for x in env.hitl_log if x["kind"] == kind)
    lo, hi = int(c.get("min", 0 if "max" in c else 1)), c.get("max")
    ok = n >= lo and (hi is None or n <= int(hi))
    return ok, f"{n} {kind} request(s) (expected {'≥' + str(lo)}{'' if hi is None else ', ≤' + str(hi)})"


def check_memory_contains(env, c):
    prof = env.runtime.profiles.get(c.get("profile") or env.primary_profile)
    target = c.get("target", "memory")
    text = "\n".join(NotesMemory(prof).entries(target))
    ok = re.search(c["pattern"], text, re.MULTILINE) is not None
    return ok, f"{target} memory of @{prof.name} {'contains' if ok else 'lacks'} {c['pattern']!r}"


def check_experience_count(env, c):
    prof = env.runtime.profiles.get(c.get("profile") or env.primary_profile)
    n = len(ExperienceStore(prof).all())
    need = int(c.get("min", 1))
    return n >= need, f"{n} experience record(s) for @{prof.name} (need ≥{need})"


def check_delegated(env, c):
    done = [e for e in env.events if e["type"] == "delegation.finished"]
    to = c.get("to")
    if to:
        to = [to] if isinstance(to, str) else list(to)
        done = [e for e in done if e.get("to") in to]
    if c.get("successful", True):
        done = [e for e in done if e.get("status") == "completed"]
    need = int(c.get("min", 1))
    return len(done) >= need, f"{len(done)} delegation(s){' to ' + ','.join(to) if to else ''} (need ≥{need})"


def check_board_tasks(env, c):
    tasks = env.runtime.board.list(c.get("scope") or env.board_scope)
    if c.get("status"):
        tasks = [t for t in tasks if t["status"] == c["status"]]
    need = int(c.get("min", 1))
    return len(tasks) >= need, f"{len(tasks)} board task(s){' with status ' + c['status'] if c.get('status') else ''} (need ≥{need})"


CHECKS: dict[str, Callable[[CheckEnv, dict], tuple[bool, str]]] = {
    "file_exists": check_file_exists,
    "file_absent": check_file_absent,
    "file_contains": check_file_contains,
    "file_not_contains": check_file_not_contains,
    "command": check_command,
    "python": check_python,
    "answer_contains": check_answer_contains,
    "answer_not_contains": check_answer_not_contains,
    "git_commits": check_git_commits,
    "git_clean": check_git_clean,
    "hitl": check_hitl,
    "memory_contains": check_memory_contains,
    "experience_count": check_experience_count,
    "delegated": check_delegated,
    "board_tasks": check_board_tasks,
}


def run_check(env: CheckEnv, c: dict[str, Any]) -> dict[str, Any]:
    fn = CHECKS.get(c.get("type", ""))
    if fn is None:
        return {"id": c["id"], "type": c.get("type"), "passed": False, "message": f"unknown check type {c.get('type')!r}",
                "weight": float(c.get("weight", 1))}
    try:
        ok, msg = fn(env, c)
    except Exception as exc:  # a broken check counts as failed, with the reason recorded
        ok, msg = False, f"check error: {type(exc).__name__}: {exc}"
    return {"id": c["id"], "type": c["type"], "passed": bool(ok), "message": msg, "weight": float(c.get("weight", 1))}
