"""Collaboration tools: delegation, bot-to-bot messages, the team task board, explicit file sharing."""

from __future__ import annotations

from ..team.delegation import DelegationError, board_scope, copy_files, delegate, message_agent
from ..team.fast import set_scope
from .registry import ToolContext, ToolError, obj, tool

_TASK = {
    "type": "object",
    "properties": {
        "goal": {"type": "string", "description": "self-contained description of the subtask"},
        "purpose": {"type": "string", "enum": ["work", "review"], "description": "Use review for independent sign-off. Use work for authoring, repairs or advisory work."},
        "to": {"type": "string", "description": "teammate name; omitted on planned work uses its card owner, otherwise a temporary subagent"},
        "context": {"type": "string", "description": "everything the delegate needs to know (it cannot see your conversation)"},
        "files": {"type": "array", "items": {"type": "string"}, "description": "workspace files/folders to copy to the delegate"},
        "expected_output": {"type": "string", "description": "What the recipient needs to proceed. List only the paths being delivered. "
                            "Leave team size estimates out of this field."},
        "requirement_source": {"type": "string", "description": "For a binding constraint, quote or identify the user request, task specification or concrete destination limit and the deliverable it governs."},
        "review": {
            "type": "object",
            "description": "For a bounded independent review of shared files. A PASS only applies to those exact versions.",
            "properties": {
                "inputs": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 8},
                "fresh": {"type": "boolean", "description": "Require a fresh observation when acceptance depends on changing external state."},
                "criterion": {"type": "string", "description": "Stable user requirement. On an existing card omit to inherit it; use goal/context for the focus of a revision."},
                "observation": {"type": "string", "description": "Outcome to observe in use. Omit on revisions to inherit it. In goal say which edits may affect it."},
                "report": {"type": "string", "description": "The shared/ Markdown evidence file for this card. Use a distinct path for each independent review."},
                "max_steps": {"type": "integer", "minimum": 1, "maximum": 200,
                              "description": "Optional shorter step limit within the platform's review ceiling"},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 900,
                                    "description": "Optional shorter timeout within the platform's review ceiling"},
            },
            "required": ["inputs", "report"],
            "additionalProperties": False,
        },
        "task_id": {"type": "string", "description": "existing team-board task this delegation fulfils"},
    },
    "required": ["goal"],
    "additionalProperties": False,
}


@tool(
    "delegate_task",
    "Hand subtasks to teammates (to=<name>) or to temporary subagents of yourself (omit `to`). Prefer the teammate whose "
    "role fits the subtask (e.g. review → a reviewer, research → a researcher); temporary subagents are for generic "
    "chores no teammate owns. Each delegate really executes the task with its own tools and returns a report. Pass several independent tasks in `tasks` to run them "
    "in parallel. Ask the user in a separate turn before sending work that needs their answer. For an independent "
    "review in a group, use review={criterion,inputs:[shared/...],report:shared/...}. Pass the planned task_id from "
    "the first review through revisions. Use review.observation for outcomes that must be verified in use. "
    "Check the board before delegating a review. Reuse current evidence for the same criteria and review only changes. "
    "Pass `task_id` for planned work. An exact, unique match to the current plan's declared output files also links its card. "
    "The card status and result are updated for you.",
    obj({"tasks": {"type": "array", "items": _TASK, "minItems": 1, "maxItems": 8}}, ["tasks"]),
    "delegation",
)
def delegate_task(ctx: ToolContext, a):
    try:
        return delegate(ctx, a["tasks"])
    except DelegationError as exc:
        raise ToolError(str(exc))


@tool(
    "message_agent",
    "Send a direct message to a teammate's Bot Chat and wait for its reply (questions, reviews, quick asks). "
    "For substantial work use delegate_task.",
    obj({"target": {"type": "string"}, "message": {"type": "string"}}, ["target", "message"]),
    "team",
)
def message_agent_tool(ctx: ToolContext, a):
    try:
        return message_agent(ctx, a["target"], a["message"])
    except DelegationError as exc:
        raise ToolError(str(exc))


@tool(
    "team_tasks",
    "The team task board (scoped to the current group room, or to you outside rooms). Use it to decompose a goal "
    "into subtasks and track ownership/status. actions: add(title, description?, assignee?, depends_on?), "
    "update(task_id, status?, result?, assignee?), list(). Tasks you hand out with delegate_task(task_id=...) are "
    "updated automatically; use update only for work you do yourself. Add several tasks with parallel calls. "
    "`files` and `checks` record a card's acceptance scope: the files it delivers and the commands that accept them "
    "(used by Fast Mode's run_checks). Use flag_conflict only when concrete evidence contradicts an active instruction or source and the outcome still depends on resolving it. It "
    "records both alternatives and their source. Resolve it via delegate_task review on that ID. "
    "For a clearly independent new request, separate_request(task_id, description) sets aside an earlier "
    "unrelated conflict for this request only. Explain the difference in scope.",
    obj({"action": {"type": "string", "enum": ["add", "update", "list", "flag_conflict", "separate_request"]}, "title": {"type": "string"},
         "source": {"type": "string", "description": "For flag_conflict only: the specific source, version or shared file which contradicts a working assumption. Describe both alternatives in description."},
         "description": {"type": "string"}, "assignee": {"type": "string"},
         "depends_on": {"type": "array", "items": {"type": "string"},
                        "description": "IDs or displayed numbers of existing tasks on this board. Use IDs when planning in parallel."},
         "task_id": {"type": "string"},
         "status": {"type": "string", "enum": ["todo", "in_progress", "done", "failed", "blocked"]},
         "result": {"type": "string"},
         "files": {"type": "array", "items": {"type": "string"}, "maxItems": 60},
         "check_inputs": {"type": "array", "items": {"type": "string"}, "maxItems": 60,
                          "description": "Register scripts, fixtures and other inputs read by checks; these are versioned separately from deliverables."},
         "checks": {"type": "array", "items": {"type": "string"}, "maxItems": 8}}, ["action"]),
    "team",
)
def team_tasks(ctx: ToolContext, a):
    board = ctx.runtime.board
    scope = board_scope(ctx)
    action = a["action"]
    if action in {"add", "flag_conflict"}:
        conflict = action == "flag_conflict"
        source = (a.get("source") or "").strip() if conflict else None
        if conflict and (not ctx.room_id or not source or not (a.get("description") or "").strip()):
            raise ToolError("A group evidence conflict needs the conflicting alternatives in description and a specific source.")
        if not a.get("title"):
            raise ToolError("title is required")
        assignee = (a.get("assignee") or "").lstrip("@") or None
        if assignee and not ctx.runtime.profiles.exists(assignee):
            raise ToolError(f"no agent named {assignee}")
        t = board.add(scope, a["title"], description=a.get("description") or "", assignee=assignee,
                      created_by=ctx.profile.name, depends_on=a.get("depends_on"), conflict_source=source)
        if conflict and (turn := ctx.agent.budget.team_turn):
            turn.track(t["id"])
        if conflict and source.startswith("shared/"):
            try:
                if ctx.paths.resolve(source).is_file():
                    a = {**a, "check_inputs": list(dict.fromkeys([*(a.get("check_inputs") or []), source]))}
            except (ValueError, OSError, RuntimeError):
                pass  # Free-text locators may include a passage or edition.
        _set_scope(ctx, t["id"], a)
        return f"added {t['id']}\n" + board.render(scope)
    if action == "separate_request":
        turn = ctx.agent.review_turn
        if turn is None:
            raise ToolError("Only the lead of the current request can set its scope.")
        try:
            turn.separate_request(a.get("task_id") or "", a.get("description") or "")
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        return "Independent request noted. The earlier dispute remains open on its original card."
    if action == "update":
        if not a.get("task_id"):
            raise ToolError("task_id is required")
        task = board.get(a["task_id"])
        if task["room_id"] != scope:
            raise ToolError("task does not belong to this board")
        if (task.get("review") or task.get("conflict_source")) and any(a.get(field) is not None for field in ("status", "result", "assignee")):
            raise ToolError("review results are recorded by the review; delegate a focused follow-up for changed files")
        board.update(task["id"], status=a.get("status"), result=a.get("result"),
                     assignee=(a.get("assignee") or "").lstrip("@") or None)
        _set_scope(ctx, a["task_id"], a)
        return board.render(scope)
    return board.render(scope)


def _set_scope(ctx: ToolContext, task_id: str, a) -> None:
    try:
        set_scope(ctx, task_id, a.get("files"), a.get("checks"), a.get("check_inputs"))
    except Exception as exc:  # noqa: BLE001 - a path outside the allowed folders
        raise ToolError(f"files: {exc}")


@tool(
    "share_file",
    "Explicitly share files from your workspace: to='room' copies into the group room's shared folder; "
    "to='<agent>' copies into that agent's workspace under inbox/from-<you>/.",
    obj({"paths": {"type": "array", "items": {"type": "string"}, "minItems": 1}, "to": {"type": "string"}}, ["paths", "to"]),
    "team",
)
def share_file(ctx: ToolContext, a):
    to = a["to"].strip().lstrip("@")
    if to == "room":
        if not ctx.room_id:
            raise ToolError("you are not in a group room")
        dest = ctx.runtime.rooms.shared_dir(ctx.room_id)
        label = "shared/"
    else:
        if not ctx.runtime.profiles.exists(to):
            raise ToolError(f"no agent named {to}")
        dest = ctx.runtime.profiles.get(to).workspace / f"inbox/from-{ctx.profile.name}"
        label = f"@{to}:inbox/from-{ctx.profile.name}/"
    try:
        names = copy_files(ctx, a["paths"], dest)
    except DelegationError as exc:
        raise ToolError(str(exc))
    ctx.emit("file.shared", to=to, files=names)
    return f"Shared {', '.join(names)} → {label}"
