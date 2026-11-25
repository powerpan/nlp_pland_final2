"""`platform_info`: what the agent knows about the platform it runs on (see pland/handbook)."""

from __future__ import annotations

from .. import handbook
from .registry import ToolContext, ToolError, obj, tool


@tool(
    "platform_info",
    "Authoritative facts about PlanD, the multi-agent platform (harness) you are running on, and about your own "
    "current setup. Call it BEFORE answering any question about yourself or the platform — what this system is, "
    "what can be configured and where, which model/thinking/sandbox/approval settings you have, how you collaborate "
    "with teammates (delegation, groups, task board), how your memory works, what your limits and tools are, how the "
    "terminal and web interfaces work — and answer from what it returns instead of guessing or reading source code. "
    "Read-only; no model call. Topics: " + "; ".join(f"{k} = {v}" for k, v in handbook.TOPICS.items()) + ". "
    "Ask for several topics in parallel calls when a question spans them. Answer in the user's own language and script "
    "(Traditional Chinese if they wrote Traditional Chinese), in your own words — do not paste the topic.",
    obj({"topic": {"type": "string", "enum": handbook.topic_names(),
                   "description": "Which part to read. Start with `overview` if unsure; `status` is your live setup."}},
        ["topic"]),
    "platform",
)
def platform_info(ctx: ToolContext, a):
    topic = str(a.get("topic") or "overview").strip().lower()
    try:
        return handbook.render(topic, ctx)
    except KeyError:
        raise ToolError(f"unknown topic {topic!r}; topics:\n{handbook.index()}")
