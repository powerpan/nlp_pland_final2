"""Shell and Python execution through the profile's sandbox backend."""

from __future__ import annotations

from ..sandbox import check_command, scan_python
from .registry import ToolContext, ToolError, obj, tool


def _link_room_shared(ctx: ToolContext) -> None:
    """Make `shared/` usable from shell commands too: in a room context the workspace gets a `shared`
    symlink to the room's shared folder (re-pointed if the agent last worked in another room). File tools
    only follow it while the room context is active; outside it the link resolves outside the allowed roots."""
    shared = ctx.mounts.get("shared")
    if shared is None or ctx.backend.isolated:
        return
    link = ctx.workspace / "shared"
    try:
        if link.is_symlink():
            if link.resolve() == shared.resolve():
                return
            link.unlink()
        elif link.exists():
            return  # a real folder named shared/ exists: leave the agent's data alone
        link.symlink_to(shared.resolve(), target_is_directory=True)
    except OSError:
        pass


def _cwd(ctx: ToolContext, raw: str | None):
    _link_room_shared(ctx)
    path = ctx.paths.resolve(raw or ".")
    if not path.is_dir():
        raise ToolError(f"cwd {raw!r} is not a directory")
    return path


def _gate(ctx: ToolContext, verdict, what: str, text: str) -> None:
    if verdict.blocked:
        raise ToolError(f"Blocked by the safety floor ({verdict.blocked}). This can never run through the agent.")
    for reason in verdict.needs_approval or ():
        ctx.require_approval(f"{what}:{reason}", f"{what} wants to: {reason}", detail=text[:2000])


@tool(
    "run_shell",
    "Run a bash command in your workspace (or a sub-directory via cwd) and return exit code, stdout and stderr. "
    "Use it for builds, tests, package installs, git inspection, etc. Long-running servers are not supported.",
    obj({"command": {"type": "string"}, "cwd": {"type": "string"}, "timeout": {"type": "integer", "minimum": 1, "maximum": 1800}}, ["command"]),
    "code",
)
def run_shell(ctx: ToolContext, a):
    cmd = a["command"]
    _gate(ctx, check_command(cmd), "shell", cmd)
    res = ctx.backend.run(cmd, _cwd(ctx, a.get("cwd")), timeout=a.get("timeout"), mounts=ctx.mounts)
    ctx.emit("exec.finished", kind="shell", command=cmd[:500], exit_code=res.exit_code, duration=round(res.duration, 2))
    return res.render(ctx.settings.sandbox.max_output_chars)


@tool(
    "run_python",
    "Execute Python 3 source code in your workspace and return exit code, stdout and stderr. "
    "To keep code, write it to a file with write_file and run it with run_shell instead.",
    obj({"code": {"type": "string"}, "cwd": {"type": "string"}, "timeout": {"type": "integer", "minimum": 1, "maximum": 1800}}, ["code"]),
    "code",
)
def run_python(ctx: ToolContext, a):
    code = a["code"]
    _gate(ctx, scan_python(code), "python", code)
    res = ctx.backend.run_python(code, _cwd(ctx, a.get("cwd")), timeout=a.get("timeout"), mounts=ctx.mounts)
    ctx.emit("exec.finished", kind="python", exit_code=res.exit_code, duration=round(res.duration, 2))
    return res.render(ctx.settings.sandbox.max_output_chars)
