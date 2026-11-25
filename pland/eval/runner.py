"""Evaluation runner.

For each task: prepare an isolated environment (fresh workspaces, a fresh group room for team tasks,
memory carried or reset as the task asks), submit the prompt, wait for the final result under a
wall-clock timeout, verify with objective checks, and record everything needed for the report:
outcome, per-check results (sub-task completion), execution time, model usage, HITL exchanges,
delegations, tool errors and memory changes. The verified outcome is fed back into the agents'
experience stores, so memory evolves from ground truth rather than self-assessment.

Each suite run gets its own PLAND_HOME under the run directory (outside the repository by default:
~/.pland/eval_runs/), so evaluation never touches the user's own agents.
"""

from __future__ import annotations

import json
import math
import shutil
import statistics
import subprocess
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import pland_home
from ..hitl import ScriptedHITL, ScriptedRule
from ..llm.pricing import cost
from ..memory import ExperienceStore, NotesMemory, SkillStore
from ..runtime import Runtime
from ..sandbox.backends import scrub_env
from ..sessions import SessionStore
from ..store import DB, loads
from .checks import CheckEnv, run_check
from .tasks import Task, load_suite


@dataclass
class RunOptions:
    out_dir: Path | None = None
    backend: str = "local"
    memory: str = "on"  # on | off (ablation: no experience retrieval, no reflection, no memory tools)
    passes: int = 1  # run the whole suite N times in the same home (memory carries across passes)
    only: list[str] | None = None
    model: str | None = None
    thinking: bool | None = None  # None: profile/default setting
    reasoning: str | None = None  # thinking intensity: off|default|low|medium|high|max (None: profile setting)
    label: str = ""
    # After a timeout the task is cancelled. Agents stop at their next step, but a model call (300 s, with retries)
    # or a blocking tool can keep the task's thread busy that long. The runner waits up to this long for it to exit
    # before verifying and moving on; a thread still alive then is recorded as a straggler (see SuiteRunner).
    cancel_grace_s: float = 1500.0


def _hitl_for(task: Task) -> ScriptedHITL:
    h = task.hitl or {}
    rules = [ScriptedRule(match=r["match"], reply=r.get("reply")) for r in h.get("replies") or []]
    rules += [ScriptedRule(match=r["match"], choice=r.get("choice")) for r in h.get("approval_rules") or []]
    default_choice = {"approve": "once", "deny": "deny", "session": "session", "always": "always", "once": "once"}.get(
        str(h.get("approvals") or "approve"), "once")
    return ScriptedHITL(rules, default_reply=h.get("default_reply"), default_choice=default_choice)


class SuiteRunner:
    def __init__(self, suite_path: Path, opts: RunOptions):
        self.suite_path = suite_path
        self.opts = opts
        self.meta, self.tasks = load_suite(suite_path)
        if opts.only:
            self.tasks = [t for t in self.tasks if t.id in set(opts.only)]
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = self.meta.get("name") or suite_path.name
        base = opts.out_dir or (pland_home() / "eval_runs")
        label = f"-{opts.label}" if opts.label else ""
        self.run_dir = (base / f"{name}{label}-{stamp}").resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.home = self.run_dir / "home"
        self.rt = Runtime(self.home)
        self.records: list[dict[str, Any]] = []
        self.code_version = _code_version()  # captured at start: the code this process actually loaded
        self._events: list[dict[str, Any]] = []
        self._ev_lock = threading.Lock()
        self.rt.bus.subscribe(self._on_event)
        # Usage is attributed by the ledger's root run (one per top-level agent run, shared by its delegates), not
        # by time window: rows of a root that belongs to an earlier task (a late reflection, a straggler) never
        # count for a later one.
        self._done_roots: set[str] = set()
        # Task threads still alive after cancel + cancel_grace_s: their sessions stay cancelled, their ledger rows
        # and events are kept out of later tasks, and no later task starts in a workspace they can still write.
        self._stragglers: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ setup helpers
    def _on_event(self, ev: dict[str, Any]) -> None:
        with self._ev_lock:
            self._events.append(ev)

    def _settings_patch(self, task: Task) -> dict[str, Any]:
        patch: dict[str, Any] = {"max_iterations": task.max_iterations, "approvals": {"mode": "manual", "timeout": 120},
                                 "sandbox": {"backend": self.opts.backend}}
        model: dict[str, Any] = {}
        if self.opts.model:
            model["model"] = self.opts.model
        if self.opts.thinking is not None:
            model["thinking"] = self.opts.thinking
        if self.opts.reasoning:
            from ..llm.reasoning import to_settings

            model.update(to_settings(self.opts.reasoning))
        if model:
            patch["model"] = model
        if self.opts.memory == "off":
            patch.update({"reflection": False, "experience_top_k": 0,
                          "toolsets": ["files", "code", "web", "git", "plan", "hitl", "delegation", "team"]})
        return patch

    def _reset_memory(self, name: str) -> None:
        prof = self.rt.profiles.get(name)
        for f in ("MEMORY.md", "USER.md"):
            (prof.memories_dir / f).write_text("", encoding="utf-8")
        prof.db.execute("DELETE FROM experiences")
        for s in prof.skills_dir.glob("*.md"):
            s.unlink()

    def _fresh_workspace(self, name: str) -> Path:
        ws = self.rt.profiles.get(name).workspace
        for child in ws.iterdir():
            try:
                shutil.rmtree(child, onerror=_force_writable) if child.is_dir() and not child.is_symlink() else child.unlink()
            except OSError:
                # e.g. root-owned files written from a container: move them out of the way instead
                child.rename(self.run_dir / f"stale-{name}-{child.name}-{time.time_ns()}")
        return ws

    def _prepare(self, task: Task) -> dict[str, Any]:
        patch = self._settings_patch(task)
        involved: list[str]
        room = None
        if task.mode == "team":
            bots = task.team.get("bots") or []
            if not bots:
                raise ValueError(f"team task {task.id} has no bots")
            for b in bots:
                name = b["name"]
                fields = dict(title=b.get("title") or name, description=b.get("description") or "", soul=b.get("soul"))
                if self.rt.profiles.exists(name):
                    self.rt.profiles.update(name, **fields, settings=patch)
                else:
                    self.rt.profiles.create(name, bot=True, settings=patch, **fields)
            involved = [b["name"] for b in bots]
            lead = task.team.get("lead") or involved[0]
            primary = lead
            if task.team.get("room", True):
                room = self.rt.rooms.create(f"{task.id}-{int(time.time())}", involved, lead=lead)
        else:
            self.rt.profiles.update("default", settings=patch)
            involved = ["default"]
            primary = "default"
        for name in involved:
            if task.memory == "fresh":
                self._reset_memory(name)
            self._fresh_workspace(name)
        env_room = room["id"] if room else None
        # setup files / commands
        roots = CheckEnv(self.rt, primary, self.rt.profiles.get(primary).workspace, "", env_room,
                         env_room or f"dm:{primary}", [], [])
        for rel, content in (task.setup.get("files") or {}).items():
            p = roots.path(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content if isinstance(content, str) else json.dumps(content, indent=2), encoding="utf-8")
        for cmd in task.setup.get("commands") or []:
            r = subprocess.run(cmd, shell=True, cwd=str(roots.workspace), capture_output=True, text=True, timeout=120,
                               env=scrub_env({"GIT_AUTHOR_NAME": "setup", "GIT_AUTHOR_EMAIL": "setup@eval",
                                              "GIT_COMMITTER_NAME": "setup", "GIT_COMMITTER_EMAIL": "setup@eval"}),
                               executable="/bin/bash")
            if r.returncode != 0:
                raise RuntimeError(f"setup command failed: {cmd}: {r.stderr[-400:]}")
        return {"involved": involved, "primary": primary, "room": room}

    # ------------------------------------------------------------------ stragglers & usage attribution
    @staticmethod
    def _task_profiles(task: Task) -> set[str]:
        if task.mode == "team":
            return {b["name"] for b in task.team.get("bots") or []}
        return {"default"}

    def _settle_stragglers(self, profiles: set[str]) -> None:
        """Before a task starts: retire stragglers that have exited; wait (bounded) for live ones that work in one
        of this task's profiles, and refuse to start the task in a workspace one of them can still write to."""
        for s in list(self._stragglers):
            if s["thread"].is_alive() and s["profiles"] & profiles:
                s["thread"].join(self.opts.cancel_grace_s)
            if not s["thread"].is_alive():
                self._done_roots |= self._roots_of(s["sessions"], s["started"])
                self._stragglers.remove(s)
        busy = [s for s in self._stragglers if s["profiles"] & profiles]
        if busy:
            names = ", ".join("@" + n for n in sorted(busy[0]["profiles"] & profiles))
            raise RuntimeError(f"task {busy[0]['task_id']} is still running in the workspace of {names} after being "
                               "cancelled; not starting this task there")

    def _roots_of(self, sessions: set[tuple[str, str]], since: float) -> set[str]:
        if not sessions:
            return set()
        rows = self.rt.ledger.db.query("SELECT DISTINCT root_run, profile, session_id FROM llm_calls WHERE ts>=?", [since])
        return {r["root_run"] for r in rows if (r["profile"], r["session_id"]) in sessions}

    def _ledger_rows(self, since: float) -> list[dict[str, Any]]:
        return self.rt.ledger.db.query(
            "SELECT root_run, profile, session_id, model, prompt_tokens, cached_tokens, completion_tokens, duration"
            " FROM llm_calls WHERE ts>=?", [since])

    @staticmethod
    def _usage_totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Same figures as `Ledger.totals`, over the given rows."""
        by_model: dict[str, list[int]] = {}
        seconds = 0.0
        for r in rows:
            m = by_model.setdefault(r["model"], [0, 0, 0])
            m[0] += int(r["prompt_tokens"] or 0)
            m[1] += int(r["cached_tokens"] or 0)
            m[2] += int(r["completion_tokens"] or 0)
            seconds += float(r["duration"] or 0)
        prompt = sum(v[0] for v in by_model.values())
        cached = sum(v[1] for v in by_model.values())
        completion = sum(v[2] for v in by_model.values())
        return {"calls": len(rows), "prompt_tokens": prompt, "cached_tokens": cached, "completion_tokens": completion,
                "cache_hit_rate": round(cached / prompt, 3) if prompt else 0.0,
                "cost_usd": round(sum(cost(v[0], v[1], v[2], m) for m, v in by_model.items()), 5),
                "model_seconds": round(seconds, 1), "models": sorted(m for m in by_model if m)}

    def _memory_snapshot(self, names: list[str]) -> dict[str, Any]:
        snap = {}
        for n in names:
            prof = self.rt.profiles.get(n)
            notes = NotesMemory(prof)
            exps = ExperienceStore(prof).all()
            snap[n] = {"memory_chars": notes.usage("memory")[0], "user_chars": notes.usage("user")[0],
                       "memory_entries": len(notes.entries("memory")), "user_entries": len(notes.entries("user")),
                       "experiences": len(exps), "skills": len(SkillStore(prof).list()),
                       "experience_outcomes": {o: sum(1 for e in exps if e.outcome == o) for o in ("success", "partial", "failure")}}
        return snap

    # ------------------------------------------------------------------ one task
    def run_task(self, task: Task, pass_no: int = 1) -> dict[str, Any]:
        rec: dict[str, Any] = {"task_id": task.id, "title": task.title, "category": task.category, "mode": task.mode,
                               "pass": pass_no, "source": task.source}
        hitl = _hitl_for(task)
        try:
            self._settle_stragglers(self._task_profiles(task))
            env_info = self._prepare(task)
        except Exception as exc:
            rec.update(outcome="crashed", error=f"setup failed: {exc}", duration_s=0.0, checks=[], subtask_rate=0.0)
            return rec
        involved, primary, room = env_info["involved"], env_info["primary"], env_info["room"]
        mem_before = self._memory_snapshot(involved)
        with self._ev_lock:
            self._events.clear()
        box: dict[str, Any] = {}
        self.rt.cancel_everything(False)
        # what belongs to earlier tasks, fixed before this one starts
        foreign_sessions: set[tuple[str, str]] = set().union(*(s["sessions"] for s in self._stragglers))
        foreign_roots = set(self._done_roots)

        def work():
            try:
                if task.mode == "team" and room:
                    box["drive"] = self.rt.rooms.send(room["id"], task.prompt, hitl=hitl, background=False)["result"]
                elif task.mode == "team":
                    prof = self.rt.profiles.get(primary)
                    agent = self.rt.agent(prof, prof.canonical_chat_id(), hitl=hitl)
                    box["result"] = agent.run(task.prompt)
                else:
                    agent = self.rt.agent("default", hitl=hitl)
                    box["result"] = agent.run(task.prompt)
            except Exception as exc:
                box["exception"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=5)}"

        started = time.time()
        th = threading.Thread(target=work, name=f"eval-{task.id}", daemon=True)
        th.start()
        th.join(task.timeout)
        timed_out = th.is_alive()
        if timed_out:
            self.rt.cancel_everything(True)  # stays set while the thread winds down (bounded)
            th.join(self.opts.cancel_grace_s)
        duration = time.time() - started  # execution time ends when the final result is produced
        straggler = None
        if th.is_alive():
            # Still busy (a model call or a tool that does not poll cancellation). Keep its sessions cancelled once
            # the global flag is cleared for the next task, and remember them so nothing of it is counted there.
            with self._ev_lock:
                mine = {(e["profile"], e["session_id"]) for e in self._events
                        if e["type"] == "run.started" and e.get("profile") and e.get("session_id")}
            mine -= foreign_sessions
            for prof_name, sid in sorted(mine):
                self.rt.cancel(prof_name, sid)
            self._stragglers.append({"thread": th, "task_id": task.id, "profiles": set(self._task_profiles(task)),
                                     "sessions": mine, "started": started})
            straggler = {"alive_after_cancel_s": self.opts.cancel_grace_s, "sessions": sorted([list(x) for x in mine]),
                         "note": "the task's thread was still running after cancellation; its sessions stay cancelled, "
                                 "its later model usage and events are not counted for other tasks, and no task "
                                 "starts in its workspace while it runs"}
        self.rt.cancel_everything(False)
        self.rt.wait_reflections(180)  # post-task learning finishes before verification feeds back into it
        rows = self._ledger_rows(started)
        foreign_roots |= self._roots_of(foreign_sessions, min([started] + [s["started"] for s in self._stragglers]))
        session_roots: dict[tuple[str, str], set[str]] = {}
        for r in rows:
            session_roots.setdefault((r["profile"], r["session_id"]), set()).add(r["root_run"])

        def foreign(e: dict[str, Any]) -> bool:
            key = (e.get("profile"), e.get("session_id"))
            roots = session_roots.get(key)  # type: ignore[arg-type]
            return key in foreign_sessions or bool(roots and roots <= foreign_roots)

        with self._ev_lock:
            events = [e for e in self._events if not foreign(e)]

        # ---- final answer & run status
        answer, run_status, error = "", None, box.get("exception")
        sessions: list[tuple[str, str]] = []
        internal_errors: list[str] = []
        res = box.get("result")
        if res is not None:
            answer, run_status, error = res.text, res.status, error or res.error
            sessions.append((res.profile, res.session_id))
        elif room:
            msgs = self.rt.rooms.messages(room["id"])
            first_user = next((m["id"] for m in msgs if m["speaker"] == "user"), 0)
            bot_msgs = [m for m in msgs if m["id"] > first_user and m["kind"] == "message" and m["speaker"] not in ("user", "system")]
            answer = "\n\n".join(f"@{m['speaker']}: {m['content']}" for m in bot_msgs)
            finished = [e for e in events if e["type"] == "run.finished"]
            # A failed member/delegate run is a failure the team saw and could route around (the lead gets a failed
            # delegation back); only a failure of the room drive itself is a crash. Internal errors are kept below.
            run_status = "completed" if "drive" in box else ("error" if finished else None)
            internal_errors = [f"@{e.get('profile')}: {(e.get('error') or e.get('status'))}"[:300]
                               for e in finished if e.get("status") not in ("completed",)]
        for e in events:
            if e["type"] == "run.started" and e.get("profile") and e.get("session_id"):
                pair = (e["profile"], e["session_id"])
                if pair not in sessions:
                    sessions.append(pair)

        # ---- checks
        ws = self.rt.profiles.get(primary).workspace
        prof = self.rt.profiles.get(primary)
        env = CheckEnv(self.rt, primary, ws, answer, room["id"] if room else None,
                       room["id"] if room else f"dm:{primary}", hitl.log, events,
                       result={"run_status": run_status, "duration_s": duration},
                       backend=self.rt.backend_for(prof, prof.settings()))  # checks run in the task's sandbox
        checks = [run_check(env, c) for c in task.checks]
        total_w = sum(c["weight"] for c in checks)
        passed_w = sum(c["weight"] for c in checks if c["passed"])
        req = set(task.required_ids)
        req_ok = all(c["passed"] for c in checks if c["id"] in req)
        if timed_out:
            outcome = "timeout"
        elif error and run_status in (None, "error"):
            outcome = "crashed"
        elif not checks:
            outcome = "unverified"
        elif req_ok:
            outcome = "success"
        elif passed_w > 0:
            outcome = "partial"
        else:
            outcome = "failed"

        # ---- feed the verified outcome back into experience (ground-truth evolution)
        verified = {"success": "success", "partial": "partial"}.get(outcome, "failure")
        for prof_name, sid in sessions:
            try:
                prof = self.rt.profiles.get(prof_name)
                store = ExperienceStore(prof)
                store.set_outcome(sid, verified, note=f"eval {task.id}: {outcome}")
                meta = SessionStore(prof).get(sid).meta
                for fb in meta.get("feedback") or []:
                    store.correct_feedback(fb.get("used") or [], fb.get("self_outcome") == "success", verified == "success", sid)
            except Exception:
                pass

        mem_after = self._memory_snapshot(involved)
        rows = [r for r in self._ledger_rows(started) if r["root_run"] not in foreign_roots]
        self._done_roots |= {r["root_run"] for r in rows}
        usage = self._usage_totals(rows)
        tool_events = [e for e in events if e["type"] == "tool.finished"]
        rec.update(
            outcome=outcome, run_status=run_status, timed_out=timed_out, error=(error or "")[:2000] or None,
            duration_s=round(duration, 2), answer=answer[:6000],
            checks=checks, checks_passed=sum(1 for c in checks if c["passed"]), checks_total=len(checks),
            subtask_rate=round(passed_w / total_w, 4) if total_w else None, required=sorted(req),
            usage=usage, tool_calls=len(tool_events), tool_errors=sum(1 for e in tool_events if not e.get("ok")),
            tools_used=sorted({e["tool"] for e in tool_events}),
            hitl=hitl.log, delegations=[{k: e.get(k) for k in ("profile", "to", "status", "duration", "task_id")}
                                        for e in events if e["type"] == "delegation.finished"],
            experiences_retrieved=[{"profile": e.get("profile"), "ids": e.get("ids"), "scores": e.get("scores")}
                                   for e in events if e["type"] == "experience.retrieved"],
            experiences_added=[{"profile": e.get("profile"), "id": e.get("id"), "self_outcome": e.get("outcome"),
                                "lessons": e.get("lessons")} for e in events if e["type"] == "experience.added"],
            memory_before=mem_before, memory_after=mem_after, sessions=[list(s) for s in sessions],
            room_id=room["id"] if room else None, failure_mode=None, internal_errors=internal_errors,
            straggler=straggler,
        )
        rec["failure_mode"] = classify_failure(rec)
        self._save_task_artifacts(task, rec, events, involved, room, pass_no)
        return rec

    def _save_task_artifacts(self, task: Task, rec: dict, events: list[dict], involved: list[str], room, pass_no: int) -> None:
        sub = f"pass{pass_no}/{task.id}" if self.opts.passes > 1 else task.id
        tdir = self.run_dir / "tasks" / sub
        tdir.mkdir(parents=True, exist_ok=True)
        with open(tdir / "events.jsonl", "w", encoding="utf-8") as fh:
            for e in events:
                fh.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")
        (tdir / "result.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        lines = [f"# {task.id} — {rec['outcome']}", "", "## Prompt", "", task.prompt, ""]
        for prof_name, sid in rec.get("sessions") or []:
            prof = self.rt.profiles.get(prof_name)
            st = SessionStore(prof)
            lines += [f"## @{prof_name} · session {sid} ({st.get(sid).kind})", ""]
            for r in st.records(sid):
                m = r["message"]
                role = m.get("role")
                if role == "system":
                    continue
                if role == "user":
                    lines.append(f"**user:** {(r['meta'].get('display') or m.get('content') or '')[:3000]}\n")
                elif role == "assistant":
                    if m.get("content"):
                        lines.append(f"**assistant:** {m['content'][:3000]}\n")
                    for tc in m.get("tool_calls") or []:
                        lines.append(f"- `{tc['function']['name']}` {tc['function'].get('arguments', '')[:400]}")
                elif role == "tool":
                    lines.append(f"  - → {str(m.get('content', ''))[:600]!r}")
            lines.append("")
        if room:
            lines += ["## Room transcript", ""]
            for m in self.rt.rooms.messages(room["id"]):
                lines.append(f"- **{m['speaker']}** ({m['kind']}): {m['content'][:1500]}")
        (tdir / "transcript.md").write_text("\n".join(lines), encoding="utf-8")
        # keep the produced workspace(s) as evidence
        for name in involved:
            src = self.rt.profiles.get(name).workspace
            dst = tdir / "workspace" / name
            shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(".venv", "node_modules", "__pycache__"))
        if room:
            shutil.copytree(self.rt.rooms.shared_dir(room["id"]), tdir / "workspace" / "shared", dirs_exist_ok=True)

    # ------------------------------------------------------------------ suite
    def run(self, progress=None) -> dict[str, Any]:
        t0 = time.time()
        for p in range(1, self.opts.passes + 1):
            for i, task in enumerate(self.tasks, 1):
                if progress:
                    progress(f"[pass {p}] {i}/{len(self.tasks)} {task.id} …")
                rec = self.run_task(task, p)
                self.records.append(rec)
                if progress:
                    progress(f"    → {rec['outcome']} ({rec.get('checks_passed', 0)}/{rec.get('checks_total', 0)} checks, "
                             f"{rec['duration_s']}s)")
                self._write_results(time.time() - t0)
        summary = self._write_results(time.time() - t0)
        self.rt.shutdown()
        return summary

    def _write_results(self, wall: float) -> dict[str, Any]:
        summary = summarize(self.records)
        summary.update(suite=self.meta.get("name"), description=self.meta.get("description"), run_dir=str(self.run_dir),
                       wall_time_s=round(wall, 1), options={k: (str(v) if isinstance(v, Path) else v) for k, v in self.opts.__dict__.items()},
                       started=time.strftime("%Y-%m-%d %H:%M:%S"), code_version=self.code_version,
                       model=self.rt.profiles.get("default").settings().model.resolved().model)
        (self.run_dir / "results.json").write_text(json.dumps({"summary": summary, "tasks": self.records}, ensure_ascii=False,
                                                              indent=1, default=str), encoding="utf-8")
        from .report import render_report

        (self.run_dir / "report.md").write_text(render_report(summary, self.records), encoding="utf-8")
        return summary


def _force_writable(func, path, _exc) -> None:
    import os
    import stat

    os.chmod(os.path.dirname(path), stat.S_IRWXU)
    os.chmod(path, stat.S_IRWXU)
    func(path)


def _code_version() -> str:
    try:
        repo = Path(__file__).resolve().parents[2]
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo, capture_output=True, text=True, timeout=10)
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "pland"], cwd=repo, capture_output=True, text=True, timeout=10)
        return r.stdout.strip() + ("-dirty" if dirty.stdout.strip() else "") if r.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def classify_failure(rec: dict[str, Any]) -> str | None:
    if rec["outcome"] in ("success", "unverified"):
        return None
    if rec["outcome"] == "timeout":
        return "timeout"
    if rec["outcome"] == "crashed":
        return "crash: " + (rec.get("error") or "unknown").splitlines()[0][:120]
    if rec.get("run_status") in ("budget_exceeded", "loop_detected", "max_iterations"):
        return rec["run_status"]
    failed = [c for c in rec.get("checks") or [] if not c["passed"]]
    kinds = {c["type"] for c in failed}
    if kinds & {"hitl"}:
        return "HITL behaviour wrong (did not ask / asked when not needed)"
    if kinds & {"delegated", "board_tasks"}:
        return "no real delegation / task tracking"
    if kinds & {"memory_contains", "experience_count"}:
        return "memory not saved / not reused"
    if kinds & {"file_exists"} and all(c["type"] in {"file_exists", "file_contains", "python", "command"} for c in failed):
        return "deliverable missing"
    if kinds & {"command"}:
        return "verification tests failing"
    if kinds & {"git_commits", "git_clean"}:
        return "git workflow incomplete"
    if kinds & {"python", "file_contains", "file_not_contains", "answer_contains", "answer_not_contains"}:
        return "wrong or incomplete result"
    if kinds & {"file_absent"}:
        return "unwanted file state"
    return "checks failed"


def _pct(n: float, d: float) -> float | None:
    return round(100.0 * n / d, 1) if d else None


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    verified = [r for r in records if r["outcome"] != "unverified"]
    outcomes = {o: sum(1 for r in records if r["outcome"] == o) for o in ("success", "partial", "failed", "crashed", "timeout", "unverified")}
    total_w = sum(c["weight"] for r in verified for c in r.get("checks") or [])
    passed_w = sum(c["weight"] for r in verified for c in r.get("checks") or [] if c["passed"])
    durations = [r["duration_s"] for r in records if r.get("duration_s") is not None]
    usage_keys = ("calls", "prompt_tokens", "cached_tokens", "completion_tokens", "cost_usd")
    usage = {k: round(sum((r.get("usage") or {}).get(k, 0) for r in records), 5) for k in usage_keys}
    usage["cache_hit_rate"] = round(usage["cached_tokens"] / usage["prompt_tokens"], 3) if usage["prompt_tokens"] else 0.0

    def group(key):
        out = {}
        for val in sorted({r.get(key) for r in records}, key=str):
            rs = [r for r in records if r.get(key) == val and r["outcome"] != "unverified"]
            if not rs:
                continue
            tw = sum(c["weight"] for r in rs for c in r["checks"])
            pw = sum(c["weight"] for r in rs for c in r["checks"] if c["passed"])
            out[str(val)] = {"tasks": len(rs), "goal_rate": _pct(sum(r["outcome"] == "success" for r in rs), len(rs)),
                             "subtask_rate": _pct(pw, tw), "mean_time_s": round(statistics.mean(r["duration_s"] for r in rs), 1)}
        return out

    failure_modes: dict[str, int] = {}
    for r in records:
        if r.get("failure_mode"):
            failure_modes[r["failure_mode"]] = failure_modes.get(r["failure_mode"], 0) + 1
    with_exp = [r for r in verified if r.get("experiences_retrieved")]
    without_exp = [r for r in verified if not r.get("experiences_retrieved")]
    return {
        "tasks": len(records),
        "verified_tasks": len(verified),
        "outcomes": outcomes,
        "goal_completion_rate": _pct(outcomes["success"], len(verified)),
        "subtask_completion_rate": _pct(passed_w, total_w),
        "crash_rate": _pct(outcomes["crashed"], len(records)),
        "time": {
            "total_s": round(sum(durations), 1),
            "mean_s": round(statistics.mean(durations), 1) if durations else None,
            "median_s": round(statistics.median(durations), 1) if durations else None,
            "p90_s": round(sorted(durations)[max(0, math.ceil(len(durations) * 0.9) - 1)], 1) if durations else None,
            "max_s": round(max(durations), 1) if durations else None,
        },
        "usage": usage,
        "by_category": group("category"),
        "by_mode": group("mode"),
        "by_pass": group("pass"),
        "failure_modes": failure_modes,
        "memory_effect": {
            "tasks_with_retrieved_experience": len(with_exp),
            "goal_rate_with_experience": _pct(sum(r["outcome"] == "success" for r in with_exp), len(with_exp)),
            "tasks_without_retrieved_experience": len(without_exp),
            "goal_rate_without_experience": _pct(sum(r["outcome"] == "success" for r in without_exp), len(without_exp)),
        },
        "hitl_requests": sum(len(r.get("hitl") or []) for r in records),
        "delegations": sum(len(r.get("delegations") or []) for r in records),
    }


def run_suite(suite: str | Path, opts: RunOptions, progress=None) -> tuple[SuiteRunner, dict[str, Any]]:
    from .tasks import resolve_suite

    runner = SuiteRunner(resolve_suite(str(suite)), opts)
    try:
        summary = runner.run(progress)
    finally:
        DB.close_all()
    return runner, summary


def load_results(path: Path) -> dict[str, Any]:
    p = path / "results.json" if path.is_dir() else path
    return loads(p.read_text(encoding="utf-8"), {})
