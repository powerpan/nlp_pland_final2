"""Host execution backend with a filtered environment and timeout.

This backend is not an operating-system sandbox. Use it for trusted local work.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import SandboxConfig

_SECRET_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "COOKIE", "SESSION")
_ENV_KEEP = {"PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "USER", "LOGNAME", "SHELL", "TMPDIR", "TZ",
             "SSH_AUTH_SOCK", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"}


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    duration: float = 0.0

    def render(self, limit: int = 20000) -> str:
        out = self.stdout or ""
        err = self.stderr or ""
        parts = [f"exit_code: {self.exit_code}" + (" (timed out)" if self.timed_out else "")]
        if out:
            parts.append("stdout:\n" + _truncate(out, limit))
        if err:
            parts.append("stderr:\n" + _truncate(err, limit // 2))
        return "\n".join(parts)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-limit // 2 :]
    return f"{head}\n... [{len(text) - limit} chars truncated] ...\n{tail}"


def scrub_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {}
    for k, v in os.environ.items():
        if k in _ENV_KEEP or (k.startswith("LC_")):
            env[k] = v
        elif any(h in k.upper() for h in _SECRET_HINTS):
            continue
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.update(extra or {})
    return env


class Backend:
    name = "base"
    isolated = False  # True when an OS/container boundary contains the process

    def run(self, command: str, cwd: Path, *, timeout: float | None = None, env: dict[str, str] | None = None,
            mounts: dict[str, Path] | None = None) -> ExecResult:
        raise NotImplementedError

    def run_python(self, code: str, cwd: Path, *, timeout: float | None = None, mounts: dict[str, Path] | None = None) -> ExecResult:
        raise NotImplementedError


class LocalBackend(Backend):
    name = "local"
    isolated = False

    def __init__(self, cfg: SandboxConfig | None = None, python: str | None = None):
        self.cfg = cfg or SandboxConfig()
        self.python = python or sys.executable

    def _limits(self):  # pragma: no cover - runs in the child
        try:
            import resource

            cpu = int(self.cfg.command_timeout * 2) + 5
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
            fsize = 512 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except Exception:
            pass

    def _exec(self, argv: list[str], cwd: Path, timeout: float, env: dict[str, str], stdin: str | None = None) -> ExecResult:
        start = time.time()
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=True,
            preexec_fn=self._limits if os.name == "posix" else None,
        )
        try:
            out, err = proc.communicate(input=stdin, timeout=timeout)
            return ExecResult(proc.returncode, out, err, False, time.time() - start)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            out, err = proc.communicate()
            return ExecResult(-9, out or "", (err or "") + f"\n[killed after {timeout:.0f}s timeout]", True, time.time() - start)

    def run(self, command, cwd, *, timeout=None, env=None, mounts=None) -> ExecResult:
        cwd.mkdir(parents=True, exist_ok=True)
        return self._exec(["/bin/bash", "-c", command], cwd, timeout or self.cfg.command_timeout, scrub_env(env))

    def run_python(self, code, cwd, *, timeout=None, mounts=None) -> ExecResult:
        cwd.mkdir(parents=True, exist_ok=True)
        return self._exec([self.python, "-I", "-"], cwd, timeout or self.cfg.command_timeout, scrub_env(), stdin=code)


def make_backend(cfg: SandboxConfig, profile_name: str, workspace: Path) -> Backend:
    if cfg.backend != "local":
        raise ValueError("this stage supports only the local backend")
    return LocalBackend(cfg)


def quote(s: str) -> str:
    return shlex.quote(s)
