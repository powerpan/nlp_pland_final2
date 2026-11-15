"""File tools, confined to the agent's workspace roots by PathPolicy."""

from __future__ import annotations

import fnmatch
import os
import re

from .registry import ToolContext, ToolError, obj, tool

# Document handling is limited to Markdown and plain text by design.
UNSUPPORTED_DOCS = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".odt", ".rtf", ".pages", ".key"}
MAX_READ = 60000
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache"}


def _check_doc_format(path) -> None:
    if path.suffix.lower() in UNSUPPORTED_DOCS:
        raise ToolError(f"'{path.suffix}' documents are not supported. Use Markdown (.md) or plain text (.txt) for documents.")


@tool(
    "read_file",
    "Read a UTF-8 text file from your workspace. Returns numbered lines. Use offset/limit (1-based line numbers) for large files.",
    obj({"path": {"type": "string"}, "offset": {"type": "integer", "minimum": 1}, "limit": {"type": "integer", "minimum": 1}}, ["path"]),
    "files",
)
def read_file(ctx: ToolContext, a):
    path = ctx.paths.resolve(a["path"])
    _check_doc_format(path)
    if not path.exists():
        raise ToolError(f"{a['path']} does not exist")
    if path.is_dir():
        raise ToolError(f"{a['path']} is a directory; use list_dir")
    data = path.read_bytes()
    if b"\x00" in data[:4096]:
        raise ToolError("binary file; cannot display")
    lines = data.decode("utf-8", errors="replace").splitlines()
    start = max(1, int(a.get("offset") or 1))
    limit = int(a.get("limit") or 2000)
    chunk = lines[start - 1 : start - 1 + limit]
    out = "\n".join(f"{i:>5}\t{line}" for i, line in enumerate(chunk, start))
    if len(out) > MAX_READ:
        out = out[:MAX_READ] + "\n... [truncated; use offset/limit]"
    total = len(lines)
    header = f"{ctx.paths.display(path)} ({total} lines)"
    if start > 1 or start - 1 + limit < total:
        header += f", showing {start}-{min(total, start - 1 + limit)}"
    return header + "\n" + out


@tool(
    "write_file",
    "Create or overwrite a text file in your workspace (parent folders are created). Prefer edit_file for small changes to existing files.",
    obj({"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
    "files",
)
def write_file(ctx: ToolContext, a):
    path = ctx.paths.resolve(a["path"], for_write=True)
    _check_doc_format(path)
    if path.is_dir():
        raise ToolError(f"{a['path']} is a directory")
    existed = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(a["content"], encoding="utf-8")
    ctx.emit("file.changed", path=ctx.paths.display(path), op="update" if existed else "create")
    return f"{'Updated' if existed else 'Created'} {ctx.paths.display(path)} ({len(a['content'])} chars)"


@tool(
    "edit_file",
    "Replace an exact text snippet in a file. old_text must match exactly once unless replace_all is true.",
    obj({"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"},
         "replace_all": {"type": "boolean"}}, ["path", "old_text", "new_text"]),
    "files",
)
def edit_file(ctx: ToolContext, a):
    path = ctx.paths.resolve(a["path"], for_write=True)
    _check_doc_format(path)
    if not path.is_file():
        raise ToolError(f"{a['path']} does not exist")
    text = path.read_text(encoding="utf-8")
    old, new = a["old_text"], a["new_text"]
    count = text.count(old)
    if count == 0:
        raise ToolError("old_text not found; read the file again and copy the exact text")
    if count > 1 and not a.get("replace_all"):
        raise ToolError(f"old_text occurs {count} times; add more context or set replace_all")
    text = text.replace(old, new) if a.get("replace_all") else text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    ctx.emit("file.changed", path=ctx.paths.display(path), op="update")
    return f"Edited {ctx.paths.display(path)} ({count if a.get('replace_all') else 1} replacement)"


@tool(
    "delete_file",
    "Delete a file or an empty directory in your workspace. Requires human approval.",
    obj({"path": {"type": "string"}}, ["path"]),
    "files",
)
def delete_file(ctx: ToolContext, a):
    path = ctx.paths.resolve(a["path"], for_write=True)
    if not path.exists():
        raise ToolError(f"{a['path']} does not exist")
    if path in [r.resolve() for r in ctx.paths.roots.values()]:
        raise ToolError("refusing to delete a workspace root")
    ctx.require_approval("files:delete", f"Delete {ctx.paths.display(path)}", detail=f"absolute path: {path}")
    if path.is_dir():
        path.rmdir()
    else:
        path.unlink()
    ctx.emit("file.changed", path=ctx.paths.display(path), op="delete")
    return f"Deleted {ctx.paths.display(path)}"


@tool(
    "list_dir",
    "List files under a directory of your workspace (default: workspace root). Set recursive=true for a tree (max 400 entries).",
    obj({"path": {"type": "string"}, "recursive": {"type": "boolean"}}),
    "files",
)
def list_dir(ctx: ToolContext, a):
    path = ctx.paths.resolve(a.get("path") or ".")
    if not path.is_dir():
        raise ToolError(f"{a.get('path')} is not a directory")
    entries = []
    if a.get("recursive"):
        for root, dirs, files in os.walk(path):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for f in sorted(files):
                full = os.path.join(root, f)
                entries.append(f"{os.path.relpath(full, path)}  ({os.path.getsize(full)} B)")
                if len(entries) >= 400:
                    entries.append("... (truncated)")
                    return "\n".join(entries)
    else:
        for child in sorted(path.iterdir()):
            entries.append(child.name + ("/" if child.is_dir() else f"  ({child.stat().st_size} B)"))
    return f"{ctx.paths.display(path)}:\n" + ("\n".join(entries) if entries else "(empty)")


@tool(
    "search_files",
    "Search file contents with a regular expression under a workspace directory. Optional glob filter, e.g. '*.py'.",
    obj({"pattern": {"type": "string"}, "path": {"type": "string"}, "glob": {"type": "string"}}, ["pattern"]),
    "files",
)
def search_files(ctx: ToolContext, a):
    base = ctx.paths.resolve(a.get("path") or ".")
    try:
        rx = re.compile(a["pattern"])
    except re.error as exc:
        raise ToolError(f"invalid regex: {exc}")
    glob = a.get("glob")
    hits = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if glob and not fnmatch.fnmatch(f, glob):
                continue
            full = os.path.join(root, f)
            try:
                with open(full, encoding="utf-8") as fh:
                    for no, line in enumerate(fh, 1):
                        if rx.search(line):
                            hits.append(f"{os.path.relpath(full, base)}:{no}: {line.rstrip()[:240]}")
                            if len(hits) >= 200:
                                return "\n".join(hits) + "\n... (truncated)"
            except (UnicodeDecodeError, OSError):
                continue
    return "\n".join(hits) if hits else "no matches"
