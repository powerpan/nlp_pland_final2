"""Clarification tool: pause and ask the human, then continue the same run with the answer."""

from __future__ import annotations

from ..hitl import HITLRequest
from .registry import ToolContext, obj, tool


@tool(
    "ask_user",
    "Ask the human a question and wait for the answer. Use it when the instruction is ambiguous, key information "
    "is missing, or a decision belongs to the user. Offer options when there are clear alternatives. "
    "Do not use it for permission to run commands — risky operations prompt for approval automatically.",
    obj({"question": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}},
         "context": {"type": "string", "description": "why you are asking / what you will do with the answer"}}, ["question"]),
    "hitl",
)
def ask_user(ctx: ToolContext, a):
    req = HITLRequest(kind="clarify", profile=ctx.profile.name, session_id=ctx.session_id, question=a["question"],
                      options=list(a.get("options") or []), detail=a.get("context") or "", room_id=ctx.room_id,
                      run_id=ctx.run_id)
    ctx.emit("hitl.waiting", kind="clarify", question=a["question"])
    ans = ctx.hitl.request(req, timeout=ctx.settings.approvals.timeout)
    if ans.status == "answered" and ans.text.strip():
        return f"The user answered: {ans.text.strip()}"
    return f"[{ans.status}] {ans.text or 'No answer.'}"
