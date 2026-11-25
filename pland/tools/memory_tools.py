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
         "verified_task_id": {"type": "string", "description": "Store the exact signed resolution or observed evidence from a passing board card."},
         "user_quote": {"type": "string", "description": "For a preference explicitly stated by the current human, quote their exact words. Saves those words immediately to target=user."},
         "content": {"type": "string"}, "old_text": {"type": "string"}}, ["action", "target"]),
    "memory",
)
def memory_tool(ctx: ToolContext, a):
    mem = NotesMemory(ctx.profile)
    action, target = a["action"], a["target"]
    verified = a.get("verified_task_id")
    turn = ctx.agent.budget.team_turn
    quote = (a.get("user_quote") or "").strip()
    content = (a.get("content") or "").strip()
    if quote and (target != "user" or action not in {"add", "replace"} or (turn and quote not in turn.user_text)):
        raise ToolError("For user_quote, copy an exact preference from the current human's message and use target=user.")
    if target == "user" and verified:
        raise ToolError("A card verifies team work. For the human's preference use user_quote with the human's exact words.")
    if turn and target == "user" and content and content in turn.user_text and action in {"add", "replace"}:
        quote = quote or content

    def write(*, validate_only=False):
        content = quote or a.get("content") or ""
        if verified:
            card = ctx.runtime.board.get(verified)
            review = card.get("review") or {}
            if (not ctx.room_id or card["room_id"] != ctx.room_id or action != "add" or target != "memory"
                    or card["status"] != "done" or review.get("verdict") != "pass"
                    or not (review.get("resolution") or review.get("evidence", {}).get("basis") == "observed")):
                raise ToolError("Only a current signed resolution on this group's card can be remembered this way.")
            content = review.get("resolution") or review["evidence"]["detail"]
        if action == "add":
            msg = mem.add(target, content, ctx.session_id, validate_only=validate_only)
        elif action == "replace":
            msg = mem.replace(target, a.get("old_text") or "", content, ctx.session_id, validate_only=validate_only)
        elif action == "remove":
            msg = mem.remove(target, a.get("old_text") or "", ctx.session_id)
        elif action == "read":
            entries = mem.entries(target)
            used, cap = mem.usage(target)
            return f"{target} [{used}/{cap}]\n" + ("\n§\n".join(entries) or "(empty)")
        else:
            raise ToolError(f"unknown action {action}")
        if not validate_only:
            ctx.emit("memory.changed", store=target, action=action)
        return msg

    try:
        if quote:
            return write()  # The human is the source; later findings cannot invalidate this preference.
        if action in {"add", "replace"} and turn:
            if feedback := write(validate_only=True):
                return feedback
            if target == "user" and turn.conflicts:
                raise ToolError("For the user's own preference, use user_quote with their exact words. Work conclusions belong on the board.")
            turn.defer_learning(ctx.agent, write, independently_sourced=bool(verified))
            return ("Queued until group verification settles. To remember an explicit user preference immediately, "
                    "use target=user with user_quote copied from the latest human message.")
        return write()
    except MemoryError_ as exc:
        raise ToolError(str(exc))


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
    "Save or update a skill: a reusable procedure for a kind of task you expect to repeat. Write the content with "
    "these sections: '## When to Use', '## Procedure' (numbered steps), '## Pitfalls', '## Verification'. "
    "Update an existing skill (same name) instead of creating near-duplicates.",
    obj({"name": {"type": "string", "description": "kebab-case id"}, "description": {"type": "string",
         "description": "one line: what it does and when it applies"},
         "content": {"type": "string", "description": "Markdown body with the four sections"}}, ["name", "description", "content"]),
    "memory",
)
def skill_save(ctx: ToolContext, a):
    SkillStore.validate_name(a["name"])
    def save():
        msg = SkillStore(ctx.profile).save(a["name"], a["description"], a["content"], ctx.session_id)
        ctx.emit("memory.changed", store="skill", action="save", name=a["name"])
        return msg
    if ctx.agent.budget.team_turn:
        ctx.agent.budget.team_turn.defer_learning(ctx.agent, save)
        return "Queued until group verification settles. Unverified procedures from a disputed task are withheld."
    return save()


@tool(
    "session_search",
    "Search your own past conversations (all your sessions, full text, no summarization). Pass `query` to find "
    "sessions where something was discussed; pass `session_id` + `around_message_id` to read more around a hit. "
    "Use it for 'did we do X before / what did the user say about Y' questions; memory notes hold only key facts.",
    obj({"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10},
         "session_id": {"type": "string"}, "around_message_id": {"type": "integer"},
         "window": {"type": "integer", "minimum": 1, "maximum": 20}}),
    "memory",
)
def session_search(ctx: ToolContext, a):
    from ..sessions import SessionStore
    import time as _time

    store = SessionStore(ctx.profile)
    if a.get("session_id") and a.get("around_message_id"):
        msgs = store.window(a["session_id"], int(a["around_message_id"]), int(a.get("window") or 4))
        if not msgs:
            raise ToolError("no messages there")
        return "\n".join(f"#{m['id']} [{m['role']}] {m['text']}" for m in msgs)
    if not a.get("query"):
        raise ToolError("pass a query, or session_id + around_message_id")
    hits = store.search(a["query"], limit=int(a.get("limit") or 4), exclude=ctx.session_id)
    ctx.emit("memory.session_search", query=a["query"][:200], hits=len(hits))
    if not hits:
        return "No past conversation matched."
    blocks = []
    for i, h in enumerate(hits):
        when = _time.strftime("%Y-%m-%d %H:%M", _time.localtime(h["when"]))
        lines = [f"session {h['session_id']} · {h['kind']} · {when} · {h['title'][:80]!r}", f"  match #{h['match_message_id']}: {h['snippet']}"]
        if i == 0:  # the best hit gets its surrounding context, the rest stay compact
            for m in store.window(h["session_id"], h["match_message_id"], 2):
                lines.append(f"    #{m['id']} [{m['role']}] {m['text'][:500]}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n\n(use session_id + around_message_id to read more)"
