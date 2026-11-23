"""Execution backends for shell commands and Python code.

* `LocalBackend` runs on the host inside the profile's workspace with a scrubbed environment,
  a wall-clock timeout, process-group kill and POSIX resource limits. It is NOT an OS sandbox: a
  process can still read files the OS user can read. Dangerous commands therefore go through the
  approval layer first.
* `DockerBackend` runs inside one long-lived, hardened container per profile (all capabilities
  dropped, no-new-privileges, pids/memory/cpu limits, optional `--network none`), with only that
  profile's workspace (and, in a room, the room's shared folder) bind-mounted. The container is the
  security boundary here.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import signal
import subprocess
import sys
import threading
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
    # Put the platform's own Python (3.10+, with pytest) first so `python3`/`pytest` work out of the box.
    py_bin = str(Path(sys.executable).parent)
    env["PATH"] = py_bin + os.pathsep + env["PATH"]
    env.pop("VIRTUAL_ENV", None)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.update(extra or {})
    return env


class Backend:
    name = "base"
    isolated = False  # True when an OS/container boundary contains the process

    def run(self, command: str, cwd: Path, *, timeout: float | None = None, env: dict[str, str] | None = None,
            mounts: dict[str, Path] | None = None, cancel=None) -> ExecResult:
        raise NotImplementedError

    def run_python(self, code: str, cwd: Path, *, timeout: float | None = None, mounts: dict[str, Path] | None = None,
                   cancel=None) -> ExecResult:
        raise NotImplementedError


SANDBOX_EXEC = "/usr/bin/sandbox-exec"


def _sb_quote(path: Path | str) -> str:
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def seatbelt_profile(writable: list[Path], readable: list[Path], denied: list[Path]) -> str:
    """macOS Seatbelt policy for one command: everything outside `denied` behaves normally (system
    libraries, toolchains, network, temp dirs); inside `denied` (all user homes and PLAND_HOME) file
    contents can be neither read nor written, except the agent's own writable roots and the read-only
    toolchain paths. Metadata (stat) stays allowed so git/venv can walk parent directories."""
    lines = ["(version 1)", "(allow default)"]
    lines.append("(deny file-read* file-write* " + " ".join(f"(subpath {_sb_quote(p)})" for p in denied) + ")")
    lines.append("(allow file-read-metadata)")
    if readable:
        lines.append("(allow file-read* " + " ".join(f"(subpath {_sb_quote(p)})" for p in readable) + ")")
    lines.append("(allow file-read* file-write* " + " ".join(f"(subpath {_sb_quote(p)})" for p in writable) + ")")
    return "\n".join(lines) + "\n"


class LocalBackend(Backend):
    name = "local"
    isolated = False

    def __init__(self, cfg: SandboxConfig | None = None, python: str | None = None, workspace: Path | None = None,
                 deny_roots: list[Path] | None = None, home_dir: Path | None = None):
        self.cfg = cfg or SandboxConfig()
        self.python = python or sys.executable
        self.workspace = workspace.resolve() if workspace else None
        # The private HOME stays in the bot's own folder even when a conversation works in a user's folder,
        # so tool caches and dotfiles never land in the user's project.
        self.home_dir = home_dir.resolve() if home_dir else (self.workspace / ".home" if self.workspace else None)
        self.seatbelt = (self.cfg.os_sandbox == "auto" and sys.platform == "darwin" and os.path.exists(SANDBOX_EXEC)
                         and self.workspace is not None)
        if self.seatbelt:
            self.name = "local+seatbelt"
            home = Path(os.path.expanduser("~")).resolve()
            denied = {Path("/Users"), home, *(p.resolve() for p in (deny_roots or []))}
            self._denied = sorted(denied)
            # read-only: the platform's Python (venv + base install) so `python3`, pytest, pip work
            self._readable = sorted({Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(),
                                     Path(sys.executable).resolve().parent})

    def _wrap(self, argv: list[str], cwd: Path, mounts: dict[str, Path] | None, env: dict[str, str]) -> list[str]:
        if not self.seatbelt:
            return argv
        home = self.home_dir
        home.mkdir(parents=True, exist_ok=True)
        writable = [self.workspace] + [m.resolve() for m in (mounts or {}).values()]
        if not any(home == w or w in home.parents for w in writable):
            writable.append(home)
        if not any(cwd.resolve() == w or w in cwd.resolve().parents for w in writable):
            writable.append(cwd.resolve())
        env["HOME"] = str(home)  # the real home is off limits; tools get a private one
        env.setdefault("GIT_AUTHOR_NAME", "pland-agent")
        env.setdefault("GIT_AUTHOR_EMAIL", "agent@pland.local")
        env.setdefault("GIT_COMMITTER_NAME", env["GIT_AUTHOR_NAME"])
        env.setdefault("GIT_COMMITTER_EMAIL", env["GIT_AUTHOR_EMAIL"])
        return [SANDBOX_EXEC, "-p", seatbelt_profile(writable, self._readable, self._denied)] + argv

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

    def _exec(self, argv: list[str], cwd: Path, timeout: float, env: dict[str, str], stdin: str | None = None,
              cancel=None) -> ExecResult:
        """Run in a new session/process group. When the command returns, whatever it left running in the
        background (`cmd &`, nohup) is killed with the group — processes belong to the run that started them.
        `cancel()` is polled once a second so a stopped run does not wait for a long command to finish."""
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
        deadline = start + timeout
        pending_input = stdin
        while True:
            try:
                out, err = proc.communicate(input=pending_input, timeout=min(1.0, max(0.01, deadline - time.time())))
                self._kill_group(proc)  # reap background leftovers
                return ExecResult(proc.returncode, out, err, False, time.time() - start)
            except subprocess.TimeoutExpired:
                pending_input = None  # stdin was already written on the first call
                if proc.poll() is not None:
                    # The command itself has exited but a background child still holds the output pipe open:
                    # stop the leftovers now instead of waiting for them.
                    code = proc.returncode
                    self._kill_group(proc)
                    out, err = proc.communicate()
                    return ExecResult(code, out, err, False, time.time() - start)
                stopped = cancel is not None and cancel()
                if time.time() < deadline and not stopped:
                    continue
                self._kill_group(proc)
                out, err = proc.communicate()
                why = "run cancelled" if stopped else f"killed after {timeout:.0f}s timeout"
                return ExecResult(-9, out or "", (err or "") + f"\n[{why}]", True, time.time() - start)

    @staticmethod
    def _kill_group(proc: subprocess.Popen) -> None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            if proc.poll() is None:
                proc.kill()

    def run(self, command, cwd, *, timeout=None, env=None, mounts=None, cancel=None) -> ExecResult:
        cwd.mkdir(parents=True, exist_ok=True)
        e = scrub_env(env)
        argv = self._wrap(["/bin/bash", "-c", command], cwd, mounts, e)
        return self._exec(argv, cwd, timeout or self.cfg.command_timeout, e, cancel=cancel)

    def run_python(self, code, cwd, *, timeout=None, mounts=None, cancel=None) -> ExecResult:
        cwd.mkdir(parents=True, exist_ok=True)
        e = scrub_env()
        argv = self._wrap([self.python, "-I", "-"], cwd, mounts, e)
        return self._exec(argv, cwd, timeout or self.cfg.command_timeout, e, stdin=code, cancel=cancel)


class DockerBackend(Backend):
    name = "docker"
    isolated = True

    def __init__(self, cfg: SandboxConfig, profile_name: str, workspace: Path):
        self.cfg = cfg
        self.profile_name = profile_name
        self.workspace = workspace.resolve()
        self._lock = threading.Lock()
        self._containers: dict[str, str] = {}

    @staticmethod
    def available() -> bool:
        try:
            r = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True, timeout=15)
            return r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    _image_lock = threading.Lock()
    _image_ready: dict[str, str] = {}

    def _image(self) -> str:
        """Ensure the sandbox image exists: build pland-sandbox from docker/sandbox.Dockerfile once (git,
        pytest, curl...), falling back to python:3.11-slim if building is impossible."""
        want = self.cfg.docker_image
        with DockerBackend._image_lock:
            if want in DockerBackend._image_ready:
                return DockerBackend._image_ready[want]
            have = subprocess.run(["docker", "image", "inspect", want], capture_output=True, text=True).returncode == 0
            if not have and want.startswith("pland-sandbox"):
                dockerfile = Path(__file__).resolve().parents[2] / "docker" / "sandbox.Dockerfile"
                if dockerfile.is_file():
                    r = subprocess.run(["docker", "build", "-t", want, "-f", str(dockerfile), str(dockerfile.parent)],
                                       capture_output=True, text=True, timeout=900)
                    have = r.returncode == 0
            DockerBackend._image_ready[want] = want if have else "python:3.11-slim"
            return DockerBackend._image_ready[want]

    def _container_for(self, mounts: dict[str, Path] | None) -> str:
        key = "|".join(f"{k}={v}" for k, v in sorted((mounts or {}).items()))
        with self._lock:
            name = self._containers.get(key)
            if name and self._alive(name):
                return name
            # one container per (bot, folder, mounts): conversations in different folders never share one
            ident = f"{self.workspace}|{key}"
            suffix = int(hashlib.sha1(ident.encode()).hexdigest()[:6], 16)
            name = f"pland-{self.profile_name}-{suffix}"
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True)
            argv = [
                "docker", "run", "-d", "--name", name,
                "--label", "pland=1",
                "--cap-drop", "ALL",
                "--cap-add", "CHOWN", "--cap-add", "DAC_OVERRIDE", "--cap-add", "FOWNER",
                "--security-opt", "no-new-privileges",
                "--pids-limit", "256",
                "--memory", self.cfg.docker_memory,
                "--cpus", self.cfg.docker_cpus,
                "--network", self.cfg.docker_network,
                "--tmpfs", "/tmp:rw,nosuid,size=512m",
                "-v", f"{self.workspace}:/workspace",
                "-w", "/workspace",
            ]
            for alias, path in (mounts or {}).items():
                # mounted beside the workspace; ./shared inside the workspace is a symlink to it (see
                # tools.code._link_room_shared) — a nested mount point would leave a root-owned dir on the host
                argv += ["-v", f"{path.resolve()}:/{alias}"]
            argv += [self._image(), "sleep", "infinity"]
            r = subprocess.run(argv, capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                raise RuntimeError(f"failed to start sandbox container: {r.stderr.strip()[:500]}")
            self._containers[key] = name
            return name

    @staticmethod
    def _alive(name: str) -> bool:
        r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", name], capture_output=True, text=True)
        return r.returncode == 0 and r.stdout.strip() == "true"

    def _container_cwd(self, cwd: Path, mounts: dict[str, Path] | None) -> str:
        cwd = cwd.resolve()
        if cwd == self.workspace or self.workspace in cwd.parents:
            return "/workspace/" + cwd.relative_to(self.workspace).as_posix()
        for alias, path in (mounts or {}).items():
            path = path.resolve()
            if cwd == path or path in cwd.parents:
                return f"/{alias}/" + cwd.relative_to(path).as_posix()
        return "/workspace"

    def _exec(self, argv: list[str], timeout: float, stdin: str | None = None) -> ExecResult:
        start = time.time()
        try:
            r = subprocess.run(argv, input=stdin, capture_output=True, text=True, errors="replace", timeout=timeout)
            return ExecResult(r.returncode, r.stdout, r.stderr, False, time.time() - start)
        except subprocess.TimeoutExpired as exc:
            return ExecResult(-9, (exc.stdout or "") if isinstance(exc.stdout, str) else "",
                              f"[killed after {timeout:.0f}s timeout]", True, time.time() - start)

    def run(self, command, cwd, *, timeout=None, env=None, mounts=None, cancel=None) -> ExecResult:
        name = self._container_for(mounts)
        argv = ["docker", "exec", "-w", self._container_cwd(cwd, mounts)]
        for k, v in (env or {}).items():
            argv += ["-e", f"{k}={v}"]
        argv += [name, "bash", "-c", command]
        return self._exec(argv, timeout or self.cfg.command_timeout)

    def run_python(self, code, cwd, *, timeout=None, mounts=None, cancel=None) -> ExecResult:
        name = self._container_for(mounts)
        argv = ["docker", "exec", "-i", "-w", self._container_cwd(cwd, mounts), name, "python", "-"]
        return self._exec(argv, timeout or self.cfg.command_timeout, stdin=code)

    def shutdown(self) -> None:
        with self._lock:
            for name in self._containers.values():
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True)
            self._containers.clear()


def make_backend(cfg: SandboxConfig, profile_name: str, workspace: Path, deny_roots: list[Path] | None = None,
                 home_dir: Path | None = None) -> Backend:
    if cfg.backend == "docker":
        return DockerBackend(cfg, profile_name, workspace)
    if cfg.backend != "local":
        raise ValueError(f"unknown sandbox backend {cfg.backend!r} (use local or docker)")
    return LocalBackend(cfg, workspace=workspace, deny_roots=deny_roots, home_dir=home_dir)


def quote(s: str) -> str:
    return shlex.quote(s)
