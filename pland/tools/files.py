"""File tools, confined to the agent's workspace roots by PathPolicy."""

from __future__ import annotations

import fnmatch
import os
import re

from .registry import ToolContext, ToolError, obj, tool

# Document handling is limited to Markdown and plain text by design.
UNSUPPORTED_DOCS = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".odt", ".rtf", ".pages", ".key"}
# Characters of numbered lines per read_file call: below the agent's 24,000-character cap on a tool result, so a
# page is never cut in the middle (a 60,000 limit used to lose the middle of long files, with a header saying "311 lines").
MAX_READ = 20_000
MAX_LINE = 4_000  # a single very long line is clipped rather than filling the page
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache"}


def _check_doc_format(path) -> None:
    if path.suffix.lower() in UNSUPPORTED_DOCS:
        raise ToolError(f"'{path.suffix}' documents are not supported. Use Markdown (.md) or plain text (.txt) for documents.")


@tool(
    "read_file",
    "Read a UTF-8 text file from your workspace. Returns numbered lines, up to about 20,000 characters per call; when "
    "more remains, the result ends with the offset to continue from. Use offset/limit (1-based line numbers) to read "
    "a specific part.",
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
    total = len(lines)
    start = max(1, int(a.get("offset") or 1))
    if total and start > total:
        raise ToolError(f"offset {start} is past the end of {a['path']} ({total} lines)")
    limit = int(a.get("limit") or 2000)
    wanted_end = min(total, start - 1 + limit)
    rows, size, end = [], 0, start - 1
    for i in range(start, wanted_end + 1):
        line = lines[i - 1]
        if len(line) > MAX_LINE:
            line = line[:MAX_LINE] + f" … [line clipped: {len(line) - MAX_LINE} more characters]"
        row = f"{i:>5}\t{line}"
        if rows and size + len(row) + 1 > MAX_READ:
            break
        rows.append(row)
        size += len(row) + 1
        end = i
    header = f"{ctx.paths.display(path)} ({total} lines)"
    if start > 1 or end < total:
        header += f", showing {start}-{end}"
    out = header + "\n" + "\n".join(rows)
    if end < wanted_end:
        out += (f"\n... [page full: lines {end + 1}-{wanted_end} not shown yet — call read_file again with "
                f"offset={end + 1} to continue]")
    return out


@tool(
    "write_file",
    "Create or overwrite a text file in your workspace (parent folders are created). Prefer edit_file for small changes "
    "to existing files. Keep each call under about 20,000 characters: write a large file in parts, the first with a "
    "normal call and the rest with append=true.",
    obj({"path": {"type": "string"}, "content": {"type": "string"},
         "append": {"type": "boolean", "description": "add content to the end of the file instead of replacing it"}},
        ["path", "content"]),
    "files",
)
def write_file(ctx: ToolContext, a):
    path = ctx.paths.resolve(a["path"], for_write=True)
    _check_doc_format(path)
    if path.is_dir():
        raise ToolError(f"{a['path']} is a directory")
    existed = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    if a.get("append") and existed:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(a["content"])
        ctx.emit("file.changed", path=ctx.paths.display(path), op="update")
        return f"Appended {len(a['content'])} chars to {ctx.paths.display(path)} (now {path.stat().st_size} bytes)"
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
    "Search file contents with a regular expression in a workspace directory (recursively) or a single file. "
    "Optional glob filter for directory searches, e.g. '*.py'.",
    obj({"pattern": {"type": "string"}, "path": {"type": "string"}, "glob": {"type": "string"}}, ["pattern"]),
    "files",
)
def search_files(ctx: ToolContext, a):
    base = ctx.paths.resolve(a.get("path") or ".")
    if not base.exists():
        raise ToolError(f"{a.get('path')} does not exist")  # not "no matches": that would read as a confirmed absence
    try:
        rx = re.compile(a["pattern"])
    except re.error as exc:
        raise ToolError(f"invalid regex: {exc}")
    glob = a.get("glob")
    hits = []
    if base.is_file():  # a single file: search it (os.walk on a file yields nothing, which used to look like a miss)
        walk = [(str(base.parent), [], [base.name])]
        base = base.parent
    else:
        walk = os.walk(base)
    for root, dirs, files in walk:
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
