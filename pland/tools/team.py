"""Collaboration tools: delegation, bot-to-bot messages, the team task board, explicit file sharing."""

from __future__ import annotations

from ..team.delegation import DelegationError, board_scope, copy_files, delegate, message_agent
from .registry import ToolContext, ToolError, obj, tool

_TASK = {
    "type": "object",
    "properties": {
        "goal": {"type": "string", "description": "self-contained description of the subtask"},
        "to": {"type": "string", "description": "teammate name to execute it; omit for a temporary subagent of yourself"},
        "context": {"type": "string", "description": "everything the delegate needs to know (it cannot see your conversation)"},
        "files": {"type": "array", "items": {"type": "string"}, "description": "workspace files/folders to copy to the delegate"},
        "expected_output": {"type": "string"},
        "task_id": {"type": "string", "description": "existing team-board task this delegation fulfils"},
    },
    "required": ["goal"],
    "additionalProperties": False,
}


@tool(
    "delegate_task",
    "Hand subtasks to teammates (to=<name>) or to temporary subagents of yourself (omit `to`). Each delegate really "
    "executes the task with its own tools and returns a report. Pass several independent tasks in `tasks` to run them "
    "in parallel. Each task is tracked on the team board.",
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
    "update(task_id, status?, result?, assignee?), list().",
    obj({"action": {"type": "string", "enum": ["add", "update", "list"]}, "title": {"type": "string"},
         "description": {"type": "string"}, "assignee": {"type": "string"},
         "depends_on": {"type": "array", "items": {"type": "string"}}, "task_id": {"type": "string"},
         "status": {"type": "string", "enum": ["todo", "in_progress", "done", "failed", "blocked"]},
         "result": {"type": "string"}}, ["action"]),
    "team",
)
def team_tasks(ctx: ToolContext, a):
    board = ctx.runtime.board
    scope = board_scope(ctx)
    action = a["action"]
    if action == "add":
        if not a.get("title"):
            raise ToolError("title is required")
        assignee = (a.get("assignee") or "").lstrip("@") or None
        if assignee and not ctx.runtime.profiles.exists(assignee):
            raise ToolError(f"no agent named {assignee}")
        t = board.add(scope, a["title"], description=a.get("description") or "", assignee=assignee,
                      created_by=ctx.profile.name, depends_on=a.get("depends_on"))
        return f"added {t['id']}\n" + board.render(scope)
    if action == "update":
        if not a.get("task_id"):
            raise ToolError("task_id is required")
        board.update(a["task_id"], status=a.get("status"), result=a.get("result"),
                     assignee=(a.get("assignee") or "").lstrip("@") or None)
        return board.render(scope)
    return board.render(scope)


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
