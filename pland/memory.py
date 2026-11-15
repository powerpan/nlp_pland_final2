"""Bounded notes and reusable skills scoped to an individual profile."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .store import dumps, now

if TYPE_CHECKING:
    from .profiles import Profile

SEP = "\n§\n"
LIMITS = {"memory": 2200, "user": 1375}
FILES = {"memory": "MEMORY.md", "user": "USER.md"}


def _log(profile: "Profile", store: str, op: str, detail: Any, session_id: str | None = None) -> None:
    profile.db.execute(
        "INSERT INTO memory_events(ts, store, op, detail, session_id) VALUES (?,?,?,?,?)",
        (now(), store, op, dumps(detail), session_id),
    )


class MemoryError_(ValueError):
    pass


class NotesMemory:
    def __init__(self, profile: "Profile"):
        self.profile = profile

    def _path(self, target: str) -> Path:
        if target not in FILES:
            raise MemoryError_("target must be 'memory' or 'user'")
        return self.profile.memories_dir / FILES[target]

    def entries(self, target: str) -> list[str]:
        try:
            text = self._path(target).read_text(encoding="utf-8")
        except OSError:
            return []
        return [e.strip() for e in text.split("§") if e.strip()]

    def _write(self, target: str, entries: list[str]) -> None:
        total = len(SEP.join(entries))
        if total > LIMITS[target]:
            raise MemoryError_(
                f"{target} memory would be {total} chars (limit {LIMITS[target]}). Consolidate or remove entries first."
            )
        self._path(target).write_text(SEP.join(entries), encoding="utf-8")

    def usage(self, target: str) -> tuple[int, int]:
        return len(SEP.join(self.entries(target))), LIMITS[target]

    def add(self, target: str, content: str, session_id: str | None = None) -> str:
        content = content.strip()
        if not content:
            raise MemoryError_("content is empty")
        entries = self.entries(target)
        if any(content == e or content in e for e in entries):
            return "Already remembered (duplicate skipped)."
        entries.append(content)
        self._write(target, entries)
        _log(self.profile, target, "add", {"content": content}, session_id)
        used, cap = self.usage(target)
        return f"Saved to {target} ({used}/{cap} chars)."

    def replace(self, target: str, old_text: str, content: str, session_id: str | None = None) -> str:
        entries = self.entries(target)
        hits = [i for i, e in enumerate(entries) if old_text.strip() and old_text.strip() in e]
        if not hits:
            raise MemoryError_(f"no {target} entry contains {old_text!r}")
        if len(hits) > 1:
            raise MemoryError_(f"{len(hits)} entries contain {old_text!r}; use a more specific substring")
        before = entries[hits[0]]
        entries[hits[0]] = content.strip()
        self._write(target, entries)
        _log(self.profile, target, "replace", {"before": before, "after": content.strip()}, session_id)
        return "Entry replaced."

    def remove(self, target: str, old_text: str, session_id: str | None = None) -> str:
        entries = self.entries(target)
        keep = [e for e in entries if old_text.strip() not in e]
        if len(keep) == len(entries):
            raise MemoryError_(f"no {target} entry contains {old_text!r}")
        removed = [e for e in entries if old_text.strip() in e]
        self._write(target, keep)
        _log(self.profile, target, "remove", {"removed": removed}, session_id)
        return f"Removed {len(removed)} entr{'y' if len(removed) == 1 else 'ies'}."

    def render(self) -> str:
        blocks = []
        for target, label in (("memory", "MEMORY (your personal notes)"), ("user", "USER PROFILE (what you know about the user)")):
            entries = self.entries(target)
            used, cap = self.usage(target)
            body = SEP.join(entries) if entries else "(empty)"
            blocks.append(f"── {label} [{used}/{cap} chars] ──\n{body}")
        return "\n\n".join(blocks)


# --------------------------------------------------------------------------- skills

_FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")


class SkillStore:
    def __init__(self, profile: "Profile"):
        self.profile = profile

    def list(self) -> list[dict[str, str]]:
        out = []
        for path in sorted(self.profile.skills_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            desc = ""
            m = _FRONT.match(text)
            if m:
                for line in m.group(1).splitlines():
                    if line.startswith("description:"):
                        desc = line.split(":", 1)[1].strip()
            out.append({"name": path.stem, "description": desc})
        return out

    def view(self, name: str) -> str:
        path = self.profile.skills_dir / f"{name}.md"
        if not path.is_file():
            raise KeyError(f"no skill named {name!r}")
        return path.read_text(encoding="utf-8")

    def save(self, name: str, description: str, content: str, session_id: str | None = None) -> str:
        if not _SKILL_NAME.match(name):
            raise ValueError("skill name must match [a-z0-9][a-z0-9_-]{0,47}")
        path = self.profile.skills_dir / f"{name}.md"
        existed = path.exists()
        path.write_text(f"---\nname: {name}\ndescription: {description.strip()}\n---\n\n{content.strip()}\n", encoding="utf-8")
        _log(self.profile, "skill", "replace" if existed else "add", {"name": name, "description": description}, session_id)
        return f"Skill '{name}' {'updated' if existed else 'saved'}."
