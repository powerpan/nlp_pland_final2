"""The host-side git tools must not run programs the repository (which the agent can write) chooses: hooks,
fsmonitor, filter drivers, ssh commands … — and the shell policy must see pushes however `git` is spelled."""

from __future__ import annotations

import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from pland.sandbox import check_command
from pland.tools import load_builtin_tools
from pland.tools.registry import TOOLS, ToolContext, execute

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


class _Approve:
    def __init__(self):
        self.asked = []

    def require(self, category, summary, detail=""):
        self.asked.append(category)
        return SimpleNamespace(allowed=True, reason="approved")


@pytest.fixture()
def agent(rt, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "githome"))  # no developer global config (hooksPath, signing, …)
    (tmp_path / "githome").mkdir()
    load_builtin_tools()
    return rt.agent("default")


def ctx_of(agent, approvals=None) -> ToolContext:
    return ToolContext(runtime=agent.runtime, agent=agent, profile=agent.profile, settings=agent.settings,
                       session_id=agent.session_id, run_id="r", backend=agent.backend, paths=agent.paths,
                       hitl=agent.hitl, approvals=approvals or _Approve(), room_id=agent.room_id)


def call(agent, name, **args):
    return execute(TOOLS[name], ctx_of(agent), args)


def sh(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, check=True, capture_output=True,
                          text=True).stdout


def script(path, marker):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\ntouch '{marker}'\ncat\n")
    path.chmod(0o755)
    return path


def new_repo(agent, name="proj"):
    repo = agent.paths.roots[""] / name
    repo.mkdir()
    out = call(agent, "git_status", repo=name, init=True)
    assert not out.startswith("ERROR"), out
    (repo / "a.txt").write_text("a\n")
    return repo


def test_normal_status_and_commit_still_work(agent):
    repo = new_repo(agent)
    assert "?? a.txt" in call(agent, "git_status", repo="proj")
    out = call(agent, "git_commit", repo="proj", message="first")
    assert out.startswith("committed "), out
    assert "first" in call(agent, "git_status", repo="proj")
    sh(repo, "config", "user.name", "Someone")  # ordinary local settings are fine
    sh(repo, "config", "branch.main.description", "x")
    (repo / "b.txt").write_text("b\n")
    assert call(agent, "git_commit", repo="proj", message="second").startswith("committed ")


def test_pre_commit_hook_does_not_run(agent, tmp_path):
    repo = new_repo(agent)
    marker = tmp_path / "hook-ran"
    for hook in ("pre-commit", "commit-msg", "post-commit", "prepare-commit-msg"):
        script(repo / ".git" / "hooks" / hook, marker)
    out = call(agent, "git_commit", repo="proj", message="with hooks")
    assert out.startswith("committed "), out
    assert not marker.exists()


def test_hooks_path_in_repo_config_is_refused(agent, tmp_path):
    repo = new_repo(agent)
    script(repo / "hooks" / "pre-commit", tmp_path / "hook-ran")
    sh(repo, "config", "core.hooksPath", str(repo / "hooks"))
    out = call(agent, "git_commit", repo="proj", message="x")
    assert out.startswith("ERROR") and "core.hookspath" in out.lower()
    assert not (tmp_path / "hook-ran").exists()


def test_fsmonitor_program_is_refused_on_status(agent, tmp_path):
    repo = new_repo(agent)
    marker = tmp_path / "fsmonitor-ran"
    sh(repo, "config", "core.fsmonitor", str(script(tmp_path / "fsm.sh", marker)))
    out = call(agent, "git_status", repo="proj")
    assert out.startswith("ERROR") and "core.fsmonitor" in out and "--unset-all" in out
    assert not marker.exists()
    sh(repo, "config", "core.fsmonitor", "false")  # a boolean is fine (and is overridden to false anyway)
    assert not call(agent, "git_status", repo="proj").startswith("ERROR")


def test_clean_filter_driver_is_refused(agent, tmp_path):
    repo = new_repo(agent)
    marker = tmp_path / "filter-ran"
    sh(repo, "config", "filter.x.clean", str(script(tmp_path / "clean.sh", marker)))
    (repo / ".gitattributes").write_text("* filter=x\n")
    out = call(agent, "git_commit", repo="proj", message="x")
    assert out.startswith("ERROR") and "filter.x.clean" in out
    assert not marker.exists()
    assert sh(repo, "log", "--oneline", "--all") == ""  # nothing was staged or committed either


@pytest.mark.parametrize("key,value", [
    ("core.sshCommand", "touch /tmp/x; ssh"), ("core.pager", "less"), ("credential.helper", "!evil"),
    ("credential.https://github.com.helper", "evil"), ("include.path", "../../evil.cfg"),
    ("includeIf.gitdir:/.path", "evil.cfg"), ("gpg.program", "evil"), ("diff.x.textconv", "evil"),
    ("diff.external", "evil"), ("merge.x.driver", "evil"), ("remote.origin.receivepack", "evil"),
    ("url.ext::sh -c evil.insteadOf", "https://github.com/"), ("submodule.s.update", "!evil"),
    ("lfs.customtransfer.x.path", "evil"), ("core.worktree", "/"), ("http.sslVerify", "false"),
    ("uploadpack.packObjectsHook", "evil"), ("sequence.editor", "evil"), ("filter.lfs.clean", "evil %f"),
])
def test_program_running_settings_are_refused(agent, key, value):
    repo = new_repo(agent)
    sh(repo, "config", key, value)
    out = call(agent, "git_status", repo="proj")
    assert out.startswith("ERROR") and "Refusing to run git" in out, (key, out)


def test_standard_lfs_filter_and_worktree_config_are_checked(agent):
    repo = new_repo(agent)
    for k, v in {"filter.lfs.clean": "git-lfs clean -- %f", "filter.lfs.smudge": "git-lfs smudge -- %f",
                 "filter.lfs.process": "git-lfs filter-process", "filter.lfs.required": "true"}.items():
        sh(repo, "config", k, v)
    assert not call(agent, "git_status", repo="proj").startswith("ERROR")  # what `git lfs install --local` writes
    sh(repo, "config", "extensions.worktreeConfig", "true")
    sh(repo, "config", "--worktree", "core.sshCommand", "evil")
    assert "core.sshcommand" in call(agent, "git_status", repo="proj").lower()


def test_filter_in_a_submodule_is_refused(agent, tmp_path):
    repo = new_repo(agent)
    call(agent, "git_commit", repo="proj", message="base")
    sub = repo / "vendor"
    sub.mkdir()
    sh(sub, "init", "-q", "-b", "main")
    (sub / "f").write_text("f\n")
    sh(sub, "add", "f")
    sh(sub, "commit", "-qm", "f")
    marker = tmp_path / "sub-filter-ran"
    # `git add -A` turns the nested repository into a gitlink; git status/commit then run `git status` inside it.
    assert call(agent, "git_commit", repo="proj", message="add vendor").startswith("committed ")
    sh(sub, "config", "filter.y.clean", str(script(tmp_path / "clean.sh", marker)))
    (sub / ".gitattributes").write_text("* filter=y\n")
    os.utime(sub / "f", None)
    out = call(agent, "git_status", repo="proj")
    assert out.startswith("ERROR") and "filter.y.clean" in out and "proj/vendor" in out
    (repo / "c.txt").write_text("c\n")
    assert call(agent, "git_commit", repo="proj", message="c").startswith("ERROR")
    assert not marker.exists()


def test_push_to_local_repo_skips_both_sides_hooks(agent, tmp_path):
    repo = new_repo(agent)
    call(agent, "git_commit", repo="proj", message="first")
    bare = tmp_path / "remote.git"
    sh(tmp_path, "init", "-q", "--bare", str(bare))
    marker = tmp_path / "push-hook-ran"
    script(bare / "hooks" / "pre-receive", marker)
    script(bare / "hooks" / "post-receive", marker)
    script(repo / ".git" / "hooks" / "pre-push", marker)
    approvals = _Approve()
    out = execute(TOOLS["git_push"], ctx_of(agent, approvals), {"repo": "proj", "remote_url": str(bare), "branch": "main"})
    assert "exit_code: 0" in out, out
    assert approvals.asked == ["git:push"]
    assert out.splitlines()[0] == "$ git push -u origin main"
    assert not marker.exists()
    assert "first" in sh(bare, "log", "--oneline", "main")


def test_push_refuses_option_like_arguments_and_unsafe_target(agent, tmp_path):
    new_repo(agent)
    call(agent, "git_commit", repo="proj", message="first")
    approvals = _Approve()
    out = execute(TOOLS["git_push"], ctx_of(agent, approvals), {"repo": "proj", "remote": "--receive-pack=evil"})
    assert out.startswith("ERROR") and "must not start with '-'" in out
    bare = tmp_path / "remote.git"
    sh(tmp_path, "init", "-q", "--bare", str(bare))
    sh(bare, "config", "core.fsmonitor", "/bin/evil")
    out = execute(TOOLS["git_push"], ctx_of(agent, approvals), {"repo": "proj", "remote_url": str(bare), "branch": "main"})
    assert out.startswith("ERROR") and "core.fsmonitor" in out


@pytest.mark.parametrize("cmd", [
    "git push origin main", "git -c http.extraHeader=x push", "git -C ../repo push origin main",
    "git --git-dir=.git push", "git --git-dir .git --work-tree . push", "git --no-pager push",
    "git send-pack ../r.git main", "git http-push https://x/r.git main", "git remote-https origin https://x",
    "git remote-ext origin 'sh -c x'", "/usr/libexec/git-core/git-push origin", "sh -c 'git -C x push'",
    "git -c alias.p=push p origin", "git -c 'alias.p=!git push' p", "sub=push; git $sub", "cd a && git push",
    "git submodule foreach 'git push'", "echo $(git push)", "git status; git push",
])
def test_policy_flags_push_variants(cmd):
    assert "push to a remote repository" in (check_command(cmd).needs_approval or []), cmd


@pytest.mark.parametrize("cmd", [
    "git status", "git commit -m 'push the fix'", "git log --grep push", "git remote -v",
    "git remote add origin https://x", "git -C sub status", "git -c core.pager=cat log",
])
def test_policy_leaves_other_git_commands_alone(cmd):
    assert check_command(cmd).ok, cmd
