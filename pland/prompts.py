"""System-prompt assembly. The system prompt is built once per session and stored as the first
message, so it stays byte-stable across turns (prefix caching) — memory edits made during a session
show up from the next session on, as in Hermes."""

from __future__ import annotations

import platform
import time
from typing import TYPE_CHECKING

from .memory import NotesMemory, SkillStore

if TYPE_CHECKING:
    from .profiles import Profile

WORK_RULES = """\
# How you work
- Use available tools to do the task. Verify your work before claiming success.
- Relative file paths resolve inside your private workspace.
- Use todo to plan tasks with three or more steps.
- If an essential detail is missing, explain what you need from the user.
- In your final answer, summarize your result, give evidence, and state what remains open.
"""


MEMORY_RULES = """\
# Memory
You keep bounded personal notes (shown below as a snapshot taken at session start). Use the `memory` tool to save
durable facts: user preferences, environment details, conventions, and lessons that will matter in future tasks.
Do not save one-off task details or paths inside your workspace. Relevant past experiences may be attached to a
task; apply their lessons.
Save a skill (skill_save) when you work out a reusable multi-step procedure.
"""


def build_system_prompt(profile: "Profile", *,
                        backend_name: str = "local", extra: str | None = None, tool_names: set[str] | None = None) -> str:
    parts = []
    ident = f"You are {profile.title} (@{profile.name})."
    if profile.description:
        ident += f" Role: {profile.description}"
    parts.append(ident)
    parts.append(profile.soul)
    ws = profile.workspace
    env = [
        "# Environment",
        f"- Date: {time.strftime('%Y-%m-%d %H:%M %Z')}",
        f"- Host OS: {platform.system()} {platform.release()} | execution backend: {backend_name}"
        + (" (commands run inside an isolated container; /workspace is your workspace)" if backend_name == "docker" else ""),
        f"- Your private workspace: {ws}",
    ]
    if platform.system() == "Darwin" and backend_name != "docker":
        env.append("- Shell is macOS (BSD userland): `sed -i ''`, no GNU `timeout`/`cat -A`; use `python3` for portable "
                   "scripting. Python 3 with pytest is on PATH.")
    parts.append("\n".join(env))
    parts.append(WORK_RULES)
    tool_names = tool_names or set()
    if "memory" in tool_names:
        notes = NotesMemory(profile)
        parts.append(MEMORY_RULES + "\n" + notes.render())
        skills = SkillStore(profile).list()
        if skills:
            parts.append("# Your skills (read the relevant one with skill_view before starting a matching task)\n"
                         + "\n".join(f"- {s['name']}: {s['description']}" for s in skills))
    if extra:
        parts.append(extra)
    return "\n\n".join(p for p in parts if p)
