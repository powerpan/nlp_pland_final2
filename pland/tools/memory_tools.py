"""Memory, experience and skill tools (scoped to the calling agent's own profile)."""

from __future__ import annotations

from ..memory import ExperienceStore, MemoryError_, NotesMemory, SkillStore
from .registry import ToolContext, ToolError, obj, tool


@tool(
    "memory",
    "Manage your persistent notes. target='memory' for facts/conventions/lessons about your environment and work, "
    "target='user' for the user's preferences. Actions: add, replace (old_text→content), remove (old_text), read. "
    "Notes are bounded; consolidate when full. They appear in your system prompt from the next session on.",
    obj({"action": {"type": "string", "enum": ["add", "replace", "remove", "read"]},
         "target": {"type": "string", "enum": ["memory", "user"]},
         "content": {"type": "string"}, "old_text": {"type": "string"}}, ["action", "target"]),
    "memory",
)
def memory_tool(ctx: ToolContext, a):
    mem = NotesMemory(ctx.profile)
    action, target = a["action"], a["target"]
    try:
        if action == "add":
            msg = mem.add(target, a.get("content") or "", ctx.session_id)
        elif action == "replace":
            msg = mem.replace(target, a.get("old_text") or "", a.get("content") or "", ctx.session_id)
        elif action == "remove":
            msg = mem.remove(target, a.get("old_text") or "", ctx.session_id)
        elif action == "read":
            entries = mem.entries(target)
            used, cap = mem.usage(target)
            return f"{target} [{used}/{cap}]\n" + ("\n§\n".join(entries) or "(empty)")
        else:
            raise ToolError(f"unknown action {action}")
    except MemoryError_ as exc:
        raise ToolError(str(exc))
    ctx.emit("memory.changed", store=target, action=action)
    return msg


@tool(
    "recall_experience",
    "Search your past task experiences (successes, failures, lessons, procedures) for something relevant to a query.",
    obj({"query": {"type": "string"}, "k": {"type": "integer", "minimum": 1, "maximum": 8}}, ["query"]),
    "memory",
)
def recall_experience(ctx: ToolContext, a):
    store = ExperienceStore(ctx.profile)
    hits = store.search(a["query"], int(a.get("k") or 4), min_coverage=0.15)
    if not hits:
        return "No relevant past experience."
    store.mark_used([e.id for e, _ in hits], ctx.session_id)
    ctx.agent.used_experience_ids.update(e.id for e, _ in hits)
    return "\n\n".join(f"(score {s}) {e.render()}" for e, s in hits)


@tool(
    "skill_view",
    "Read one of your saved skills (procedures you wrote for recurring work). The index is in your system prompt.",
    obj({"name": {"type": "string"}}, ["name"]),
    "memory",
)
def skill_view(ctx: ToolContext, a):
    try:
        return SkillStore(ctx.profile).view(a["name"])
    except KeyError as exc:
        raise ToolError(str(exc))


@tool(
    "skill_save",
    "Save or update a skill: a reusable, step-by-step procedure for a kind of task you expect to repeat.",
    obj({"name": {"type": "string", "description": "kebab-case id"}, "description": {"type": "string"},
         "content": {"type": "string", "description": "Markdown procedure"}}, ["name", "description", "content"]),
    "memory",
)
def skill_save(ctx: ToolContext, a):
    msg = SkillStore(ctx.profile).save(a["name"], a["description"], a["content"], ctx.session_id)
    ctx.emit("memory.changed", store="skill", action="save", name=a["name"])
    return msg
