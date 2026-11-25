"""Fast Mode for group tasks: a per-group setting (room settings "fast_mode") that bounds the checking a
team does on one request, without lowering anyone's thinking — every bot keeps its own configured reasoning level.

While a Fast Mode drive runs (one human message and everything it sets off), its `FastMode` object rides on the
drive's shared `Budget`, so the lead, its delegates and their subagents all see the same limits:

* Every shell or Python command runs for at most `COMMAND_LIMIT_S` (25 s), and all commands of the team together for
  at most `TEAM_LIMIT_S` (90 s). Time is reserved before a command starts, so parallel delegates cannot overshoot.
* Board cards carry an acceptance scope: the files a card delivers and the checks that accept them
  (`team_tasks add/update` with `files` and `checks`). `run_checks` runs only those checks, skips a check that
  already passed on the same file contents, and records each result against the files' SHA-256 hashes.
* Review cards bind an acceptance criterion to input versions and a report. Fast Mode allows a first review, a
  revision and one continuation of unfinished work. Step and phase-specific time ceilings are operator settings.
  Cross-card reuse requires an explicit matching criterion, context and current evidence.
* At the end of the drive the group gets a summary line: which files are verified (every check of their cards passed
  and no review failed, all on the current contents) and what still needs checking, and why.

Check results live in shared.db (`verifications`), review verdicts in `team_reviews`, so a later message in the same
group reuses them as long as the files are unchanged.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import AgentSettings, global_settings
from ..store import dumps, loads, now

if TYPE_CHECKING:
    from ..runtime import Runtime
    from ..tools.registry import ToolContext

COMMAND_LIMIT_S = 25.0
TEAM_LIMIT_S = 90.0
MIN_COMMAND_S = 1.0  # below this much time left, a command is not started at all
MAX_SCOPE_FILES = 60
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules", ".venv", "venv"}
_REVIEW_WORDS = re.compile(r"\breview|\bQA\b|審查|審閱|覆核|评审|審核|(?:请|請)(?:再|独立|獨立)?(?:复核|複核|审核|审阅|審閱|审查|验收|驗收)", re.IGNORECASE)
_VERDICT_REQUEST = re.compile(
    r"(?:\b(?:reply|respond|answer|report back|(?:just|only|please) return)\b|回[我覆复答]|只[写寫回]|首行|第一行|(?:给出|給出|请给|請給)(?:结论|結論|判定))"
    r"[^.!?。！？]{0,100}?(?<![a-z])pass\s*(?:[/／]|or|或(?:者)?|还是|還是)\s*fail(?![a-z])", re.I)
REVIEW_ROLE = re.compile(r"\breview|\bQA\b|審查|審閱|測試員|tester", re.IGNORECASE)  # a bot whose job is reviewing


class FastLimit(RuntimeError):
    """The team's command time is used up."""


def enabled(room: dict[str, Any] | None) -> bool:
    return bool(((room or {}).get("settings") or {}).get("fast_mode"))


def of(agent: Any) -> "FastMode | None":
    """The Fast Mode of the drive this agent works in, if any."""
    return getattr(getattr(agent, "budget", None), "fast", None)


def sha(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def expand(paths: list[str]) -> list[str]:
    """Absolute file paths: directories are expanded to the files in them (caches and VCS folders skipped)."""
    out: list[str] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and not SKIP_DIRS & set(f.relative_to(p).parts):
                    out.append(str(f))
        else:
            out.append(str(p))
    return list(dict.fromkeys(out))[:MAX_SCOPE_FILES]


def hashes(paths: list[str]) -> dict[str, str | None]:
    return {p: sha(Path(p)) for p in expand(paths)}


def read_scope(row: dict | None) -> dict:
    files = loads(row["files"], []) if row else []
    # Existing cards store only a list of outputs. New cards may declare fixtures/checker scripts separately.
    if isinstance(files, list):
        files = {"files": files, "check_inputs": []}
    return {**files, "checks": loads(row["checks"], []) if row else []}


def scope_versions(scope: dict) -> dict:
    return {**hashes(scope["files"]), **hashes(scope.get("check_inputs", []))}


def is_reviewer(profile: Any) -> bool:
    """A bot whose title or description says its job is reviewing."""
    return bool(REVIEW_ROLE.search(f"{getattr(profile, 'title', '')} {getattr(profile, 'description', '')}"))


def asks_for_review(text: str) -> bool:
    """A message that asks for a review (Fast Mode sends those through delegate_task's review field)."""
    return bool(_REVIEW_WORDS.search(text[:400]) or _VERDICT_REQUEST.search(text))


@dataclass
class ReviewDecision:
    kind: str  # run | refused
    round: int = 1  # 1 = the card's review, 2 = its follow-up
    resumes: int = 0
    reason: str = ""


def review_gate(own: dict | None, review: dict[str, Any]) -> ReviewDecision:
    """Fast Mode's rules for a prepared review (pland/team/review.py `prepare_review`)."""
    inputs = review["inputs"]
    if not own or not own.get("criterion"):
        return ReviewDecision("run")
    done = int(own.get("round") or 1)
    resumes = own.get("resumes", 0)
    names = ", ".join(inputs)
    if own["verdict"] in {"incomplete", "stale"}:
        if resumes >= 1:
            return ReviewDecision("refused", reason="This review already used its continuation. List the checks still open.")
        return ReviewDecision("run", round=done, resumes=resumes + 1)
    if done >= 2:
        return ReviewDecision("refused", reason=(
            "This card already had its review and its one follow-up in Fast Mode. Do not review it again: report "
            f"these files as still needing a check: {names}."))
    return ReviewDecision("run", round=done + 1, resumes=resumes)


class FastMode:
    """The Fast Mode limits and records of one group drive."""

    def __init__(self, runtime: "Runtime", room_id: str, *, command_limit: float | None = None,
                 team_limit: float | None = None):
        self.rt = runtime
        self.db = runtime.shared
        self.room_id = room_id
        self.command_limit = COMMAND_LIMIT_S if command_limit is None else command_limit
        self.team_limit = TEAM_LIMIT_S if team_limit is None else team_limit
        settings = global_settings(runtime.root)
        defaults = AgentSettings
        self.review_steps = min(settings.get("review_max_steps", defaults.review_max_steps),
                                settings.get("fast_review_steps", defaults.fast_review_steps))
        time_limit = settings.get("review_timeout_seconds", defaults.review_timeout_seconds)
        self.first_seconds = min(time_limit, settings.get("fast_review_seconds", defaults.fast_review_seconds))
        self.followup_seconds = min(time_limit, settings.get("fast_followup_seconds", defaults.fast_followup_seconds))
        self.started = time.time()
        self.inherited_conflicts: set[str] = set()
        self.used = 0.0  # seconds of command time spent
        self.reserved = 0.0  # seconds held by commands still running
        self.commands = 0
        self.refused = 0  # commands not started because the team's time was used up
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ command time
    @property
    def remaining(self) -> float:
        with self._lock:
            return max(0.0, self.team_limit - self.used - self.reserved)

    def reserve(self, requested: float | None) -> float:
        """Hold time for one command; returns its timeout. Raises FastLimit when the team's time is used up."""
        with self._lock:
            left = self.team_limit - self.used - self.reserved
            if left < MIN_COMMAND_S:
                self.refused += 1
                raise FastLimit(self.exhausted_text())
            timeout = min(self.command_limit, float(requested) if requested else self.command_limit, left)
            self.reserved += timeout
            self.commands += 1
            return timeout

    def settle(self, reserved: float, duration: float) -> None:
        with self._lock:
            self.reserved = max(0.0, self.reserved - reserved)
            self.used += min(max(0.0, duration), reserved)

    def describe(self) -> str:
        return (f"Fast Mode command time: {self.used:.0f}s of the team's {self.team_limit:.0f}s used, "
                f"{self.remaining:.0f}s left; each command stops after {self.command_limit:.0f}s.")

    def exhausted_text(self) -> str:
        return (f"Fast Mode: the team's {self.team_limit:.0f}s of command time is used up, so no more shell or Python "
                "commands run in this request. Stop checking: report the verified files and list what still needs "
                "checking.\n" + self.status_text())

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"command_seconds": round(self.used, 1), "team_limit_s": self.team_limit,
                    "command_limit_s": self.command_limit, "commands": self.commands, "refused": self.refused}

    # ------------------------------------------------------------------ card scopes
    def scope(self, task_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT files, checks FROM task_scopes WHERE task_id=? AND room_id=?", (task_id, self.room_id))
        return read_scope(row)

    def check_signature(self, raw: str) -> str:
        """A repeated acceptance call may address a different version of its inputs."""
        args = loads(raw, {})
        tid = args.get("task_id") if isinstance(args, dict) else None
        if not isinstance(tid, str):
            return raw
        scope = self.scope(tid)
        return dumps([tid, scope["checks"], scope_versions(scope)])

    def label(self, path: str) -> str:
        return label(self.rt, self.room_id, path)

    def _records(self, *, task_id: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM verifications WHERE room_id=?", [self.room_id]
        if task_id:
            sql += " AND task_id=?"
            params.append(task_id)
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        rows = self.db.query(sql + " ORDER BY id", params)
        for r in rows:
            r["files"] = loads(r["files"], {})
            r["snapshot"] = loads(r.get("snapshot"), {})
        return rows

    def record(self, *, task_id: str | None, kind: str, subject: str, files: dict[str, str | None], result: str,
               report: str = "", rnd: int = 1, snapshot: dict[str, str] | None = None) -> None:
        self.db.execute("INSERT INTO verifications(room_id, task_id, kind, subject, files, verdict, round, report, snapshot, created)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (self.room_id, task_id, kind, subject, dumps(files), result, rnd, report[:8000],
                         dumps(snapshot or {}), now()))

    # ------------------------------------------------------------------ checks
    def check_state(self, task_id: str, command: str, current: dict[str, str | None]) -> tuple[str, dict | None]:
        """("pass" | "fail" | "stale" | "stale-fail" | "not-run", the deciding record). A result counts for every card
        with the same check on the same file contents: a run found a stale result on the first card overruling the
        same check that later passed on the final contents under another card."""
        rows = [r for r in self._records(kind="check") if r["subject"] == command]
        if not current:
            observed = [r for r in rows if r["task_id"] == task_id and not r["files"] and r["created"] >= self.started]
            return (observed[-1]["verdict"], observed[-1]) if observed else ("not-run", None)
        same = [r for r in rows if r["files"] == current and None not in current.values()]
        if same:
            return ("pass" if same[-1]["verdict"] == "pass" else "fail"), same[-1]
        mine = [r for r in rows if r["task_id"] == task_id]
        if mine:
            return ("stale" if mine[-1]["verdict"] == "pass" else "stale-fail"), mine[-1]
        return "not-run", None

    def board_checks(self, task_id: str) -> list[dict[str, str]]:
        scope = self.scope(task_id)
        if not scope["checks"]:
            return []
        current = scope_versions(scope)
        if current:
            return [{"command": cmd, "state": self.check_state(task_id, cmd, current)[0]} for cmd in scope["checks"]]
        observed = {r["subject"]: r for r in self._records(task_id=task_id, kind="check") if not r["files"]}
        return [{"command": cmd, "state": "last-" + observed[cmd]["verdict"] if cmd in observed else "not-run"}
                for cmd in scope["checks"]]

    def passed_check(self, task_id: str, command: str, current: dict[str, str | None]) -> dict[str, Any] | None:
        """The result of this check, if it passed on exactly the current file contents."""
        if not current:
            return None  # a live observation has no version to cache
        state, row = self.check_state(task_id, command, current)
        return row if state == "pass" else None

    # ------------------------------------------------------------------ status
    def has_active_checks(self) -> bool:
        return bool(self.db.one("SELECT 1 FROM task_scopes s JOIN team_tasks t ON t.id=s.task_id "
                                "WHERE s.room_id=? AND (s.updated>=? OR t.updated>=?) "
                                "UNION ALL SELECT 1 FROM verifications WHERE room_id=? AND created>=? LIMIT 1",
                                (self.room_id, self.started, self.started, self.room_id, self.started)))

    def _active_scopes(self) -> list[dict[str, Any]]:
        """Cards with declared outputs or checks touched during this drive."""
        rows = self.db.query("SELECT t.id, t.title, t.updated, s.files, s.checks, s.updated AS scope_updated FROM team_tasks t "
                             "JOIN task_scopes s ON s.task_id = t.id WHERE t.room_id=? ORDER BY t.created", (self.room_id,))
        touched = {r["task_id"] for r in self.db.query(
            "SELECT DISTINCT task_id FROM verifications WHERE room_id=? AND created>=?", (self.room_id, self.started))}
        out = []
        for r in rows:
            if max(r["updated"], r["scope_updated"]) >= self.started or r["id"] in touched:
                out.append({"id": r["id"], "title": r["title"], **read_scope(r)})
        return out

    def _absolute(self, name: str) -> str:
        return str(self.rt.rooms.shared_dir(self.room_id) / name.removeprefix("shared/"))

    def status(self) -> dict[str, Any]:
        """Which files are verified and what still needs checking, judged on the files' current contents."""
        cards = self._active_scopes()
        reviewed = self.rt.board.reviewed(self.room_id)
        requirements = []
        verified: list[str] = []
        pending: list[str] = []  # human-readable reasons
        per_file: dict[str, list[str]] = {}
        evidence: dict[str, bool] = {}
        for card in cards:
            outputs = hashes(card["files"])
            current = {**outputs, **hashes(card.get("check_inputs", []))}
            checks = []
            for f, digest in outputs.items():
                per_file.setdefault(f, [])
                if digest is None:
                    per_file[f].append("the file is missing")
            for cmd in card["checks"]:
                found, _ = self.check_state(card["id"], cmd, current)
                checks.append({"command": cmd, "state": found})
                if found == "pass":
                    for f in outputs:
                        evidence[f] = True
                    continue
                state = {"fail": "failed", "stale": "passed, but the files changed afterwards",
                         "stale-fail": "failed on an earlier version and was not run again", "not-run": "was not run"}[found]
                for f in outputs:
                    per_file[f].append(f"check `{cmd}` {state}")
            if checks:
                requirements.append({"task_id": card["id"], "criterion": card["title"],
                                     "verdict": "pass" if all(c["state"] == "pass" for c in checks)
                                     else "fail" if any(c["state"] == "fail" for c in checks) else "incomplete",
                                     "files": [self.label(f) for f in outputs], "checks": checks})
        active_ids = {card["id"] for card in cards}
        for row in self.db.query("SELECT id,title,updated FROM team_tasks WHERE room_id=? AND conflict_source IS NOT NULL "
                                 "AND id NOT IN (SELECT task_id FROM team_reviews)",
                                 (self.room_id,)):
            if row["id"] not in self.inherited_conflicts and row["updated"] < self.started:
                continue
            active_ids.add(row["id"])
            requirements.append({"task_id": row["id"], "criterion": row["title"], "verdict": "incomplete",
                                 "files": [], "report": None})
        for card in reviewed:
            review = card["review"]
            if card["id"] not in active_ids | self.inherited_conflicts and card["updated"] < self.started:
                continue
            active_ids.add(card["id"])
            criterion = review.get("criterion") or card["title"]
            verdict = review["verdict"]
            requirements.append({"task_id": card["id"], "criterion": criterion, "verdict": verdict,
                                 "files": list(review["inputs"]), "report": review["report"] if review["report_written"] else None})
            # A review can read a fixture or brief as evidence. Keep it versioned, but do not
            # count it as a deliverable unless a related production card also declares it as one.
            inputs = [self._absolute(name) for name, digest in review["inputs"].items() if digest is not None]
            input_set = set(inputs)
            related = [scope for scope in cards
                       if scope["id"] == card["id"] or not input_set.isdisjoint(expand(scope["files"]))]
            included = {scope["id"] for scope in related}
            related.extend(self.scope(tid) for tid in card["depends_on"] if tid not in included)
            references = {p for scope in related for p in expand(scope.get("check_inputs", []))}
            references.update(self._absolute(name) for name in review.get("supporting_files", []))
            references.difference_update(p for scope in related for p in expand(scope["files"]))
            for f in inputs:
                if f in references:
                    continue
                reasons = per_file.setdefault(f, [])
                if verdict == "pass" and card["status"] == "done":
                    evidence[f] = True
                else:
                    reason = {"stale": "changed after its review", "fail": "its review said FAIL"}.get(
                        verdict, review.get("verdict_reason") or "its review is incomplete")
                    reasons.append(f"{criterion}: {reason}")
        for f, reasons in per_file.items():
            if not reasons and evidence.get(f):
                verified.append(f)
            else:
                pending.append(f"{self.label(f)}: " + ("; ".join(dict.fromkeys(reasons)) if reasons else "no check or review covers it"))
        return {"cards": len(active_ids), "requirements": requirements,
                "present": [self.label(f) for f in per_file if Path(f).is_file()],
                "verified": [self.label(f) for f in verified], "pending": pending}

    def status_text(self, st: dict | None = None) -> str:
        st = self.status() if st is None else st
        if not st["cards"]:
            return "No board card has files and checks yet, so nothing is verified."
        lines = [f"- {r['criterion']}: {r['verdict'].upper()}" for r in st["requirements"]]
        if st["pending"]:
            lines.append("Files present: " + (", ".join(st["present"]) or "(none)"))
        lines += ["Verified: " + (", ".join(st["verified"]) or "(none)")]
        if st["pending"]:
            lines.append("Still needs checking:")
            lines += [f"- {p}" for p in st["pending"]]
        return "\n".join(lines)

    def summary(self, st: dict | None = None) -> str | None:
        """The group's closing line for this drive (None when no card had an acceptance scope)."""
        st = self.status() if st is None else st
        if not st["cards"]:
            return None
        verified, total = len(st["verified"]), len(st["verified"]) + len(st["pending"])
        present = len(st["present"])
        if not total:
            head = "Fast Mode — acceptance checks for this request."
        elif verified == total and all(r["verdict"] == "pass" for r in st["requirements"]):
            head = f"✓ Fast Mode — files verified: {verified} of {total}."
        elif self.refused or self.remaining < MIN_COMMAND_S:
            head = f"⚠ Fast Mode — files verified: {verified} of {total}; the command time ran out."
        else:
            head = f"⚠ Fast Mode — files verified: {verified} of {total}."
        if st["pending"]:
            head = " ".join((head, f"Deliverables present: {present} of {total}."))
        return head + "\n" + self.status_text(st) + "\n" + self.describe()


def label(rt: "Runtime", room_id: str | None, path: str) -> str:
    """A short name for a file: shared/… inside the group's folder, @bot:… inside a bot's workspace."""
    p = Path(path)
    if room_id:
        try:
            return "shared/" + p.relative_to(rt.rooms.shared_dir(room_id)).as_posix()
        except ValueError:
            pass
        for name in (rt.rooms.get(room_id) or {}).get("members", []):
            try:
                return f"@{name}:" + p.relative_to(rt.profiles.get(name).workspace.resolve()).as_posix()
            except (ValueError, KeyError):
                continue
    return str(p)


def set_scope(ctx: "ToolContext", task_id: str, files: list[str] | None, checks: list[str] | None,
              check_inputs: list[str] | None = None) -> None:
    """Store a card's acceptance scope (files resolved from the caller's folder; `shared/` works for everyone)."""
    if files is None and checks is None and check_inputs is None:
        return
    row = ctx.runtime.shared.one("SELECT files, checks FROM task_scopes WHERE task_id=?", (task_id,))
    scope = read_scope(row)
    if files is not None:
        scope["files"] = list(dict.fromkeys(str(ctx.paths.resolve(p)) for p in files[:MAX_SCOPE_FILES]))
    if check_inputs is not None:
        scope["check_inputs"] = list(dict.fromkeys(str(ctx.paths.resolve(p)) for p in check_inputs[:MAX_SCOPE_FILES]))
    if checks is not None:
        scope["checks"] = [c.strip() for c in checks if c and c.strip()][:8]
    ctx.runtime.shared.execute(
        "INSERT INTO task_scopes(task_id, room_id, files, checks, updated) VALUES (?,?,?,?,?) "
        "ON CONFLICT(task_id) DO UPDATE SET files=excluded.files, checks=excluded.checks, updated=excluded.updated",
        (task_id, ctx.room_id, dumps({k: scope[k] for k in ("files", "check_inputs")}), dumps(scope["checks"]), now()))


def scope_lines(rt: "Runtime", task: dict[str, Any]) -> str:
    """The card's scope for the board text agents read ("" when it has none)."""
    row = rt.shared.one("SELECT files, checks FROM task_scopes WHERE task_id=?", (task["id"],))
    if not row:
        return ""
    scope = read_scope(row)
    files = [label(rt, task.get("room_id"), f) for f in scope["files"]]
    checks = scope["checks"]
    out = ""
    if files:
        out += "\n    files: " + ", ".join(files)
    if scope["check_inputs"]:
        out += "\n    check inputs: " + ", ".join(label(rt, task.get("room_id"), p) for p in scope["check_inputs"])
    if checks:
        out += "\n    checks: " + " | ".join(checks)
    return out


def guidance(fast: FastMode, role: str) -> str:
    """What a Fast Mode drive asks of the lead and of the bots it hands work to."""
    common = (f"FAST MODE is on for this group. Run only the checks required for acceptance — no extra exploratory runs. "
              f"Every shell or Python command stops after {fast.command_limit:.0f}s and the whole team has "
              f"{fast.team_limit:.0f}s of command time for this request ({fast.remaining:.0f}s left now). "
              "Think as carefully as you normally do. "
              "For an advisory length target, skip counting and allow at most one optional shortening pass. "
              "Hand off as soon as the result is usable. Reopen for missing requirements, substantive errors, "
              "failed required checks or requested changes.")
    if role == "lead":
        return common + (
            " Put each deliverable on the board with its acceptance scope: team_tasks add/update with `files` (the "
            "files the card delivers), `check_inputs` (local checker scripts, fixtures and source files the checks read) and `checks` (the commands that accept them, e.g. `pytest -q shared/test_x.py`). "
            "Run them with run_checks(task_id); a check that already passed on unchanged files is not run again. "
            "run_checks is the acceptance run: do not also run the tests or ad-hoc scripts yourself before or after it. "
            "When assigning a check, name the decision it must settle and ask for a prompt verdict with the "
            "evidence that matters. Focus on explicit requirements and defects that change the result or its use. "
            "For an independent sign-off use delegate_task's review field (inputs and report under shared/). "
            f"Each review has up to {fast.review_steps} steps; the first gets "
            f"{fast.first_seconds}s and its revision gets {fast.followup_seconds}s. Use the same card and criterion "
            "for one continuation of unfinished work and one revision. Reuse requires matching criteria and evidence. "
            "Make small, well-understood fixes yourself when your tools allow, then run the affected check. "
            "Send work back to its author only when it needs their expertise or access. If no independent "
            "sign-off is due, deliver after the check passes. If a required review failed or you changed signed "
            "inputs, get the verdict on the affected parts on the same card. Once accepted, deliver as-is and "
            "skip optional polish. "
            "If the command time runs out before every required check passes, stop and reply with the verified files "
            "and a clear list of what still needs checking.")
    if role == "review":
        return common + (
            " Start with the check most likely to change the verdict. Honor every required observation. "
            "As soon as the evidence establishes a blocking defect, record FAIL with the observed result and "
            "the needed correction. Include other known blockers in that report. Once the required checks pass, "
            "record PASS and return immediately. Keep the report brief and omit optional polish. "
            "If evidence is missing, identify the outstanding "
            "check and leave the verdict INCOMPLETE.")
    return common + (" If asked to check evidence during production, report material findings promptly. "
                     "If your task has a board card with checks, run them with run_checks(task_id) instead of "
                     "your own test commands. Do not start a review unless this task was delegated to you as one "
                     "(reviews run only through delegate_task's review field). If the command time runs out, report "
                     "what you verified and what still needs checking.")
