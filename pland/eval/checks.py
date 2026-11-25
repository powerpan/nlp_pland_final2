"""Objective verifiers. Every check returns (passed, message); none of them trusts the agent's claims.

Checks that only read files, the answer or the runtime's records run in this process. Checks that execute
anything — `command`, `python` (which imports the agent's modules) and the git checks (git runs hooks, filters
and fsmonitor commands a repository's config names) — run through the task's sandbox backend (local+Seatbelt
on macOS, or the task's Docker container), so code an agent planted in its workspace never runs unconfined on
the host during scoring. A `python` check that needs host-only state (e.g. the runtime's event database) says
so with `host: true`: it then runs on the host, but without the workspace on `sys.path` and outside it.
The check code itself reaches the sandbox on stdin; it is never written to disk.
"""

from __future__ import annotations

import errno
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from ..config import SandboxConfig
from ..memory import ExperienceStore, NotesMemory
from ..sandbox.backends import Backend, ExecResult, LocalBackend, scrub_env

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
    # The task's sandbox (the runner passes the backend the agent used). None: a local backend confined to the
    # workspace (Seatbelt on macOS) with a private HOME outside it, created on first use.
    backend: Backend | None = None

    def sandbox(self) -> Backend:
        if self.backend is None:
            home = Path(tempfile.mkdtemp(prefix="pland-check-home-"))
            weakref.finalize(self, shutil.rmtree, str(home), True)
            self.backend = LocalBackend(SandboxConfig(), workspace=self.workspace, home_dir=home)
        return self.backend

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


_BOT_REF = re.compile(r"@([A-Za-z0-9_][A-Za-z0-9_.-]*)/")


def _isolated(backend: Backend) -> bool:
    return bool(getattr(backend, "isolated", False))


def _sandbox_roots(env: CheckEnv, text: str) -> tuple[dict[str, Path], dict[str, Any]]:
    """Mounts for a sandboxed check, and the roots its `path()` helper maps to (as seen inside the sandbox):
    the room's shared folder, plus every other bot workspace the check refers to as `@bot/...`."""
    backend = env.sandbox()
    iso = _isolated(backend)
    mounts: dict[str, Path] = {}
    shared = ""
    if env.room_id:
        mounts["shared"] = env.runtime.rooms.shared_dir(env.room_id)
        shared = "/shared" if iso else str(mounts["shared"])
    bots: dict[str, str] = {}
    referenced = set(_BOT_REF.findall(text))
    for prof in env.runtime.profiles.list():
        ws = Path(prof.workspace)
        if ws.resolve() == env.workspace.resolve():
            bots[prof.name] = "/workspace" if iso else str(ws)
        elif prof.name in referenced:
            mounts[f"bot-{prof.name}"] = ws
            bots[prof.name] = f"/bot-{prof.name}" if iso else str(ws)
        else:  # not mounted: unreadable from the sandbox, as it was for the agent
            bots[prof.name] = str(ws)
    return mounts, {"ws": "/workspace" if iso else str(env.workspace), "shared": shared, "bots": bots}


def _missing_cwd(cwd: Path) -> FileNotFoundError:
    # the error subprocess raised when these checks ran on the host (the backends would create the folder instead)
    return FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(cwd))


def check_command(env, c):
    cwd = env.path(c.get("cwd") or ".")
    if not cwd.is_dir():
        return False, f"cwd {c.get('cwd')} missing"
    mounts, _ = _sandbox_roots(env, f"{c.get('cwd') or ''}\n{c['run']}")
    r = env.sandbox().run(c["run"], cwd, timeout=float(c.get("timeout") or 120), mounts=mounts)
    if r.timed_out:
        return False, f"`{c['run']}` timed out"
    exp = int(c.get("expect_exit", 0))
    ok = r.exit_code == exp
    msg = f"`{c['run']}` exit {r.exit_code} (expected {exp})"
    if ok and c.get("expect_stdout"):
        ok = re.search(c["expect_stdout"], r.stdout + r.stderr, re.MULTILINE) is not None
        msg += f"; output {'matches' if ok else 'does not match'} {c['expect_stdout']!r}"
    if not ok:
        msg += "\n" + (r.stdout + r.stderr)[-800:]
    return ok, msg


# Runs as `python -I -` with this text on stdin; _CTX (the check code, answer, run result and roots) is prepended.
_PY_HARNESS = r"""
import json, os, sys, traceback
from pathlib import Path
_ctx = json.loads(_CTX)
del _CTX
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
if _ctx.get("git_env"):
    os.environ.update(_ctx["git_env"])
if _ctx["import_ws"]:
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
"""

# git refuses repositories owned by another uid (the container runs as root on host-owned files)
_CONTAINER_GIT_ENV = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "safe.directory", "GIT_CONFIG_VALUE_0": "*"}


def _host_python(code: str, timeout: float) -> ExecResult:
    """A `host: true` check: on the host, isolated mode, cwd outside every workspace, nothing imported from them."""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            r = subprocess.run([sys.executable, "-I", "-"], cwd=tmp, input=code, capture_output=True, text=True,
                               errors="replace", timeout=timeout, env=scrub_env())
        except subprocess.TimeoutExpired:
            return ExecResult(-9, "", "", True)
    return ExecResult(r.returncode, r.stdout, r.stderr)


def check_python(env, c):
    code = c["code"]
    timeout = float(c.get("timeout") or 120)
    host = bool(c.get("host"))
    ctx: dict[str, Any] = {"answer": env.answer, "result": env.result, "code": code, "import_ws": not host}
    if host:
        roots = {"shared": str(env.runtime.rooms.shared_dir(env.room_id)) if env.room_id else "",
                 "bots": {p.name: str(p.workspace) for p in env.runtime.profiles.list()}}
        ctx.update(ws=str(env.workspace), roots=roots)
        r = _host_python(f"_CTX = {json.dumps(json.dumps(ctx, default=str))}\n{_PY_HARNESS}", timeout)
    else:
        backend = env.sandbox()
        mounts, roots = _sandbox_roots(env, code)
        ctx.update(ws=roots.pop("ws"), roots=roots, git_env=_CONTAINER_GIT_ENV if _isolated(backend) else None)
        script = f"_CTX = {json.dumps(json.dumps(ctx, default=str))}\n{_PY_HARNESS}"
        if env.workspace.is_dir():
            r = backend.run_python(script, env.workspace, timeout=timeout, mounts=mounts)
        else:
            with tempfile.TemporaryDirectory() as tmp:
                r = backend.run_python(script, Path(tmp), timeout=timeout, mounts=mounts)
    if r.timed_out:
        return False, "python check timed out"
    ok = r.exit_code == 0
    detail = (r.stderr or r.stdout).strip()[-800:]
    return ok, "python check passed" if ok else f"python check failed: {detail}"


def check_answer_contains(env, c):
    ok = re.search(c["pattern"], env.answer or "", re.MULTILINE) is not None
    return ok, f"answer {'matches' if ok else 'does not match'} {c['pattern']!r}"


def check_answer_not_contains(env, c):
    ok = re.search(c["pattern"], env.answer or "", re.MULTILINE) is None
    return ok, f"answer {'does not contain' if ok else 'contains'} {c['pattern']!r}"


def _git(env: CheckEnv, cwd: Path, *args: str) -> ExecResult:
    if not cwd.is_dir():
        raise _missing_cwd(cwd)
    backend = env.sandbox()
    mounts, _ = _sandbox_roots(env, "")
    pre = ["-c", "safe.directory=*"] if _isolated(backend) else []
    return backend.run(" ".join(shlex.quote(a) for a in ["git", *pre, *args]), cwd, timeout=60, mounts=mounts)


def check_git_commits(env, c):
    repo = env.path(c.get("repo") or ".")
    r = _git(env, repo, "log", "--format=%s", c.get("ref") or "HEAD")
    if r.exit_code != 0:
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
    r = _git(env, repo, "status", "--porcelain")
    if r.exit_code != 0:
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
