"""Shell and Python execution through the profile's sandbox backend."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from ..approvals import clip_detail
from ..sandbox import check_command, scan_python
from ..team import fast as fastmode
from .registry import ToolContext, ToolError, obj, tool


def _link_room_shared(ctx: ToolContext) -> None:
    """Make `shared/` usable from shell commands too: in a room context the workspace gets a `shared`
    symlink to the room's shared folder (re-pointed if the agent last worked in another room). File tools
    only follow it while the room context is active; outside it the link resolves outside the allowed roots."""
    shared = ctx.mounts.get("shared")
    if shared is None:
        return
    # local: point at the room folder on the host; docker: at the /shared mount inside the container
    target = Path("/shared") if ctx.backend.isolated else shared.resolve()
    link = ctx.workspace / "shared"
    try:
        if link.is_symlink():
            if Path(os.readlink(link)) == target:
                return
            link.unlink()
        elif link.exists():
            return  # a real folder named shared/ exists: leave the agent's data alone
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pass


def _cwd(ctx: ToolContext, raw: str | None):
    _link_room_shared(ctx)
    path = ctx.paths.resolve(raw or ".")
    if not path.is_dir():
        raise ToolError(f"cwd {raw!r} is not a directory")
    return path


def _execution_limits(ctx: ToolContext, requested: float | None) -> dict:
    timeout = requested or ctx.settings.sandbox.command_timeout
    agent = ctx.agent
    while agent is not None:
        if agent.deadline is not None:
            timeout = min(timeout, max(0.01, agent.deadline - time.time()))
        agent = agent.caller
    return {"timeout": timeout, "cancel": ctx.agent._cancel_requested}


CONTAINER_STILL_ASK = ("delete", "push", "credential", "publish", "secret", "discard", "DROP", "TRUNCATE", "Unicode")


def _gate(ctx: ToolContext, verdict, what: str, text: str) -> None:
    if verdict.blocked:
        raise ToolError(f"Blocked by the safety floor ({verdict.blocked}). This can never run through the agent.")
    if verdict.needs_approval:
        # Inside a container the container contains system-level damage (sudo, chmod, killing processes,
        # system config), so those need no approval there. The agent's real workspace is
        # bind-mounted into the container, so destroying data still needs a human — as do operations that
        # reach outside (push, credentials, secrets, publishing).
        reasons = verdict.needs_approval
        if ctx.backend.isolated:
            reasons = [r for r in reasons if any(k in r for k in CONTAINER_STILL_ASK)]
        for reason in reasons:
            ctx.require_approval(f"{what}:{reason}", f"{what} wants to: {reason}", detail=clip_detail(text))


@tool(
    "run_shell",
    "Run a bash command in your workspace (or a sub-directory via cwd) and return exit code, stdout and stderr. "
    "Use it for builds, tests, package installs, git inspection, etc. Long-running servers and background jobs are not "
    "supported: anything still running when the command returns is stopped. "
    "For headless Chromium on macOS, use a temporary user-data directory and --use-mock-keychain.",
    obj({"command": {"type": "string"}, "cwd": {"type": "string"}, "timeout": {"type": "integer", "minimum": 1, "maximum": 600}}, ["command"]),
    "code",
)
def run_shell(ctx: ToolContext, a):
    cmd = a["command"]
    if re.search(r"\bgit\b[^\n;|&]*\bpush\b", cmd) and (ctx.backend.isolated or getattr(ctx.backend, "seatbelt", False)):
        # Sandboxed shells have no access to the user's credential helper (private HOME / container).
        raise ToolError("Pushing is only allowed through the git_push tool (it runs on the host with the user's "
                        "credentials after the human approves). Do not push by any other means — no scripts, git "
                        "libraries or alternative clients.")
    _gate(ctx, check_command(cmd), "shell", cmd)
    cwd = _cwd(ctx, a.get("cwd"))
    with _timed(ctx, a.get("timeout")) as (timeout, note):
        res = ctx.backend.run(cmd, cwd, mounts=ctx.mounts, **_execution_limits(ctx, timeout))
        note(res)
    ctx.emit("exec.finished", kind="shell", command=cmd[:500], exit_code=res.exit_code, duration=round(res.duration, 2))
    return res.render(ctx.settings.sandbox.max_output_chars) + _fast_note(ctx)


@tool(
    "run_python",
    "Execute Python 3 source code in your workspace and return exit code, stdout and stderr. "
    "To keep code, write it to a file with write_file and run it with run_shell instead.",
    obj({"code": {"type": "string"}, "cwd": {"type": "string"}, "timeout": {"type": "integer", "minimum": 1, "maximum": 600}}, ["code"]),
    "code",
)
def run_python(ctx: ToolContext, a):
    code = a["code"]
    _gate(ctx, scan_python(code), "python", code)
    cwd = _cwd(ctx, a.get("cwd"))
    with _timed(ctx, a.get("timeout")) as (timeout, note):
        res = ctx.backend.run_python(code, cwd, mounts=ctx.mounts, **_execution_limits(ctx, timeout))
        note(res)
    ctx.emit("exec.finished", kind="python", exit_code=res.exit_code, duration=round(res.duration, 2))
    return res.render(ctx.settings.sandbox.max_output_chars) + _fast_note(ctx)


@tool(
    "run_checks",
    "Fast Mode: run the acceptance checks recorded on a board card (team_tasks `checks`) against its `files`. A check "
    "that already passed on the same file contents is reused instead of run again. Each check counts against the "
    "team's command time. Returns each check's result and which of the card's files are verified.",
    obj({"task_id": {"type": "string"}}, ["task_id"]),
    "code",
)
def run_checks(ctx: ToolContext, a):
    fast = fastmode.of(ctx.agent)
    if fast is None:
        raise ToolError("run_checks works only in a group with Fast Mode on; run the commands with run_shell instead")
    tid = a["task_id"]
    ctx.runtime.board.get(tid)  # validates the id
    scope = fast.scope(tid)
    if not scope["checks"]:
        raise ToolError(f"card {tid} has no checks; add them with team_tasks update(task_id, files=[...], checks=[...])")
    cwd = _cwd(ctx, None)
    lines: list[str] = []
    for i, cmd in enumerate(scope["checks"]):
        current = fastmode.scope_versions(scope)
        if fast.passed_check(tid, cmd, current):
            lines.append(f"- `{cmd}`: passed earlier on the same file contents (reused, not run again)")
            continue
        try:
            _gate(ctx, check_command(cmd), "shell", cmd)
            with _timed(ctx, None) as (timeout, note):
                res = ctx.backend.run(cmd, cwd, mounts=ctx.mounts, **_execution_limits(ctx, timeout))
                note(res)
        except ToolError as exc:
            left = scope["checks"][i:]
            lines.append(f"- not run ({str(exc).splitlines()[0]}): " + " | ".join(f"`{c}`" for c in left))
            break
        ok = res.exit_code == 0 and not res.timed_out
        fast.record(task_id=tid, kind="check", subject=cmd, files=current, result="pass" if ok else "fail",
                    report=(res.stdout or "")[-2000:] + (res.stderr or "")[-2000:])
        ctx.emit("exec.finished", kind="check", command=cmd[:500], exit_code=res.exit_code, duration=round(res.duration, 2))
        if ok:
            lines.append(f"- `{cmd}`: PASS ({res.duration:.1f}s)")
        else:
            lines.append(f"- `{cmd}`: FAIL\n" + res.render(4000))
    return f"Checks of {tid}:\n" + "\n".join(lines) + "\n\n" + fast.status_text() + "\n" + fast.describe()


class _timed:
    """Hold Fast Mode command time around one command: the timeout is capped at the per-command limit and at the
    team's remaining time, and what the command really took is charged afterwards. Outside Fast Mode it only passes
    the requested timeout through."""

    def __init__(self, ctx: ToolContext, requested):
        self.fast = fastmode.of(ctx.agent)
        self.requested = requested
        self.held = 0.0
        self.duration = None

    def __enter__(self):
        if self.fast is None:
            return self.requested, lambda res: None
        try:
            self.held = self.fast.reserve(self.requested)
        except fastmode.FastLimit as exc:
            raise ToolError(str(exc))

        def note(res):
            self.duration = res.duration
        return self.held, note

    def __exit__(self, *exc):
        if self.fast is not None and self.held:
            self.fast.settle(self.held, self.held if self.duration is None else self.duration)
        return False


def _fast_note(ctx: ToolContext) -> str:
    fast = fastmode.of(ctx.agent)
    return "\n[" + fast.describe() + "]" if fast is not None else ""
