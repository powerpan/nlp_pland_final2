"""File browsing and uploads for the web UI: a profile's workspace and a room's shared folder.

Users look at what the agents produced. Every
path is relative to one root folder and goes through `PathPolicy({"": root})`, which resolves
symlinks and rejects anything outside the root and credential/state files (.env, .ssh, state.db, …).
Absolute paths are refused outright. Only regular files are read, at most `MAX_PREVIEW` bytes, and
only when they are UTF-8 text. Uploads (the composer's + button) land in `uploads/` of the same folder.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..sandbox import PathPolicy, PolicyError
from ..tools.files import UNSUPPORTED_DOCS

SKIP_NAMES = {".git", ".venv", "venv", "node_modules", "__pycache__", ".home", ".pytest_cache", ".mypy_cache",
              ".ruff_cache", ".DS_Store"}
MAX_ENTRIES = 1000       # listed per directory (the rest is reported as truncated)
MAX_SCAN = 5000          # directory entries looked at before giving up
MAX_PREVIEW = 200_000    # bytes of a file returned for preview
_DRIVE = re.compile(r"^[A-Za-z]:")
MAX_UPLOAD = 20 * 1024 * 1024  # bytes per uploaded file
UPLOAD_DIR = "uploads"
_UNSAFE_NAME = re.compile(r"[^\w.\- ()\[\]@+,]")


def _clean(rel: str | None) -> str:
    rel = (rel or "").strip().replace("\\", "/")
    if rel.startswith(("/", "~")) or _DRIVE.match(rel):
        raise HTTPException(403, "absolute paths are not allowed; paths are relative to the folder")
    return rel.strip("/") if rel not in ("", ".") else ""


def _resolve(policy: PathPolicy, rel: str) -> Path:
    try:
        return policy.resolve(rel or ".")
    except PolicyError as exc:
        if "outside" in str(exc):
            raise HTTPException(403, "that path is outside this folder") from None
        raise HTTPException(403, str(exc)) from None


def _relative(path: Path, root: Path) -> str:
    rel = path.relative_to(root).as_posix()
    return "" if rel == "." else rel


def list_dir(root: Path, rel: str | None = None) -> dict[str, Any]:
    """Entries of one directory under `root` (directories first), without tooling folders, secret
    files and symlinks that lead outside the root."""
    rel = _clean(rel)
    root_r = root.resolve()
    if not rel and not root_r.is_dir():
        return {"path": "", "parent": None, "entries": [], "truncated": False}
    policy = PathPolicy({"": root_r})
    target = _resolve(policy, rel)
    if not target.exists():
        raise HTTPException(404, f"no such folder: {rel or '.'}")
    if not target.is_dir():
        raise HTTPException(400, f"{rel} is a file, not a folder")
    base = _relative(target, root_r)
    entries: list[dict[str, Any]] = []
    scanned = 0
    for child in target.iterdir():
        scanned += 1
        if scanned > MAX_SCAN:
            break
        if child.name in SKIP_NAMES:
            continue
        child_rel = f"{base}/{child.name}" if base else child.name
        try:
            resolved = policy.resolve(child_rel)  # follows symlinks; refuses secrets and escapes
            st = resolved.stat()
        except (PolicyError, OSError):
            continue
        is_dir = stat.S_ISDIR(st.st_mode)
        if not is_dir and not stat.S_ISREG(st.st_mode):
            continue  # sockets, FIFOs, devices
        entries.append({"name": child.name, "path": child_rel, "is_dir": is_dir,
                        "size": None if is_dir else st.st_size, "mtime": st.st_mtime})
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    return {
        "path": base,
        "parent": None if not base else base.rpartition("/")[0],
        "entries": entries[:MAX_ENTRIES],
        "truncated": len(entries) > MAX_ENTRIES or scanned > MAX_SCAN,
    }


def read_text(root: Path, rel: str | None) -> dict[str, Any]:
    """The text of one regular file under `root` (first `MAX_PREVIEW` bytes). Binary files are
    refused with 415."""
    rel = _clean(rel)
    if not rel:
        raise HTTPException(400, "pass the path of a file")
    root_r = root.resolve()
    target = _resolve(PathPolicy({"": root_r}), rel)
    try:
        st = target.stat()
    except OSError:
        raise HTTPException(404, f"no such file: {rel}") from None
    if stat.S_ISDIR(st.st_mode):
        raise HTTPException(400, f"{rel} is a folder")
    if not stat.S_ISREG(st.st_mode):
        raise HTTPException(400, f"{rel} is not a regular file")
    with open(target, "rb") as fh:
        data = fh.read(MAX_PREVIEW + 1)
    truncated = len(data) > MAX_PREVIEW
    data = data[:MAX_PREVIEW]
    if b"\x00" in data:
        raise HTTPException(415, f"{target.name} is a binary file and cannot be previewed")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        if truncated and exc.start >= len(data) - 3:  # the cut fell inside a multi-byte character
            text = data[:exc.start].decode("utf-8", errors="replace")
        else:
            raise HTTPException(415, f"{target.name} is not a UTF-8 text file and cannot be previewed") from None
    return {"path": _relative(target, root_r), "name": target.name, "size": st.st_size, "mtime": st.st_mtime,
            "content": text, "truncated": truncated}


def save_upload(root: Path, filename: str, data: bytes) -> dict[str, Any]:
    """Store an uploaded file as `uploads/<name>` under `root`. Only the last path component of the name is
    kept, unsafe characters become `_`, and an existing file is never overwritten (`name-2.ext`, …).
    PDF / Office documents are refused like everywhere else: document work in PlanD is .md / .txt."""
    name = _UNSAFE_NAME.sub("_", Path(str(filename).replace("\\", "/")).name.strip()).lstrip(".") or "upload"
    suffix = Path(name).suffix.lower()
    if suffix in UNSUPPORTED_DOCS:
        raise HTTPException(415, f"{suffix} documents are not supported; convert it to .md or .txt first")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"file is larger than {MAX_UPLOAD // (1024 * 1024)} MB")
    policy = PathPolicy({"": root})
    folder = _resolve(policy, UPLOAD_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    stem, ext = Path(name).stem, Path(name).suffix
    target, n = folder / name, 2
    while target.exists():
        target, n = folder / f"{stem}-{n}{ext}", n + 1
    target = _resolve(policy, f"{UPLOAD_DIR}/{target.name}")  # also refuses credential/state file names
    target.write_bytes(data)
    return {"path": _relative(target, root.resolve()), "name": target.name, "size": len(data)}


def check_attachments(root: Path, paths: list[str]) -> list[str]:
    """Validate attachment paths sent with a message: each must be an existing file under `uploads/`."""
    policy = PathPolicy({"": root})
    out = []
    for rel in paths[:20]:
        rel = _clean(rel)
        if not rel.startswith(UPLOAD_DIR + "/"):
            raise HTTPException(400, f"attachments must be uploaded files ({UPLOAD_DIR}/…), got {rel!r}")
        if not _resolve(policy, rel).is_file():
            raise HTTPException(400, f"attachment {rel!r} does not exist")
        out.append(rel)
    return out


def list_dirs(path: str, *, pland_root: Path) -> dict[str, Any]:
    """Sub-folders of an absolute folder for the conversation folder picker: names only, never file names or
    contents, hidden folders skipped. `usable` says whether the folder itself may be chosen (and why not)."""
    from ..workspace import WorkspaceError, check_workspace

    p = Path(path).expanduser()
    if not p.is_absolute():
        raise HTTPException(400, "use an absolute path")
    p = p.resolve()
    if not p.is_dir():
        raise HTTPException(404, f"{p} is not a folder")
    try:
        check_workspace(p, pland_root=pland_root)
        usable, reason = True, ""
    except WorkspaceError as exc:
        usable, reason = False, str(exc)
    dirs, truncated = [], False
    try:
        entries = sorted(os.scandir(p), key=lambda e: e.name.lower())
    except PermissionError:
        entries = []
    for e in entries:
        if e.name.startswith(".") or e.name in SKIP_NAMES:
            continue
        try:
            if not e.is_dir():
                continue
        except OSError:
            continue
        if len(dirs) >= 300:
            truncated = True
            break
        dirs.append({"name": e.name, "path": str(Path(e.path))})
    return {"path": str(p), "parent": str(p.parent) if p.parent != p else None, "home": os.path.expanduser("~"),
            "dirs": dirs, "truncated": truncated, "usable": usable, "reason": reason}
