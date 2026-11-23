"""JSON views of core objects for the web UI.

The core stores transcripts in the model's chat format; the UI wants something closer to what a
person reads: the user's text as typed (`meta.display`, not the experience-augmented prompt), each
assistant step with its tool calls, and each tool call paired with its result so it can be drawn
as one collapsible card. Nothing here mutates state.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ..memory import ExperienceStore, NotesMemory, SkillStore
from ..store import loads

if TYPE_CHECKING:
    from ..profiles import Profile
    from ..store import DB

TOOL_RESULT_CLIP = 8000
PREVIEW_CHARS = 160

# Bus events shown as small muted rows in a session's transcript, with the fields the UI needs.
# (`experience.retrieved` is shown on the user message it augmented, see `display_items`;
# `budget.checkpoint` already appears in the transcript as a [system] note.)
ACTIVITY_FIELDS: dict[str, tuple[str, ...]] = {
    "memory.session_search": ("query", "hits"),
    "context.pruned": ("size",),
    "context.compacted": ("folded", "size"),
    "loop.detected": ("reason",),
    "experience.added": ("outcome", "lessons"),
    "approval.auto": ("category", "grant", "summary"),
}
ACTIVITY_LIMIT = 500
_EXP_BLOCK = re.compile(r"<relevant_past_experience\b[^>]*>(.*?)</relevant_past_experience>", re.DOTALL)
_EXP_TASK = re.compile(r"^\[(?:success|partial|failure)\] Task: (.*)$", re.MULTILINE)


def clip(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + f"\n… [{len(text) - limit} more chars]"


# --------------------------------------------------------------------------- transcripts

def display_items(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn `SessionStore.records()` into UI items.

    Item roles: `user` (kind: message | note | room_turn | agent_message; `recalled` lists the tasks of
    past experiences the run added to that prompt), `assistant` (with `tool_calls`, each carrying its
    `result`/`ok`/`duration` once the tool returned) and `tool` (only for results whose call is not
    part of this batch, e.g. an incremental fetch)."""
    items: list[dict[str, Any]] = []
    calls: dict[str, dict[str, Any]] = {}
    for rec in records:
        msg, meta = rec["message"], rec["meta"] or {}
        role = msg.get("role")
        if role == "system":
            continue
        base = {"id": rec["id"], "created": rec["created"]}
        if role == "user":
            raw = msg.get("content") or ""
            if not isinstance(raw, str):
                raw = str(raw)
            if "display" in meta:
                content, kind = meta["display"] or "", "message"
                if meta.get("room_turn"):
                    kind = "room_turn"
                elif meta.get("from_agent"):
                    kind = "agent_message"
            else:
                content = raw
                kind = "note" if raw.startswith("[system]") or raw.startswith("[Summary of") else "message"
            items.append({**base, "role": "user", "kind": kind, "content": content,
                          "from_agent": meta.get("from_agent"), "turn_role": meta.get("role") if meta.get("room_turn") else None,
                          "recalled": recalled_tasks(raw) if "display" in meta else []})
        elif role == "assistant":
            tcs = []
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                call = {"id": tc.get("id"), "name": fn.get("name") or "?", "args": fn.get("arguments") or "",
                        "result": None, "ok": None, "duration": None}
                if call["id"]:
                    calls[call["id"]] = call
                tcs.append(call)
            items.append({**base, "role": "assistant", "content": msg.get("content") or "",
                          "reasoning": msg.get("reasoning_content") or None, "tool_calls": tcs,
                          "error": bool(meta.get("error")), "cancelled": bool(meta.get("cancelled")),
                          "usage": meta.get("usage")})
        elif role == "tool":
            content = msg.get("content") or ""
            if not isinstance(content, str):
                content = str(content)
            result = {"result": clip(content, TOOL_RESULT_CLIP), "ok": not content.startswith("ERROR"),
                      "duration": meta.get("duration")}
            cid = msg.get("tool_call_id")
            if cid in calls:
                calls[cid].update(result)
            else:
                items.append({**base, "role": "tool", "tool_call_id": cid, "name": meta.get("tool") or "tool", **result})
    return items


def recalled_tasks(prompt: str) -> list[str]:
    """Tasks of the past experiences `Agent._with_experience` appended to a user prompt."""
    prompt = (prompt or "").rstrip()
    if not prompt.endswith("</relevant_past_experience>"):  # the block is always appended last
        return []
    m = _EXP_BLOCK.search(prompt, prompt.rfind("<relevant_past_experience"))
    return [t.strip()[:160] for t in _EXP_TASK.findall(m.group(1))] if m else []


def session_activity(shared: "DB", profile: str, session_id: str, after: int = 0) -> tuple[list[dict[str, Any]], int]:
    """Activity events of one session newer than event id `after`, as `event` items (the client
    merges them into the transcript by `created`), plus the highest event id that existed at query
    time: the client's next cursor, so later fetches only scan new rows of the events table."""
    row = shared.one("SELECT MAX(id) AS m FROM events")
    hi = int((row or {}).get("m") or 0)
    if hi <= after:
        return [], hi
    types = tuple(ACTIVITY_FIELDS)
    rows = shared.query(
        f"SELECT id, ts, type, data FROM events WHERE id>? AND id<=? AND profile=? AND session_id=? "
        f"AND type IN ({','.join('?' * len(types))}) ORDER BY id DESC LIMIT ?",
        (after, hi, profile, session_id, *types, ACTIVITY_LIMIT))
    out = []
    for r in reversed(rows):
        data = loads(r["data"], {}) or {}
        item = {"id": f"e{r['id']}", "role": "event", "type": r["type"], "created": r["ts"]}
        for key in ACTIVITY_FIELDS[r["type"]]:
            val = data.get(key)
            item[key] = clip(val, 400) if isinstance(val, str) else val
        out.append(item)
    return out, hi


def session_todos(session) -> list[dict[str, Any]]:
    """The agent's working plan for a session (`todo` tool), stored in the session's metadata."""
    todos = (session.meta or {}).get("todos") or []
    return [t for t in todos if isinstance(t, dict)]


def tail_records(profile: "Profile", session_id: str, n: int = 60) -> list[dict[str, Any]]:
    """The last `n` records of a session (same shape as `SessionStore.records`)."""
    rows = profile.db.query(
        "SELECT id, role, body, meta, created FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?", (session_id, n))
    return [{"id": r["id"], "role": r["role"], "message": loads(r["body"], {}) or {}, "meta": loads(r["meta"], {}) or {},
             "created": r["created"]} for r in reversed(rows)]


def dangling_tool_calls(records: list[dict[str, Any]]) -> int:
    """Number of tool calls in the last assistant step that never got a result (an interrupted run)."""
    for i in range(len(records) - 1, -1, -1):
        m = records[i]["message"]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            answered = {r["message"].get("tool_call_id") for r in records[i + 1:] if r["message"].get("role") == "tool"}
            return sum(1 for tc in m["tool_calls"] if tc.get("id") not in answered)
        if m.get("role") in {"user", "assistant"}:
            return 0
    return 0


def last_message_preview(profile: "Profile", session_id: str | None) -> dict[str, Any] | None:
    """The most recent user/assistant text of a session, for roster and chat-list previews."""
    if not session_id:
        return None
    rows = profile.db.query(
        "SELECT role, body, meta, created FROM messages WHERE session_id=? AND role IN ('user','assistant') "
        "ORDER BY id DESC LIMIT 8", (session_id,))
    for r in rows:
        body, meta = loads(r["body"], {}) or {}, loads(r["meta"], {}) or {}
        if r["role"] == "user":
            text = meta.get("display") if "display" in meta else body.get("content")
            if not text or (str(text).startswith("[system]") and "display" not in meta):
                continue
        else:
            text = body.get("content")
            if not text:
                calls = body.get("tool_calls") or []
                if calls:
                    text = "⚙ " + ", ".join((c.get("function") or {}).get("name", "?") for c in calls)
        if text:
            text = " ".join(str(text).split())
            return {"role": r["role"], "text": text[:PREVIEW_CHARS], "created": r["created"]}
    return None


# --------------------------------------------------------------------------- memory

def memory_view(profile: "Profile", *, experiences: int = 100, events: int = 60) -> dict[str, Any]:
    notes = NotesMemory(profile)
    out_notes = {}
    for target in ("memory", "user"):
        used, cap = notes.usage(target)
        out_notes[target] = {"entries": notes.entries(target), "used": used, "limit": cap}
    skills = []
    store = SkillStore(profile)
    for s in store.list():
        try:
            content = (profile.skills_dir / f"{s['name']}.md").read_text(encoding="utf-8")
        except OSError:
            content = ""
        skills.append({**s, "content": clip(content, 6000)})
    exps = [e.to_dict() for e in ExperienceStore(profile).all()]
    exps.sort(key=lambda e: e["created"], reverse=True)
    rows = profile.db.query("SELECT * FROM memory_events ORDER BY id DESC LIMIT ?", (events,))
    for r in rows:
        r["detail"] = loads(r["detail"], {})
    return {
        "profile": profile.name,
        "notes": out_notes,
        "skills": skills,
        "experiences": exps[:experiences],
        "experience_count": len(exps),
        "events": rows,
    }
