"""Per-agent memory and experience.

Three layers, all stored inside the owning profile (never shared implicitly):

1. Bounded notes (`memories/MEMORY.md`, `memories/USER.md`), Hermes-style: short entries
   separated by `§`, injected into the system prompt as a frozen snapshot at session start and
   edited by the agent through the `memory` tool.
2. Experiences (`experiences` table): after every task a reflection step distils the outcome,
   reusable lessons and the procedure that worked (or why it failed). Before a new task the most
   relevant experiences are retrieved (BM25 with CJK bigrams) and shown to the agent. Each
   experience tracks how often it was used and whether the tasks that used it succeeded, and that
   helpfulness score feeds back into retrieval ranking — this is the "evolution" loop.
3. Skills (`skills/<name>.md`): procedural notes the agent writes itself for recurring work.

All writes are logged in `memory_events` so the evaluation report can show how memory changed.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .store import dumps, loads, new_id, now

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


# --------------------------------------------------------------------------- experiences

_WORD = re.compile(r"[a-zA-Z0-9_]+|[㐀-鿿豈-﫿]")
_STOP = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "is", "are", "be", "it", "this",
         "that", "please", "file", "我", "的", "了", "是", "在", "和", "請", "一", "個"}


def tokenize(text: str) -> list[str]:
    raw = [t.lower() for t in _WORD.findall(text or "")]
    out: list[str] = []
    prev_cjk = None
    for tok in raw:
        is_cjk = len(tok) == 1 and "㐀" <= tok <= "﫿"
        if is_cjk:
            if prev_cjk:
                out.append(prev_cjk + tok)  # CJK bigrams
            if tok not in _STOP:
                out.append(tok)
            prev_cjk = tok
        else:
            prev_cjk = None
            if tok not in _STOP and len(tok) > 1:
                out.append(tok)
    return out


@dataclass
class Experience:
    id: str
    task: str
    outcome: str
    summary: str
    lessons: list[str]
    procedure: str | None
    tags: list[str]
    session_id: str | None
    created: float
    uses: int
    helpful: int
    unhelpful: int
    last_used: float | None

    @classmethod
    def from_row(cls, r: dict[str, Any]) -> "Experience":
        return cls(
            id=r["id"], task=r["task"], outcome=r["outcome"], summary=r["summary"],
            lessons=loads(r["lessons"], []), procedure=r["procedure"], tags=loads(r["tags"], []),
            session_id=r["session_id"], created=r["created"], uses=r["uses"], helpful=r["helpful"],
            unhelpful=r["unhelpful"], last_used=r["last_used"],
        )

    @property
    def utility(self) -> float:
        # Laplace-smoothed success rate of tasks that used this experience.
        return (self.helpful + 1) / (self.helpful + self.unhelpful + 2)

    def text(self) -> str:
        return " ".join([self.task, self.summary, " ".join(self.lessons), self.procedure or "", " ".join(self.tags)])

    def render(self) -> str:
        lines = [f"[{self.outcome}] Task: {self.task[:200]}", f"  What happened: {self.summary[:400]}"]
        for lesson in self.lessons[:4]:
            lines.append(f"  - Lesson: {lesson[:300]}")
        if self.procedure:
            lines.append(f"  Procedure that worked: {self.procedure[:600]}")
        if self.uses:
            lines.append(f"  (reused {self.uses}x, helpful {self.helpful}, unhelpful {self.unhelpful})")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["utility"] = round(self.utility, 3)
        return d


class ExperienceStore:
    def __init__(self, profile: "Profile"):
        self.profile = profile
        self.db = profile.db

    def add(self, *, task: str, outcome: str, summary: str, lessons: list[str], procedure: str | None = None,
            tags: list[str] | None = None, session_id: str | None = None) -> Experience:
        outcome = outcome if outcome in {"success", "partial", "failure"} else "partial"
        eid = new_id("x_")
        self.db.execute(
            "INSERT INTO experiences(id, task, outcome, summary, lessons, procedure, tags, session_id, created) VALUES (?,?,?,?,?,?,?,?,?)",
            (eid, task[:2000], outcome, summary[:2000], dumps([l[:500] for l in lessons][:8]), (procedure or None) and procedure[:3000],
             dumps(tags or []), session_id, now()),
        )
        _log(self.profile, "experience", "add", {"id": eid, "task": task[:200], "outcome": outcome, "lessons": lessons[:8]}, session_id)
        return self.get(eid)

    def get(self, eid: str) -> Experience:
        row = self.db.one("SELECT * FROM experiences WHERE id=?", (eid,))
        if row is None:
            raise KeyError(eid)
        return Experience.from_row(row)

    def all(self) -> list[Experience]:
        return [Experience.from_row(r) for r in self.db.query("SELECT * FROM experiences ORDER BY created")]

    def by_session(self, session_id: str) -> list[Experience]:
        rows = self.db.query("SELECT * FROM experiences WHERE session_id=? ORDER BY created", (session_id,))
        return [Experience.from_row(r) for r in rows]

    def search(self, query: str, k: int = 3, *, min_coverage: float = 0.3, rel_cutoff: float = 0.3) -> list[tuple[Experience, float]]:
        """Rank by BM25 relevance × utility weight, gated by query-term coverage (share of the query's
        distinct terms that appear in the experience). Calibrated on real runs: unrelated tasks cover
        ~0.1–0.27 of the query terms, the same kind of task 0.5–1.0. Hits below `rel_cutoff` × the best
        score are dropped as well."""
        exps = self.all()
        if not exps or k <= 0:
            return []
        docs = [tokenize(e.text()) for e in exps]
        q = tokenize(query)
        qset = set(q)
        if not qset:
            return []
        n = len(docs)
        avgdl = sum(len(d) for d in docs) / n or 1.0
        df: Counter[str] = Counter()
        for d in docs:
            df.update(set(d))
        k1, b = 1.4, 0.75
        scored = []
        for exp, doc in zip(exps, docs):
            tf = Counter(doc)
            coverage = len(qset & tf.keys()) / len(qset)
            if coverage < min_coverage:
                continue
            s = 0.0
            for term in qset:
                if term not in tf:
                    continue
                idf = math.log(1 + n / df[term])  # stays positive in tiny stores
                s += idf * tf[term] * (k1 + 1) / (tf[term] + k1 * (1 - b + b * len(doc) / avgdl))
            # Evolution signal: experiences that kept leading to success rank higher, ones that
            # kept failing sink. Failure records stay retrievable (they carry "what not to do").
            scored.append((exp, s * (0.5 + utility_weight(exp))))
        scored.sort(key=lambda t: t[1], reverse=True)
        if not scored:
            return []
        floor = rel_cutoff * scored[0][1]
        return [(e, round(s, 3)) for e, s in scored[:k] if s >= floor]

    def mark_used(self, ids: list[str], session_id: str | None = None) -> None:
        for eid in ids:
            self.db.execute("UPDATE experiences SET uses=uses+1, last_used=? WHERE id=?", (now(), eid))
        if ids:
            _log(self.profile, "experience", "retrieve", {"ids": ids}, session_id)

    def feedback(self, ids: list[str], success: bool, session_id: str | None = None) -> None:
        col = "helpful" if success else "unhelpful"
        for eid in ids:
            self.db.execute(f"UPDATE experiences SET {col}={col}+1 WHERE id=?", (eid,))
        if ids:
            _log(self.profile, "experience", "feedback", {"ids": ids, "success": success}, session_id)

    def correct_feedback(self, ids: list[str], was_success: bool, now_success: bool, session_id: str | None = None) -> None:
        """Move feedback that was given on a self-assessed outcome to the verified outcome."""
        if was_success == now_success or not ids:
            return
        dec, inc = ("helpful", "unhelpful") if was_success else ("unhelpful", "helpful")
        for eid in ids:
            self.db.execute(f"UPDATE experiences SET {dec}=MAX(0,{dec}-1), {inc}={inc}+1 WHERE id=?", (eid,))
        _log(self.profile, "experience", "feedback", {"ids": ids, "success": now_success, "corrected": True}, session_id)

    def set_outcome(self, session_id: str, outcome: str, note: str | None = None) -> int:
        """Overwrite the self-assessed outcome with a verified one (used by the eval harness)."""
        rows = self.by_session(session_id)
        for exp in rows:
            summary = exp.summary + (f" [verified: {note}]" if note else "")
            self.db.execute("UPDATE experiences SET outcome=?, summary=? WHERE id=?", (outcome, summary[:2000], exp.id))
        if rows:
            _log(self.profile, "experience", "verify", {"session_id": session_id, "outcome": outcome, "note": note}, session_id)
        return len(rows)

    def delete(self, eid: str) -> None:
        self.db.execute("DELETE FROM experiences WHERE id=?", (eid,))
        _log(self.profile, "experience", "remove", {"id": eid})


def utility_weight(exp: Experience) -> float:
    return exp.utility


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
