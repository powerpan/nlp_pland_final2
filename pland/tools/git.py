"""Version control: real git commits and pushes inside the agent's workspace.

Git always runs on the host (even with the docker backend) so the user's configured credential
helper (e.g. `gh auth`) can authenticate pushes; pushing is outward-facing and always needs
human approval.

Because git runs outside the sandbox while the agent can write anything inside the repository (including
`.git/`), nothing the repository controls may make git run a program:

- every invocation passes `-c` overrides that switch off hooks (`core.hooksPath=/dev/null`), the fsmonitor hook
  and the `ext::` transport. Repository hooks therefore never run for agent commits, statuses or pushes — on
  purpose, and that includes hooks a tool such as Git LFS or pre-commit installed;
- before running, the repository-scoped config (`.git/config`, `config.worktree`) of the repository and of every
  submodule git would descend into is read (reading config executes nothing) and checked against an allow-list of
  settings that cannot start programs. Anything else (`core.sshCommand`, `filter.*`, `credential.*`, `gpg.*`,
  `include.*`, …) is refused with a message naming the key. The user's global and system config stay in effect,
  so their credential helper, signing and LFS filters keep working.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..sandbox.backends import scrub_env
from .registry import ToolContext, ToolError, obj, tool

# Passed to every git process (and inherited by the git processes it starts for submodules).
SAFE_OVERRIDES = (
    "-c", "core.hooksPath=/dev/null",  # hooks never run: an agent can write .git/hooks/*
    "-c", "core.fsmonitor=false",      # core.fsmonitor may name a program
    "-c", "protocol.ext.allow=never",  # ext:: URLs run arbitrary commands
)
# For pushes to a repository on this machine: git starts receive-pack in the *target* repository, whose hooks
# (pre-receive, post-update, …) would otherwise run; command-line overrides are not passed across that boundary.
SAFE_LOCAL_RECEIVE_PACK = "git -c core.hooksPath=/dev/null -c core.fsmonitor=false receive-pack"

_ANY = "*"
# Repository-scoped settings git may honour without starting a program. Keys are as `git config --list` prints
# them: section and final name lower-case. Map: section -> allowed names for `section.name` (2 parts) and for
# `section.<subsection>.name` (3 parts).
_ALLOWED_2: dict[str, set[str] | str] = {
    "core": {
        "repositoryformatversion", "filemode", "bare", "logallrefupdates", "ignorecase", "precomposeunicode",
        "symlinks", "autocrlf", "eol", "safecrlf", "checkroundtripencoding", "quotepath", "compression",
        "loosecompression", "bigfilethreshold", "abbrev", "longpaths", "checkstat", "trustctime",
        "sharedrepository", "splitindex", "untrackedcache", "preloadindex", "commitgraph", "multipackindex",
        "whitespace", "warnambiguousrefs", "hidedotfiles", "protectntfs", "protecthfs", "packedgitlimit",
        "packedgitwindowsize", "deltabasecachelimit", "fsync", "fsyncmethod", "fsyncobjectfiles",
        "filesreflocktimeout", "packedrefstimeout", "notesref", "commentchar", "commentstring", "excludesfile",
        "attributesfile", "sparsecheckout", "sparsecheckoutcone", "fsmonitorhookversion", "fscache",
        "restrictinheritedhandles", "fsmonitor",  # fsmonitor: only a boolean, see _check_entry
    },
    "user": {"name", "email", "useconfigonly"},
    "author": {"name", "email"},
    "committer": {"name", "email"},
    "init": {"defaultbranch"},
    "branch": _ANY, "remote": {"pushdefault"},
    "submodule": {"recurse", "active", "fetchjobs", "alternatelocation", "alternateerrorstrategy", "propagatebranches"},
    "commit": {"cleanup", "status", "verbose"},
    "tag": {"sort"},
    "protocol": {"version"},
    "http": {"postbuffer", "lowspeedlimit", "lowspeedtime", "version"},
    "diff": {"renames", "renamelimit", "algorithm", "mnemonicprefix", "noprefix", "relative", "statgraphwidth",
             "context", "interhunkcontext", "indentheuristic", "colormoved", "colormovedws", "ignoresubmodules",
             "submodule", "wserrorhighlight", "suppressblankempty", "orderfile", "dirstat", "autorefreshindex"},
    "merge": {"ff", "conflictstyle", "defaulttoupstream", "log", "renames", "renamelimit", "renormalize", "stat",
              "autostash", "verbosity", "directoryrenames", "branchdesc"},
    # Sections with no setting that starts a program (aliases are only expanded for commands PlanD never runs).
    **{s: _ANY for s in ("extensions", "color", "column", "status", "log", "pull", "push", "fetch", "advice", "i18n",
                         "gc", "pack", "index", "rerere", "rebase", "blame", "grep", "maintenance", "feature",
                         "transfer", "receive", "worktree", "checkout", "am", "apply", "format", "alias", "lfs",
                         "help", "clone", "reset", "stash", "versionsort", "splitindex", "repack")},
}
_ALLOWED_3: dict[str, set[str] | str] = {
    "branch": _ANY,
    "remote": {"url", "pushurl", "fetch", "push", "mirror", "tagopt", "prune", "prunetags", "skipdefaultupdate",
               "skipfetchall", "promisor", "partialclonefilter", "followremotehead", "serveroption"},
    "submodule": {"url", "active", "branch", "ignore", "fetchrecursesubmodules", "shallow"},  # not `update` (!cmd)
    "color": _ANY, "alias": _ANY,
    "lfs": _ANY,  # minus the program-running keys in _check_entry
}
# What `git lfs install --local` writes: git-lfs itself, not a repository-chosen program.
_LFS_FILTER = {"filter.lfs.clean": "git-lfs clean -- %f", "filter.lfs.smudge": "git-lfs smudge -- %f",
               "filter.lfs.process": "git-lfs filter-process", "filter.lfs.required": "true"}
_RUNS_PROGRAM = re.compile(
    r"^(core\.(hookspath|sshcommand|pager|editor|askpass|gitproxy|alternaterefscommand|fsmonitor)|credential\..*"
    r"|filter\..*|diff\.(external|.*\.(textconv|command))|merge\..*\.driver|gpg\..*|include\.path|includeif\..*"
    r"|sequence\.editor|pager\..*|interactive\.difffilter|uploadpack\.packobjectshook|remote\..*\.(uploadpack|receivepack)"
    r"|url\..*|submodule\..*\.update|trailer\..*|(diff|merge)tool\..*|sendemail\..*|ssh\.variant)$")
_REPO_SCOPES = {"local", "worktree"}
_MAX_REPOS = 64


def _repo(ctx: ToolContext, raw: str | None):
    path = ctx.paths.resolve(raw or ".")
    if not path.is_dir():
        raise ToolError(f"{raw!r} is not a directory")
    return path


def _env(ctx: ToolContext) -> dict[str, str]:
    env = scrub_env()
    env.setdefault("GIT_AUTHOR_NAME", f"pland-{ctx.profile.name}")
    env.setdefault("GIT_AUTHOR_EMAIL", f"{ctx.profile.name}@pland.local")
    env.setdefault("GIT_COMMITTER_NAME", env["GIT_AUTHOR_NAME"])
    env.setdefault("GIT_COMMITTER_EMAIL", env["GIT_AUTHOR_EMAIL"])
    return env


def _git(ctx: ToolContext, cwd, *args: str, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *SAFE_OVERRIDES, *args], cwd=str(cwd), env=_env(ctx), capture_output=True,
                          text=True, timeout=timeout)


def _out(r: subprocess.CompletedProcess) -> str:
    text = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
    return f"exit_code: {r.returncode}\n{text.strip()}"


# --------------------------------------------------------------------------- repository config check

def _unsafe_reason(key: str, value: str) -> str | None:
    """Why a repository-scoped `key = value` is refused, or None when git cannot run a program because of it."""
    low = key.lower()  # git prints section and name lower-case but keeps the subsection's case
    section, _, rest = low.partition(".")
    name = rest.rsplit(".", 1)[-1]
    if low in _LFS_FILTER:
        return None if value.strip() == _LFS_FILTER[low] else "can run a program (clean/smudge filter driver)"
    if low == "core.fsmonitor":
        return None if value.strip().lower() in {"", "false", "true", "no", "yes", "off", "on", "0", "1"} else \
            "can run a program (fsmonitor hook)"
    if section == "lfs" and (name in {"path", "args", "clean", "smudge", "process", "standalonetransferagent"}
                             or ".customtransfer." in f".{rest}" or ".extension." in f".{rest}"):
        return "can run a program (Git LFS custom transfer agent or extension)"
    if _RUNS_PROGRAM.match(low):
        if section in {"include", "includeif"}:
            return "pulls in another config file PlanD would have to trust"
        return "can run a program"
    if section == "core" and name == "worktree":
        return "points git at files outside this repository"
    allowed = (_ALLOWED_2 if "." not in rest else _ALLOWED_3).get(section)
    if allowed == _ANY or (isinstance(allowed, set) and name in allowed):
        return None
    return "is not on PlanD's list of settings known not to run programs"


def _unsafe_config(ctx: ToolContext, cwd: Path) -> tuple[str, str] | None:
    """The first repository-scoped config entry that could make git run a program, as (key, reason)."""
    r = _git(ctx, cwd, "config", "--list", "--show-scope", "-z")
    if r.returncode != 0:
        raise ToolError("could not read the repository's git config, so git was not run:\n" + _out(r))
    # `--show-scope -z` prints scope NUL key LF value NUL; pair the fields up.
    fields = r.stdout.split("\0")
    for scope, kv in zip(fields[0::2], fields[1::2]):
        if scope not in _REPO_SCOPES:
            continue
        key, _, value = kv.partition("\n")
        reason = _unsafe_reason(key, value)
        if reason:
            return key, reason
    return None


def _nested_repos(ctx: ToolContext, cwd: Path) -> list[Path]:
    """Checked-out submodules (gitlinks with a .git) of the repository containing `cwd`: git starts processes
    inside them (e.g. `status` and `add -A` run `git status` there), honouring their own config."""
    top = _git(ctx, cwd, "rev-parse", "--show-toplevel")
    if top.returncode != 0 or not top.stdout.strip():
        return []
    root = Path(top.stdout.strip())
    ls = _git(ctx, root, "ls-files", "--stage", "-z")
    found = []
    for entry in ls.stdout.split("\0"):
        meta, _, path = entry.partition("\t")
        if meta.startswith("160000 ") and path and (root / path / ".git").exists():
            found.append(root / path)
    return found


def _check_repo(ctx: ToolContext, cwd: Path) -> None:
    """Refuse to run git in `cwd` when its repository (or a submodule git would enter) has config that could make
    git start a program on the host."""
    pending, seen = [cwd], set()
    while pending:
        here = pending.pop()
        real = here.resolve()
        if real in seen:
            continue
        seen.add(real)
        if len(seen) > _MAX_REPOS:
            raise ToolError(f"more than {_MAX_REPOS} nested git repositories; PlanD's git tools refuse to run here")
        bad = _unsafe_config(ctx, here)
        if bad:
            key, reason = bad
            where = ctx.paths.display(here)
            raise ToolError(
                f"Refusing to run git: the repository config of '{where}' sets `{key}`, which {reason}. PlanD's git "
                f"tools run on the host outside the sandbox, so repository settings that can start programs are not "
                f"allowed. Remove it (`git config --local --unset-all {shlex.quote(key)}`, or edit .git/config) — "
                f"if the user needs it, they can set it in their global git config instead.")
        pending.extend(_nested_repos(ctx, here))


# --------------------------------------------------------------------------- push targets

def _local_path(url: str, base: Path) -> Path | None:
    """The directory a push URL names when it is a repository on this machine (plain path or file://), else None."""
    url = url.strip()
    if url.startswith("file:"):
        return Path(unquote(urlparse(url).path or url[len("file:"):]))
    if "::" in url or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", url):
        return None  # transport helper or network URL
    if ":" in url.split("/", 1)[0]:
        return None  # scp-like host:path
    p = Path(url).expanduser()
    return p if p.is_absolute() else base / p


def _no_option(value: str | None, what: str) -> None:
    if value and value.lstrip().startswith("-"):
        raise ToolError(f"{what} must not start with '-' (it would be read as a git option)")


@tool(
    "git_status",
    "Show `git status --short --branch` and the latest commits of a repository in your workspace. Initialise with "
    "init=true. Git runs on the host with repository hooks disabled; a repository whose own config could make git "
    "run programs (filters, fsmonitor, sshCommand, credential helpers, …) is refused.",
    obj({"repo": {"type": "string", "description": "repository directory (default: workspace root)"}, "init": {"type": "boolean"}}),
    "git",
)
def git_status(ctx: ToolContext, a):
    repo = _repo(ctx, a.get("repo"))
    if a.get("init") and not (repo / ".git").exists():
        r = _git(ctx, repo, "init", "-b", "main")
        if r.returncode != 0:
            raise ToolError(_out(r))
    _check_repo(ctx, repo)
    st = _git(ctx, repo, "status", "--short", "--branch")
    if st.returncode != 0:
        return _out(st)
    log = _git(ctx, repo, "log", "--oneline", "-5")
    remotes = _git(ctx, repo, "remote", "-v")
    return f"{st.stdout.strip()}\n\nrecent commits:\n{log.stdout.strip() or '(none)'}\n\nremotes:\n{remotes.stdout.strip() or '(none)'}"


@tool(
    "git_commit",
    "Stage changes and create a commit. `paths` defaults to all changes ('-A'). Repository hooks (pre-commit, "
    "commit-msg, …) do not run for these commits.",
    obj({"message": {"type": "string"}, "repo": {"type": "string"}, "paths": {"type": "array", "items": {"type": "string"}}}, ["message"]),
    "git",
)
def git_commit(ctx: ToolContext, a):
    repo = _repo(ctx, a.get("repo"))
    paths = a.get("paths") or []
    for p in paths:
        ctx.paths.resolve(p)  # confinement check: absolute paths outside the workspace roots are refused
    _check_repo(ctx, repo)
    add = _git(ctx, repo, "add", *(["--", *paths] if paths else ["-A"]))  # "--": paths are never read as options
    if add.returncode != 0:
        raise ToolError(_out(add))
    _check_repo(ctx, repo)  # `add -A` may have turned a nested repository into a submodule that commit will enter
    r = _git(ctx, repo, "commit", "-m", a["message"])
    if r.returncode != 0:
        return _out(r)
    sha = _git(ctx, repo, "rev-parse", "--short", "HEAD").stdout.strip()
    ctx.emit("git.commit", repo=ctx.paths.display(repo), sha=sha, message=a["message"][:200])
    return f"committed {sha}\n{r.stdout.strip()}"


@tool(
    "git_push",
    "Push commits to a remote (e.g. GitHub). Optionally set the remote URL first. Requires human approval. "
    "Repository hooks (pre-push, and the receiving repository's hooks for a push to a local path) do not run.",
    obj({"repo": {"type": "string"}, "remote": {"type": "string"}, "branch": {"type": "string"},
         "remote_url": {"type": "string", "description": "if given, add/replace the remote with this URL"},
         "set_upstream": {"type": "boolean"}}),
    "git",
)
def git_push(ctx: ToolContext, a):
    repo = _repo(ctx, a.get("repo"))
    for field_ in ("remote", "branch", "remote_url"):
        _no_option(a.get(field_), field_)
    _check_repo(ctx, repo)
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
    push_urls = _git(ctx, repo, "remote", "get-url", "--push", "--all", remote)
    urls = push_urls.stdout.split() if push_urls.returncode == 0 else [remote]  # a path or URL given as `remote`
    local = [p for p in (_local_path(u, repo) for u in urls) if p is not None]
    for target_repo in local:  # receive-pack runs in that repository and honours its config
        if target_repo.is_dir():
            _check_repo(ctx, target_repo)
    args = ["push"] + (["-u"] if a.get("set_upstream", True) else []) + [remote, branch]
    extra = [f"--receive-pack={SAFE_LOCAL_RECEIVE_PACK}"] if local else []
    r = _git(ctx, repo, args[0], *extra, *args[1:], timeout=300)
    ctx.emit("git.push", repo=ctx.paths.display(repo), remote=remote, branch=branch, ok=r.returncode == 0)
    return f"$ git {' '.join(shlex.quote(x) for x in args)}\n" + _out(r)
