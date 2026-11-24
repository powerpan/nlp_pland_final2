"""Where a conversation works: a folder chosen for it, or the bot's private workspace.

One source of truth that the system prompt, the file tools, the
shell sandbox, uploads and the UI's file browser all read. The folder is stored with the conversation
(session meta "workspace"; for a group, room settings "workspace") — system state, not something the
model has to remember — so it survives context compaction, restarts and resumes.

A chosen folder becomes the agent's writable root instead of its private workspace; the Seatbelt and
Docker sandboxes confine commands to it exactly as they do to the private workspace. Folders that would
expose far more than a project are refused: `/`, the home folder or anything above it, system folders,
credential folders, and PlanD's own data folder (other bots' private state).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

SYSTEM_DIRS = ("/System", "/Library", "/usr", "/bin", "/sbin", "/etc", "/private/etc", "/dev", "/cores",
               "/Applications", "/opt/homebrew", "/proc", "/sys", "/boot", "/root", "/lib", "/lib64")  # and below
BROAD_DIRS = ("/Volumes", "/Users", "/home", "/tmp", "/private", "/private/tmp", "/private/var", "/var", "/opt", "/mnt",
              "/srv", "/media")  # the folder itself only: projects may live below them
CREDENTIAL_DIRS = (".ssh", ".aws", ".gnupg", ".config", ".kube", ".docker", "Library", ".local/share/keyrings")
INSTALL_ROOT = Path(__file__).resolve().parent.parent  # PlanD's own checkout (never a launch-folder default)


class WorkspaceError(ValueError):
    pass


def _home() -> Path:
    return Path(os.path.expanduser("~")).resolve()


def check_workspace(path: str | Path, *, pland_root: Path) -> Path:
    """Validate a folder a user picked for a conversation; returns it resolved or raises WorkspaceError."""
    raw = str(path).strip()
    if not raw:
        raise WorkspaceError("no folder given")
    p = Path(raw).expanduser()
    if not p.is_absolute():
        raise WorkspaceError("use an absolute path (e.g. /Users/you/projects/app)")
    p = p.resolve()
    if not p.is_dir():
        raise WorkspaceError(f"{p} is not an existing folder")
    home, root = _home(), pland_root.resolve()
    if p == Path("/") or p == home or p in home.parents or p in {Path(b).resolve() for b in BROAD_DIRS}:
        raise WorkspaceError(f"{p} is too broad; choose a project folder")
    for sysdir in SYSTEM_DIRS:
        s = Path(sysdir)
        if p == s or s in p.parents:
            raise WorkspaceError(f"{p} is a system folder")
    for cred in CREDENTIAL_DIRS:
        c = home / cred
        if p == c or c in p.parents:
            raise WorkspaceError(f"{p} holds credentials or app data; choose a project folder")
    if p == root or root in p.parents or p in root.parents:
        raise WorkspaceError(f"{p} is (or contains) PlanD's data folder {root}; use the bot's workspace instead")
    return p


def launch_folder_default(cwd: Path, *, pland_root: Path) -> tuple[Path | None, str]:
    """The folder `pland` was started from, if it makes a sensible workspace. Returns (folder or None, reason when None)."""
    cwd = cwd.resolve()
    if cwd == INSTALL_ROOT or INSTALL_ROOT in cwd.parents:
        return None, "the launch folder is PlanD's own installation"
    try:
        return check_workspace(cwd, pland_root=pland_root), ""
    except WorkspaceError as exc:
        return None, str(exc)


def chosen(meta: dict[str, Any] | None) -> str | None:
    """The folder stored for a conversation (session meta or room settings), if any."""
    value = str((meta or {}).get("workspace") or "").strip()
    return value or None


def resolve(default: Path, meta: dict[str, Any] | None) -> tuple[Path, str | None]:
    """(folder to work in, error). A stored folder that has since disappeared is an error rather than a silent
    switch to another folder, so files never land somewhere the user did not choose."""
    folder = chosen(meta)
    if folder is None:
        return default, None
    p = Path(folder)
    if not p.is_dir():
        return default, (f"The folder chosen for this conversation ({folder}) no longer exists. Choose another one "
                         "(/workspace in the CLI, the folder menu in the web UI) or go back to the bot's workspace.")
    return p.resolve(), None


def recent(runtime, limit: int = 10) -> list[str]:
    """Folders recently chosen for conversations and groups, newest first, that still exist."""
    from .store import loads

    seen: dict[str, float] = {}
    for prof in runtime.profiles.list():
        for row in prof.db.query("SELECT meta, updated FROM sessions WHERE meta LIKE '%\"workspace\"%' "
                                 "ORDER BY updated DESC LIMIT 50"):
            folder = chosen(loads(row["meta"], {}))
            if folder:
                seen[folder] = max(seen.get(folder, 0), row["updated"])
    for room in runtime.rooms.list():
        folder = chosen(room.get("settings"))
        if folder:
            seen[folder] = max(seen.get(folder, 0), room.get("updated") or 0)
    ordered = sorted(seen, key=lambda f: -seen[f])
    return [f for f in ordered if Path(f).is_dir()][:limit]
