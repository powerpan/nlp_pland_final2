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
agent's claims. Return ONLY a JSON object:
{
  "outcome": "success" | "partial" | "failure",
  "summary": "<=2 sentences: what was asked and what actually happened",
  "lessons": ["<=4 short, specific, reusable lessons (what worked, what to avoid, root cause of failures)"],
  "procedure": "short numbered procedure that would solve this kind of task next time, or empty string",
  "tags": ["3-6 lowercase keywords for retrieval"],
  "memory_notes": ["0-2 durable facts worth keeping in long-term notes (environment, user preferences); usually empty"]
}"""


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


def reflect(agent: "Agent", task_text: str, result: "RunResult") -> list[str]:
    store = ExperienceStore(agent.profile)
    status_note = f"Run status: {result.status}" + (f" ({result.error.splitlines()[0]})" if result.error else "")
    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": f"TASK:\n{task_text[:3000]}\n\n{status_note}\n\nTRANSCRIPT:\n{_digest(agent)}\n\nFINAL ANSWER:\n{result.text[:3000]}"},
    ]
    resp = agent.chat(messages, None, purpose="reflection", json_mode=True, max_tokens=1200)
    result.usage.add(resp.usage)
    data = _parse(resp.content)
    outcome = str(data.get("outcome", "partial")).lower()
    if result.status != "completed" and outcome == "success":
        outcome = "partial"
    exp = store.add(
        task=task_text, outcome=outcome, summary=str(data.get("summary", ""))[:2000],
        lessons=[str(x) for x in (data.get("lessons") or [])][:4], procedure=str(data.get("procedure") or "") or None,
        tags=[str(x).lower() for x in (data.get("tags") or [])][:6], session_id=agent.session_id,
    )
    # Feedback loop: experiences that were retrieved for this task get credit (or blame).
    if agent.used_experience_ids:
        store.feedback(sorted(agent.used_experience_ids), success=(outcome == "success"), session_id=agent.session_id)
    notes = NotesMemory(agent.profile)
    for note in (data.get("memory_notes") or [])[:2]:
        try:
            notes.add("memory", str(note), agent.session_id)
        except MemoryError_:
            break
    agent.emit("experience.added", id=exp.id, outcome=outcome, lessons=exp.lessons)
    return [exp.id]
