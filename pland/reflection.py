"""Post-task reflection: turn a finished run into a reusable experience record.

Runs on the same (DeepSeek/HKGAI) model as the agent. The outcome here is the agent's own
assessment; the evaluation harness later overwrites it with the *verified* outcome
(`ExperienceStore.set_outcome`), so the experience base learns from ground truth when available.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from .memory import ExperienceStore, MemoryError_, NotesMemory

if TYPE_CHECKING:
    from .agent import Agent, RunResult

PROMPT = """You review an AI agent's finished task to extract reusable experience for its future tasks.
Judge the outcome from the evidence in the transcript (tool errors, failing tests, missing files), not from the
agent's claims. Keep a durable decision only when the transcript includes the deciding source or a check
that distinguishes it from the alternative. Leave tentative interpretations out of lessons and procedures.
Return ONLY a JSON object:
{
  "outcome": "success" | "partial" | "failure",
  "summary": "<=2 sentences: what was asked and what actually happened",
  "lessons": ["<=4 short, specific, reusable lessons (what worked, what to avoid, root cause of failures)"],
  "procedure": "short numbered procedure that would solve this kind of task next time, or empty string",
  "tags": ["3-6 lowercase keywords for retrieval"],
  "memory_notes": ["0-2 durable facts worth keeping in long-term notes (environment, user preferences); usually empty"],
  "memory_correction": null or {"old_text": "<distinctive substring of ONE existing note that this run's evidence
                       shows is wrong or obsolete>", "action": "remove" | "replace", "content": "<corrected note if replace>"}
}
Only propose a memory_correction when the transcript gives clear evidence against an existing note; otherwise null."""


def _digest(agent: "Agent", limit: int = 24000) -> str:
    lines = []
    for r in agent.sessions.records(agent.session_id):
        m = r["message"]
        role = m.get("role")
        if role == "system":
            continue
        if role == "user":
            lines.append(f"USER: {(r['meta'].get('display') or m.get('content', ''))[:1500]}")
        elif role == "assistant":
            if m.get("content"):
                lines.append(f"AGENT: {m['content'][:1200]}")
            for tc in m.get("tool_calls") or []:
                lines.append(f"CALL {tc['function']['name']}: {tc['function'].get('arguments', '')[:300]}")
        elif role == "tool":
            lines.append(f"RESULT: {str(m.get('content', ''))[:500]}")
    text = "\n".join(lines)
    return text if len(text) <= limit else text[: limit // 3] + "\n...\n" + text[-2 * limit // 3 :]


def _parse(text: str) -> dict:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("no JSON object in reflection output")
    return json.loads(m.group(0))


def _reflect_in_context(agent: "Agent", task_text: str, status_note: str, messages: list | None = None):
    """In-context review: replay the session as-is (same system prompt, tools and history, so the
    provider's prompt cache is reused) and append one reflection request. Returns None if the model
    does not answer with usable JSON, in which case the caller falls back to a separate digest prompt."""
    if agent.role == "subagent":
        return None
    msgs = list(messages) if messages is not None else agent._llm_messages()
    msgs.append({"role": "user", "content": "[reflection request — do not call tools; reply with JSON only]\n"
                 + PROMPT + f"\n\nReflect on the most recent task in this conversation: {task_text[:600]!r}\n{status_note}"})
    schemas = [t.schema() for t in agent.tools.values()] or None
    # same thinking setting as the session so the cached prefix (which includes reasoning) still matches;
    # reasoning shares the output budget, hence the larger cap when thinking is on
    budget = 4000 if agent.settings.model.thinking else 1200
    resp = agent.chat(msgs, schemas, purpose="reflection", max_tokens=budget)
    if resp.tool_calls:
        return None
    try:
        return resp, _parse(resp.content)
    except (ValueError, json.JSONDecodeError):
        return None


def reflect(agent: "Agent", task_text: str, result: "RunResult", messages: list | None = None) -> list[str]:
    store = ExperienceStore(agent.profile)
    status_note = f"Run status: {result.status}" + (f" ({result.error.splitlines()[0]})" if result.error else "")
    got = _reflect_in_context(agent, task_text, status_note, messages)
    if got is None:
        messages = [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": f"TASK:\n{task_text[:3000]}\n\n{status_note}\n\nTRANSCRIPT:\n{_digest(agent)}\n\nFINAL ANSWER:\n{result.text[:3000]}"},
        ]
        resp = agent.chat(messages, None, purpose="reflection", json_mode=True, max_tokens=1200, thinking=False)
        data = _parse(resp.content)
    else:
        resp, data = got
    result.usage.add(resp.usage)
    outcome = str(data.get("outcome", "partial")).lower()
    if result.status != "completed" and outcome == "success":
        outcome = "partial"
    exp = store.add(
        task=task_text, outcome=outcome, summary=str(data.get("summary", ""))[:2000],
        lessons=[str(x) for x in (data.get("lessons") or [])][:4], procedure=str(data.get("procedure") or "") or None,
        tags=[str(x).lower() for x in (data.get("tags") or [])][:6], session_id=agent.session_id,
    )
    # Feedback loop: experiences that were retrieved for this task get credit (or blame).
    used = sorted(agent.used_experience_ids)
    if used:
        store.feedback(used, success=(outcome == "success"), session_id=agent.session_id)
    agent.sessions.patch_meta(agent.session_id, fn=lambda m: m.setdefault("feedback", []).append(
        {"used": used, "self_outcome": outcome, "experience": exp.id}))
    notes = NotesMemory(agent.profile)
    corr = data.get("memory_correction")
    if isinstance(corr, dict) and corr.get("old_text"):
        # Self-correction of beliefs: at most one per task, logged like any memory write.
        try:
            if corr.get("action") == "replace" and corr.get("content"):
                notes.replace("memory", str(corr["old_text"]), str(corr["content"]), agent.session_id)
            elif corr.get("action") == "remove":
                notes.remove("memory", str(corr["old_text"]), agent.session_id)
            agent.emit("memory.corrected", action=corr.get("action"), old_text=str(corr["old_text"])[:200])
        except MemoryError_:
            pass  # the substring did not identify exactly one note: leave memory untouched
    for note in (data.get("memory_notes") or [])[:2]:
        try:
            notes.add("memory", str(note), agent.session_id)
        except MemoryError_:
            break
    agent.emit("experience.added", id=exp.id, outcome=outcome, lessons=exp.lessons)
    return [exp.id]
