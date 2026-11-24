"""System-prompt assembly. The system prompt is built once per session and stored as the first
message, so it stays byte-stable across turns (prefix caching) — memory edits made during a session
show up from the next session on."""

from __future__ import annotations

import platform
import time
from typing import TYPE_CHECKING

from .memory import NotesMemory, SkillStore

if TYPE_CHECKING:
    from pathlib import Path

    from .profiles import Profile
    from .runtime import Runtime

WORK_RULES = """\
# How you work
- Accomplish tasks by acting: use your tools to create/edit files, run code and tests, search and read the web,
  and commit/push with git. Never just describe steps you could perform yourself.
- Verify before you claim success (run the code, run tests, re-read the file, check command output). If something
  failed, say so plainly; do not invent results.
- Relative paths resolve inside your workspace (the folder this conversation works in). You cannot access other
  agents' workspaces or memory.
- Deliverable files (reports, documents, code): create them early — an outline or first results within a few steps —
  and extend them as you go, so a step or output limit never leaves you with nothing written. Write large files in
  parts (each write_file call well under 20,000 characters, the rest with append=true).
- Documents you produce must be Markdown (.md) or plain text (.txt). Source code files are fine in any language.
- Human-in-the-loop: if the request is ambiguous or leaves out a fact that changes the result (a unit, format,
  target, version, scope, ...), ask with ask_user instead of guessing — even for small tasks. Do not infer such
  unstated parameters from the data's appearance. When you could not ask (no answer), state the assumption you made.
  Operations that need permission (deleting files, risky shell commands, git push, ...) automatically ask the
  human — never try to work around a denial or a refusal (e.g. pushing with a script instead of git_push).
- Keep your final answer concise: what you did, the result (with evidence such as file paths, test output, URLs),
  and anything left open.
"""

MEMORY_RULES = """\
# Memory
You keep bounded personal notes (shown below as a snapshot taken at session start). Use the `memory` tool to save
durable facts: user preferences, environment details, conventions, and lessons that will matter in future tasks.
Do not save one-off task details or paths inside your workspace. Relevant past experiences may be attached to a
task; apply their lessons. `session_search` finds specifics from your past conversations that are not in your notes.
Save a skill (skill_save) when you work out a reusable multi-step procedure.
"""


def team_section(runtime: "Runtime", profile: "Profile", room: dict | None = None) -> str:
    mates = [p for p in runtime.profiles.list(bots_only=True) if p.name != profile.name and not p.meta.get("hidden")]
    if not mates:
        return ""

    def row(p) -> str:
        # what the teammate cannot do, so a lead never assigns work its tools do not allow
        toolsets = set(p.settings().toolsets)
        limits = [text for ts, text in (("code", "cannot run code"), ("web", "no web access"), ("git", "no git"))
                  if ts not in toolsets]
        return (f"- @{p.name}: {p.title}" + (f" — {p.description}" if p.description else "")
                + (f" [{'; '.join(limits)}]" if limits else ""))

    if room:
        members = set(room.get("members") or [])
        inside = [p for p in mates if p.name in members]
        outside = [p for p in mates if p.name not in members]
        lines = ["# Teammates", "Members of this room (prefer them for the room's work):"] + [row(p) for p in inside]
        if outside:
            lines += ["Other bots outside this room (only if no member fits):"] + [row(p) for p in outside]
    else:
        lines = ["# Teammates (other agents you can collaborate with)"] + [row(p) for p in mates]
    lines.append(
        "Use delegate_task(to=\"<name>\") to hand a self-contained subtask to the best-suited teammate; it executes "
        "in its own workspace with its own tools and memory and returns a report. Independent subtasks passed together "
        "in one delegate_task call run in parallel. Give each delegate full context — they cannot see your conversation. "
        "Use message_agent for a quick question. Files a teammate writes for a delegated task are copied back into "
        "your folder under inbox/from-<name>/ when it finishes (the result lists them), so you need not ask for them; use "
        "share_file for other hand-overs. Every delegation result shows how much of the run budget is used: when little "
        "is left, finish yourself instead of starting another round. Do the work yourself when no teammate "
        "is a better fit. Size each delegated task so one teammate can finish it within its step budget (about 80 tool "
        "steps): split a broad review or audit by area or by file set, name the output file, and ask only for what the "
        "teammate's tools allow (see the limits in brackets)."
    )
    return "\n".join(lines)


def _limits(tool_names: set[str]) -> str:
    """Say what a restricted profile cannot do. Without this, a bot with no code tools kept writing
    verification scripts it had no way to run (acceptance run of the requirements-team template)."""
    if not tool_names:
        return ""
    helper = "ask a teammate who can (message_agent)" if "message_agent" in tool_names else "say so in your answer"
    lines = []
    if not tool_names & {"run_shell", "run_python"}:
        lines.append("You cannot run code or shell commands. Do not write scripts in order to run them: check behaviour "
                     f"by reading the code and its tests, and if something really needs executing, {helper}.")
    if not tool_names & {"web_search", "web_fetch"}:
        lines.append(f"You cannot search or browse the web; work from the files you have, or {helper}.")
    return "# Limits of this profile\n" + "\n".join(f"- {line}" for line in lines) if lines else ""


def build_system_prompt(runtime: "Runtime", profile: "Profile", *, role: str = "main", room: dict | None = None,
                        backend_name: str = "local", extra: str | None = None, tool_names: set[str] | None = None,
                        workspace: "Path | None" = None) -> str:
    """`workspace`: a folder the user chose for this conversation (None: the bot's private workspace)."""
    parts = []
    ident = f"You are {profile.title} (@{profile.name})."
    if profile.description:
        ident += f" Role: {profile.description}"
    parts.append(ident)
    parts.append(profile.soul)
    ws = workspace or profile.workspace
    env = [
        "# Environment",
        f"- Date: {time.strftime('%Y-%m-%d %H:%M %Z')}",
        f"- Host OS: {platform.system()} {platform.release()} | execution backend: {backend_name}"
        + (" (commands run inside an isolated container where /workspace is your workspace; the host sees a different "
           "absolute path, so use relative paths in config files such as git remotes)" if backend_name == "docker" else ""),
        f"- Your private workspace: {ws}" if workspace is None else
        f"- Working folder of this conversation: {ws}. The user chose this folder for this conversation; its files are "
        "the user's. Read before you change things, keep changes to what the task needs, and ask before deleting or "
        "overwriting files you did not create. Relative paths in file tools and commands start here.",
    ]
    if platform.system() == "Darwin" and backend_name != "docker":
        env.append("- Shell is macOS (BSD userland): `sed -i ''`, no GNU `timeout`/`cat -A`; use `python3` for portable "
                   "scripting. Python 3 with pytest is on PATH.")
    if backend_name != "local":
        env.append("- Shell commands run sandboxed with a private HOME and no access to the user's credentials or files "
                   "outside your workspace. To push to a remote (e.g. GitHub) use the git_push tool, which runs on the "
                   "host with the user's git credentials after approval.")
    if role == "main" and not room:
        env.append("- The user can give this conversation its own folder (the folder button in the web UI's header, "
                   "`/workspace <folder>` or `pland -w <folder>` in the CLI); you cannot change it yourself.")
    if room:
        env.append(f"- Shared folder of group room '{room['name']}': `shared/` (relative to your workspace) in file tools "
                   "and shell commands alike. Teammates see it; your other files stay private.")
    parts.append("\n".join(env))
    parts.append(WORK_RULES)
    tool_names = tool_names or set()
    limits = _limits(tool_names)
    if limits:
        parts.append(limits)
    if "memory" in tool_names and role != "subagent":
        notes = NotesMemory(profile)
        parts.append(MEMORY_RULES + "\n" + notes.render())
        skills = SkillStore(profile).list()
        if skills:
            parts.append("# Your skills (read the relevant one with skill_view before starting a matching task)\n"
                         + "\n".join(f"- {s['name']}: {s['description']}" for s in skills))
    if "delegate_task" in tool_names and role != "subagent":
        team = team_section(runtime, profile, room)
        if team:
            parts.append(team)
    if role == "subagent":
        parts.append("# Subagent\nYou are a temporary subagent working on one delegated subtask with a fresh context. "
                     "You cannot ask the user questions. Finish with a structured report: what you did, results, files changed, issues.")
    elif role == "delegate":
        parts.append("# Delegated work\nIn this session you execute tasks delegated to you by teammates. Work autonomously, "
                     "then finish with a concise report the delegator can act on: what you did, results with evidence, "
                     "files produced (paths), open issues. If the task names an output file, write it early and keep it "
                     "up to date; a delegation that ends without its file is reported as failed.")
    if extra:
        parts.append(extra)
    return "\n\n".join(p for p in parts if p)
