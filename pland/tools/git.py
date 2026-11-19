"""Version control: real git commits and pushes inside the agent's workspace.

Git always runs on the host (even with the docker backend) so the user's configured credential
helper (e.g. `gh auth`) can authenticate pushes; pushing is outward-facing and always needs
human approval.
"""

from __future__ import annotations

import shlex
import subprocess

from ..sandbox.backends import scrub_env
from .registry import ToolContext, ToolError, obj, tool


def _repo(ctx: ToolContext, raw: str | None):
    path = ctx.paths.resolve(raw or ".")
    if not path.is_dir():
        raise ToolError(f"{raw!r} is not a directory")
    return path


def _git(ctx: ToolContext, cwd, *args: str, timeout: float = 120) -> subprocess.CompletedProcess:
    env = scrub_env()
    env.setdefault("GIT_AUTHOR_NAME", f"pland-{ctx.profile.name}")
    env.setdefault("GIT_AUTHOR_EMAIL", f"{ctx.profile.name}@pland.local")
    env.setdefault("GIT_COMMITTER_NAME", env["GIT_AUTHOR_NAME"])
    env.setdefault("GIT_COMMITTER_EMAIL", env["GIT_AUTHOR_EMAIL"])
    return subprocess.run(["git", *args], cwd=str(cwd), env=env, capture_output=True, text=True, timeout=timeout)


def _out(r: subprocess.CompletedProcess) -> str:
    text = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
    return f"exit_code: {r.returncode}\n{text.strip()}"


@tool(
    "git_status",
    "Show `git status --short --branch` and the latest commits of a repository in your workspace. Initialise with init=true.",
    obj({"repo": {"type": "string", "description": "repository directory (default: workspace root)"}, "init": {"type": "boolean"}}),
    "git",
)
def git_status(ctx: ToolContext, a):
    repo = _repo(ctx, a.get("repo"))
    if a.get("init") and not (repo / ".git").exists():
        r = _git(ctx, repo, "init", "-b", "main")
        if r.returncode != 0:
            raise ToolError(_out(r))
    st = _git(ctx, repo, "status", "--short", "--branch")
    if st.returncode != 0:
        return _out(st)
    log = _git(ctx, repo, "log", "--oneline", "-5")
    remotes = _git(ctx, repo, "remote", "-v")
    return f"{st.stdout.strip()}\n\nrecent commits:\n{log.stdout.strip() or '(none)'}\n\nremotes:\n{remotes.stdout.strip() or '(none)'}"


@tool(
    "git_commit",
    "Stage changes and create a commit. `paths` defaults to all changes ('-A').",
    obj({"message": {"type": "string"}, "repo": {"type": "string"}, "paths": {"type": "array", "items": {"type": "string"}}}, ["message"]),
    "git",
)
def git_commit(ctx: ToolContext, a):
    repo = _repo(ctx, a.get("repo"))
    paths = a.get("paths") or []
    for p in paths:
        ctx.paths.resolve(p if not p.startswith("/") else p)  # confinement check
    add = _git(ctx, repo, "add", *(paths or ["-A"]))
    if add.returncode != 0:
        raise ToolError(_out(add))
    r = _git(ctx, repo, "commit", "-m", a["message"])
    if r.returncode != 0:
        return _out(r)
    sha = _git(ctx, repo, "rev-parse", "--short", "HEAD").stdout.strip()
    ctx.emit("git.commit", repo=ctx.paths.display(repo), sha=sha, message=a["message"][:200])
    return f"committed {sha}\n{r.stdout.strip()}"


@tool(
    "git_push",
    "Push commits to a remote (e.g. GitHub). Optionally set the remote URL first. Requires human approval.",
    obj({"repo": {"type": "string"}, "remote": {"type": "string"}, "branch": {"type": "string"},
         "remote_url": {"type": "string", "description": "if given, add/replace the remote with this URL"},
         "set_upstream": {"type": "boolean"}}),
    "git",
)
def git_push(ctx: ToolContext, a):
    repo = _repo(ctx, a.get("repo"))
    remote = a.get("remote") or "origin"
    branch = a.get("branch") or _git(ctx, repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "main"
    url = a.get("remote_url")
    target = url or _git(ctx, repo, "remote", "get-url", remote).stdout.strip() or "(unknown remote)"
    ctx.require_approval("git:push", f"git push {remote} {branch} → {target}", detail=f"repo: {ctx.paths.display(repo)}")
    if url:
        existing = _git(ctx, repo, "remote", "get-url", remote)
        r = _git(ctx, repo, "remote", "set-url" if existing.returncode == 0 else "add", remote, url)
        if r.returncode != 0:
            raise ToolError(_out(r))
    args = ["push"] + (["-u"] if a.get("set_upstream", True) else []) + [remote, branch]
    r = _git(ctx, repo, *args, timeout=300)
    ctx.emit("git.push", repo=ctx.paths.display(repo), remote=remote, branch=branch, ok=r.returncode == 0)
    return f"$ git {' '.join(shlex.quote(x) for x in args)}\n" + _out(r)
