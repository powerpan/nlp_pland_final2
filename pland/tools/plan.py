"""Session-scoped task list: the agent's own plan for multi-step work.

The list lives in the session's metadata, survives context compaction (it is re-injected with the
summary) and is shown live in the UI. It is a working plan for one agent; the team board
(`team_tasks`) is the shared record across agents.
"""

from __future__ import annotations

from .registry import ToolContext, ToolError, obj, tool

STATUSES = ("pending", "in_progress", "completed", "cancelled")
MARK = {"completed": "[x]", "in_progress": "[>]", "pending": "[ ]", "cancelled": "[~]"}
MAX_ITEMS = 60


def render(items: list[dict]) -> str:
    if not items:
        return "(no tasks)"
    done = sum(1 for t in items if t["status"] == "completed")
    lines = [f"{MARK.get(t['status'], '[ ]')} {t['id']}. {t['content']}" for t in items]
    return f"Task list ({done}/{len(items)} done):\n" + "\n".join(lines)


def get(ctx_or_store, session_id: str) -> list[dict]:
    return list((ctx_or_store.get(session_id).meta or {}).get("todos") or [])


@tool(
    "todo",
    "Your task list for this conversation. For work with 3+ steps, write the plan first, keep exactly one item "
    "in_progress, and mark items completed as you verify them. Pass `todos` to write (replaces the list; with "
    "merge=true updates items by id), omit it to read. Always returns the full list.",
    obj({"todos": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "content": {"type": "string"},
            "status": {"type": "string", "enum": list(STATUSES)}}, "required": ["id"], "additionalProperties": False}},
         "merge": {"type": "boolean"}}),
    "plan",
)
def todo(ctx: ToolContext, a):
    store = ctx.agent.sessions
    current = get(store, ctx.session_id)
    if a.get("todos") is None:
        return render(current)
    incoming = a["todos"]
    if a.get("merge"):
        by_id = {t["id"]: dict(t) for t in current}
        for t in incoming:
            if t["id"] in by_id:
                by_id[t["id"]].update({k: v for k, v in t.items() if v is not None})
            else:
                if not t.get("content"):
                    raise ToolError(f"new item {t['id']} needs content")
                by_id[t["id"]] = {"id": t["id"], "content": t["content"], "status": t.get("status", "pending")}
        items = list(by_id.values())
    else:
        items = []
        for t in incoming:
            if not t.get("content"):
                raise ToolError(f"item {t.get('id')} needs content")
            items.append({"id": str(t["id"]), "content": str(t["content"])[:500], "status": t.get("status") or "pending"})
    if len(items) > MAX_ITEMS:
        raise ToolError(f"at most {MAX_ITEMS} items")
    for t in items:
        if t["status"] not in STATUSES:
            raise ToolError(f"status must be one of {STATUSES}")
    store.patch_meta(ctx.session_id, {"todos": items})
    ctx.emit("todo.updated", todos=items)
    return render(items)
