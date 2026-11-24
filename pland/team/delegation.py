"""Real task delegation between agents.

`delegate(ctx, tasks)` executes each task by actually running another agent loop:
* `to=<bot>` — the named teammate works in a fresh *delegation* session of its own profile: its own
  persona, memory, experiences, tools and private workspace. Only what the delegator passes
  explicitly (goal, context, attached files, and the room's shared folder when inside a room)
  crosses the boundary.
* no `to`   — a temporary subagent of the delegator itself (fresh context, same workspace, no
  human channel, no long-term memory writes).
Independent tasks in one call run in parallel threads. Each task can be linked to a team-board
entry, whose status/result are kept in sync. Delegation chains are tracked to stop cycles
(A→B→A) and bounded by `max_delegation_depth`.
"""

from __future__ import annotations

import re

import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..sessions import SessionStore
from ..store import dumps, new_id, now

if TYPE_CHECKING:
    from ..tools.registry import ToolContext


class DelegationError(ValueError):
    pass


def board_scope(ctx: "ToolContext") -> str:
    return ctx.room_id or f"dm:{ctx.profile.name}"


def copy_files(ctx: "ToolContext", paths: list[str], dest: Path) -> list[str]:
    copied = []
    for raw in paths or []:
        src = ctx.paths.resolve(raw)
        if not src.exists():
            raise DelegationError(f"attached file {raw!r} does not exist")
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / src.name
        if src.is_dir():
            shutil.copytree(src, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv"))
        else:
            shutil.copy2(src, target)
        copied.append(target.name)
    return copied


# What comes back from a teammate: the files it was asked for and the ones it wrote, at most this many / this large.
MAX_RETURN_FILES = 12
MAX_RETURN_BYTES = 20 * 1024 * 1024
# Run outcomes that stop a worker before it finishes; with every requested file written, the board counts it as done.
STOPPED_EARLY = {"max_iterations", "loop_detected", "budget_exceeded"}


def return_files(ctx: "ToolContext", worker: Any, to: str) -> list[str]:
    """Copy what a teammate produced into the delegator's folder, under inbox/from-<to>/ with the same relative paths:
    the files named as expected output plus the files it wrote in this run. Without this a lead had to message each
    teammate afterwards to ask for its file (16 extra model calls for one researcher, in the teammate's private chat).
    Files in the room's shared folder are skipped (the team already sees them), as are copies of the delegator's own
    attachments (inbox/)."""
    wanted = list(dict.fromkeys([*worker._deliverables, *worker.written_paths]))
    home = Path(worker.workspace).resolve()
    dest = Path(ctx.agent.workspace) / "inbox" / f"from-{to}"
    out: list[str] = []
    for rel in wanted:
        if len(out) >= MAX_RETURN_FILES:
            break
        try:
            src = worker.paths.resolve(rel)
            inside = src.relative_to(home)
        except Exception:  # noqa: BLE001 - outside the teammate's workspace (shared/) or refused by its path policy
            continue
        if inside.parts[:1] == ("inbox",) or not src.is_file():
            continue
        size = src.stat().st_size
        if size == 0 or size > MAX_RETURN_BYTES:
            continue
        target = dest / inside
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        out.append((Path("inbox") / f"from-{to}" / inside).as_posix())
    return out


def _requested_files_written(worker: Any) -> bool:
    """Every file the delegator named as expected output exists and is not empty (False when none were named)."""
    return bool(worker._deliverables) and not worker._missing_deliverables()


def _prerequisites(ctx: "ToolContext", task_id: str | None) -> list[dict[str, Any]]:
    if not task_id:
        return []
    out = []
    for dep in ctx.runtime.board.get(task_id).get("depends_on") or []:
        try:
            out.append(ctx.runtime.board.get(dep))
        except KeyError:
            continue
    return out


_FILE_PATH = re.compile(r"(?<![\w:/.\-~])((?:~/|/|\.{1,2}/)?[\w.\-]+(?:/[\w.\-]+)*\.[A-Za-z][A-Za-z0-9]{1,5})\b")


def deliverables(task: dict[str, Any]) -> list[str]:
    """File paths the delegator named as the expected output (the worker's checkpoint and step limit check them)."""
    text = re.sub(r"(?:https?://|www\.)\S+", " ", str(task.get("expected_output") or ""))  # URLs are not files
    found = [m.group(1) for m in _FILE_PATH.finditer(text)]
    return list(dict.fromkeys(found))[:5]


def _message_for(ctx: "ToolContext", task: dict[str, Any], inbox_rel: str | None, attached: list[str]) -> str:
    sender = ctx.profile
    parts = [f"Task delegated to you by 🤖 {sender.title} (@{sender.name}).", f"\nGOAL:\n{task['goal'].strip()}"]
    if task.get("context"):
        parts.append(f"\nCONTEXT:\n{task['context'].strip()}")
    deps = [d for d in _prerequisites(ctx, task.get("task_id")) if d.get("result")]
    if deps:  # completed prerequisite work flows forward with the task, like a kanban parent link
        parts.append("\nRESULTS OF PREREQUISITE TASKS:")
        for d in deps:
            parts.append(f"### {d['id']} — {d['title']} (by @{d.get('assignee') or '?'}, {d['status']})\n{str(d['result'])[:2500]}")
    if attached:
        parts.append(f"\nATTACHED FILES (copied into your workspace under {inbox_rel}/): " + ", ".join(attached))
    if ctx.room_id:
        parts.append("\nThe group room's shared folder is available as `shared/` — put deliverables the team needs there.")
    if task.get("expected_output"):
        parts.append(f"\nEXPECTED OUTPUT:\n{task['expected_output'].strip()}")
    if inbox_rel is not None:
        parts.append(f"\nFiles you write for this task are copied back to @{sender.name} automatically when you finish; "
                     "you do not need to share them.")
    parts.append("\nWork autonomously and verify your result. End with a concise report: what you did, the result with "
                 "evidence, files produced (paths), open issues.")
    return "\n".join(parts)


def _run_one(ctx: "ToolContext", task: dict[str, Any]) -> dict[str, Any]:
    from ..agent import Agent

    rt = ctx.runtime
    goal = (task.get("goal") or "").strip()
    if not goal:
        raise DelegationError("each task needs a goal")
    to = (task.get("to") or "").strip().lstrip("@") or None
    if to == ctx.profile.name:
        to = None
    board = rt.board
    scope = board_scope(ctx)
    tid = task.get("task_id")
    prior: dict[str, Any] | None = None
    if tid:
        prior = board.get(tid)  # validates the id; a re-delegation of finished work must not erase its result
        pending = [d for d in _prerequisites(ctx, tid) if d["status"] != "done"]
        if pending:
            raise DelegationError("task " + tid + " depends on unfinished tasks: " +
                                  ", ".join(f"{d['id']} ({d['status']})" for d in pending) +
                                  ". Delegate those first (independent ones together), then this one.")
        board.update(tid, status="in_progress", assignee=to or ctx.profile.name)
    elif task.get("track", True):
        tid = board.add(scope, goal[:120], description=(task.get("context") or "")[:2000], assignee=to or ctx.profile.name,
                        created_by=ctx.profile.name)["id"]
        board.update(tid, status="in_progress")
    started = time.time()
    delivery = new_id("d_")
    rt.shared.execute(
        "INSERT INTO deliveries(id, sender, target, kind, payload, status, created, updated) VALUES (?,?,?,?,?,?,?,?)",
        (delivery, ctx.profile.name, to or f"{ctx.profile.name}/subagent", "delegation", dumps(task), "running", now(), now()),
    )
    ctx.emit("delegation.started", delivery_id=delivery, to=to or "subagent", goal=goal[:300], task_id=tid)
    if ctx.room_id:
        rt.rooms.post(ctx.room_id, ctx.profile.name, f"→ delegated to {('@' + to) if to else 'a subagent'}: {goal[:200]}",
                      kind="activity", meta={"delegation": delivery, "task_id": tid})
    try:
        if to:
            if not rt.profiles.exists(to):
                names = ", ".join(p.name for p in rt.profiles.list(bots_only=True))
                raise DelegationError(f"no teammate named '{to}'. Available: {names or '(none)'}")
            if to in ctx.chain:
                raise DelegationError(f"@{to} is already working on the task that led here (delegation cycle "
                                      f"{' → '.join(ctx.chain + [to])}). Do this part yourself or report back.")
            target = rt.profiles.get(to)
            inbox_rel = f"inbox/from-{ctx.profile.name}"
            attached = copy_files(ctx, task.get("files") or [], target.workspace / inbox_rel)
            sess = SessionStore(target).create(title=f"From @{ctx.profile.name}: {goal[:60]}", kind="delegation",
                                               room_id=ctx.room_id, meta={"from": ctx.profile.name, "task_id": tid, "delivery": delivery,
                                                                          "deliverables": deliverables(task)})
            agent = Agent(rt, target, sess.id, hitl=ctx.hitl, room_id=ctx.room_id, role="delegate",
                          depth=ctx.depth + 1, chain=ctx.chain, budget=ctx.agent.budget)
            result = agent.run(_message_for(ctx, task, inbox_rel, attached),
                               task_text=f"{goal}\n{task.get('context') or ''}".strip())
            returned = return_files(ctx, agent, to)
        else:
            sess = SessionStore(ctx.profile).create(title=f"Subagent: {goal[:60]}", kind="subagent", room_id=ctx.room_id,
                                                    meta={"parent_session": ctx.session_id, "task_id": tid,
                                                          "deliverables": deliverables(task),
                                                          # a temporary subagent thinks like the chat that spawned it
                                                          "reasoning": ctx.agent.reasoning,
                                                          "model": ctx.agent.model_override,
                                                          # ...and works in the same folder
                                                          "workspace": str(ctx.agent.workspace) if ctx.agent.custom_workspace else None})
            agent = Agent(rt, ctx.profile, sess.id, hitl=ctx.hitl, room_id=ctx.room_id, role="subagent",
                          depth=ctx.depth + 1, chain=ctx.chain[:-1], reflect=False, budget=ctx.agent.budget)
            result = agent.run(_message_for(ctx, task, None, []))
            returned = []  # a subagent works in the delegator's own folder
        delivered = _requested_files_written(agent)
        status = "done" if result.status == "completed" or (result.status in STOPPED_EARLY and delivered) else "failed"
        out = {"to": to or "subagent", "task_id": tid, "status": result.status, "session_id": result.session_id,
               "duration_s": round(time.time() - started, 1), "report": result.text[:8000]}
        if result.status != "completed" and delivered:
            out["note"] = (f"stopped early ({result.status}), but the requested file(s) were written: "
                           f"{', '.join(agent._deliverables)} — check that they are complete")
        if returned:
            out["files_in_your_folder"] = returned
    except DelegationError as exc:
        status = "failed"
        out = {"to": to or "subagent", "task_id": tid, "status": "rejected", "error": str(exc)}
    except Exception as exc:
        status = "failed"
        out = {"to": to or "subagent", "task_id": tid, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
    out["run_budget"] = ctx.agent.budget.describe()
    if tid:
        if status == "failed" and prior is not None and prior["status"] == "done":
            # A follow-up (another review round, a fix) that stopped or was refused does not undo finished work.
            if out["status"] != "rejected":
                board.update(tid, status="done", result=f"[A follow-up run stopped ({out['status']}) before finishing; "
                             f"the earlier result below still stands.]\n{prior.get('result') or ''}")
            else:
                board.update(tid, status="done")
        else:
            text = out.get("report") or out.get("error")
            board.update(tid, status=status, result=f"[{out['note']}]\n{text}" if out.get("note") else text)
    rt.shared.execute("UPDATE deliveries SET status=?, reply=?, updated=? WHERE id=?",
                      ("done" if status == "done" else "failed", dumps(out), now(), delivery))
    ctx.emit("delegation.finished", delivery_id=delivery, to=to or "subagent", status=out["status"], task_id=tid,
             duration=out.get("duration_s"), report=(out.get("report") or out.get("error") or "")[:1500])
    if ctx.room_id:
        summary = (out.get("report") or out.get("error") or "")[:400]
        rt.rooms.post(ctx.room_id, to or ctx.profile.name,
                      f"✓ finished delegated task: {goal[:120]}\n{summary}" if status == "done" else f"✗ delegated task failed: {goal[:120]}\n{summary}",
                      kind="activity", meta={"delegation": delivery, "task_id": tid})
    return out


def delegate(ctx: "ToolContext", tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not tasks:
        raise DelegationError("no tasks given")
    if len(tasks) > 8:
        raise DelegationError("at most 8 tasks per call")
    if ctx.depth + 1 > ctx.settings.max_delegation_depth:
        raise DelegationError("maximum delegation depth reached; do the work yourself")
    if ctx.agent.budget.near_limit:
        raise DelegationError("the run budget is nearly exhausted; finish with what you have")
    if len(tasks) == 1:
        return [_safe_run_one(ctx, tasks[0])]
    workers = max(1, min(ctx.settings.max_parallel_delegations, len(tasks)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="delegate") as pool:
        futures = [pool.submit(_safe_run_one, ctx, t) for t in tasks]
        return [f.result() for f in futures]


def _safe_run_one(ctx: "ToolContext", task: dict[str, Any]) -> dict[str, Any]:
    """One rejected task (bad target, unfinished prerequisites) must not sink its siblings in the batch."""
    try:
        return _run_one(ctx, task)
    except (DelegationError, KeyError) as exc:
        return {"to": task.get("to") or "subagent", "task_id": task.get("task_id"), "status": "rejected", "error": str(exc)}


def message_agent(ctx: "ToolContext", target: str, message: str, timeout: float = 900) -> dict[str, Any]:
    """Synchronous bot-to-bot message, delivered into the target's canonical Bot Chat."""
    from ..agent import Agent

    rt = ctx.runtime
    target = target.strip().lstrip("@")
    if not rt.profiles.exists(target):
        names = ", ".join(p.name for p in rt.profiles.list(bots_only=True))
        raise DelegationError(f"no agent named '{target}'. Available: {names or '(none)'}")
    if target == ctx.profile.name:
        raise DelegationError("you cannot message yourself")
    if target in ctx.chain:
        raise DelegationError(f"@{target} is waiting on you right now; answer in your own reply instead of messaging it")
    if ctx.agent.budget.near_limit:
        raise DelegationError("the run budget is nearly exhausted; finish with what you have")
    prof = rt.profiles.get(target)
    sid = prof.canonical_chat_id()
    lock = rt.session_lock(target, sid)
    if lock.locked():
        ctx.emit("message.queued", to=target)
    sender = ctx.profile
    delivery = new_id("d_")
    rt.shared.execute(
        "INSERT INTO deliveries(id, sender, target, kind, payload, status, created, updated) VALUES (?,?,?,?,?,?,?,?)",
        (delivery, sender.name, target, "message", dumps({"message": message}), "running", now(), now()),
    )
    ctx.emit("message.sent", to=target, delivery_id=delivery, message=message[:1000])
    agent = Agent(rt, prof, sid, hitl=ctx.hitl, depth=ctx.depth + 1, chain=ctx.chain, budget=ctx.agent.budget)
    result = agent.run(f"Message from 🤖 {sender.title} (@{sender.name}):\n{message}",
                       meta={"from_agent": sender.name, "delivery": delivery})
    rt.shared.execute("UPDATE deliveries SET status=?, reply=?, updated=? WHERE id=?",
                      ("done" if result.ok else "failed", result.text[:8000], now(), delivery))
    ctx.emit("message.replied", to=target, delivery_id=delivery, status=result.status, reply=result.text[:1500])
    return {"to": target, "status": result.status, "reply": result.text[:8000], "run_budget": ctx.agent.budget.describe()}
