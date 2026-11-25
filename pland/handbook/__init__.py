"""What an agent knows about the platform it runs on.

Agents are asked "what can be configured?", "how do you work with your team?", "what is this platform?". Their
answers come from here, through the read-only `platform_info` tool (pland/tools/about.py):

- **Handbook topics** — the Markdown files next to this module, written for the agent as reader. They describe
  behaviour at the level a user asks about, which the source code does not (and the code is 12k lines an agent
  would have to read through a sandbox that deliberately cannot see the installation).
- **Generated sections** — the settings table and the tool list are built from the running code (the settings
  catalogue behind the Settings page, the tool registry), so they cannot drift from it.
- **`status`** — the live setup of the agent that asks: model, thinking, approvals, sandbox, folder, tools,
  budget, memory, teammates and rooms.

tests/test_platform_info.py checks the prose against the code (every setting, tool, CLI command and slash command
named here exists, and the other way round).
"""

from __future__ import annotations

import re
from dataclasses import fields
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import AgentSettings

if TYPE_CHECKING:
    from ..tools.registry import ToolContext

HERE = Path(__file__).resolve().parent
# topic -> one line for the index (the order is the order shown to the agent)
TOPICS: dict[str, str] = {
    "overview": "what PlanD is, single agent vs Bot Mode, what an agent is here, which models are allowed",
    "status": "your own current setup, live: model, thinking, approvals, sandbox, folder, tools, budget, memory, team",
    "configuration": "everything that can be configured, where each switch is, and the values in effect for you",
    "collaboration": "delegation, messages, groups and turn-taking, the task board, file hand-over",
    "memory": "notes, experiences and how they evolve, skills, conversation search, what stays private",
    "safety": "asking the human, approvals, hard blocks, sandbox backends, isolation and its real boundaries",
    "limits": "step and budget caps, loop guards, output and context limits, retries, thinking intensity",
    "tools": "every tool by toolset, and which ones you have",
    "interfaces": "terminal commands, the web UI, the evaluation harness, where data is stored",
}
GENERATED = {"status", "tools"}  # topics with no Markdown file of their own

# What each setting does (the Settings page shows the same fields; names are the ones in pland/server/settings.py).
SETTING_NOTES: dict[str, str] = {
    "model": "model id for this provider (`deepseek-flash` is fast and cheap, `deepseek-v4-pro` is stronger)",
    "reasoning": "thinking intensity: off, default (thinking on, provider decides the depth) or a level",
    "max_tokens": "output cap per reply, thinking included",
    "stream": "stream replies so the interface shows text as it is written",
    "approvals": "who decides on operations that need permission: manual (the human), smart (guard model first), off",
    "approval_timeout": "seconds to wait for the human before a request counts as unanswered",
    "unattended": "what happens to an approval request when no human channel is attached",
    "reflection": "learn from each finished task (writes an experience record)",
    "background_reflection": "return the answer first and reflect afterwards",
    "experience_top_k": "how many past experiences are attached to a new task (0 switches retrieval off)",
    "backend": "where commands run: local (Seatbelt on macOS) or docker (a container per bot and folder)",
    "os_sandbox": "auto = wrap local commands in macOS Seatbelt when available; off = the user's full rights",
    "command_timeout": "seconds one shell or Python command may run",
    "docker_network": "container network: bridge, or none for no network at all",
    "docker_memory": "container memory limit, e.g. 1g",
    "docker_cpus": "container CPU limit",
    "max_iterations": "steps (model calls) one run may take",
    "max_run_calls": "model calls a top-level run and everything it delegates may use (a group drive gets double)",
    "max_run_tokens": "weighted tokens for the same (a cached input token counts 0.1)",
    "max_parallel_delegations": "delegated tasks of one call that run at the same time",
    "max_delegation_depth": "how deep delegation may nest (lead → teammate → its subagent is 2)",
    "fast_review_steps": "step ceiling for a Fast Mode review",
    "fast_review_seconds": "time ceiling in seconds for the initial Fast Mode review",
    "fast_followup_seconds": "time ceiling in seconds for a Fast Mode revision review",
    "review_max_steps": "platform ceiling for model calls in one independent file review",
    "review_timeout_seconds": "platform ceiling in seconds for one independent file review",
    "context_char_budget": "size of the conversation the model sees before it is compacted",
}
# Settings with no row on the Settings page: profile.yaml (or built-in) only.
FILE_ONLY_NOTES: dict[str, str] = {
    "toolsets": "which groups of tools the agent has (files, code, web, git, memory, plan, hitl, delegation, team); "
                "removing one takes those tools away, e.g. a writer without `web` and `code`",
    "model.provider": "deepseek or hkgai; normally set for the whole installation with PLAND_PROVIDER",
    "model.base_url": "endpoint override (normally from the provider's environment variable)",
    "model.thinking": "the on/off half of thinking intensity (written together with model.reasoning_effort)",
    "model.temperature": "sampling temperature, used only when thinking is off",
    "model.timeout": "seconds to wait for one model call",
    "model.max_retries": "retries of a model call after a temporary error",
    "sandbox.max_output_chars": "how much output of one command is kept",
    "sandbox.docker_image": "image the docker backend runs (built on first use)",
}


def topic_names() -> list[str]:
    return list(TOPICS)


def index() -> str:
    return "\n".join(f"- `{name}` — {line}" for name, line in TOPICS.items())


def read_topic(name: str) -> str:
    return (HERE / f"{name}.md").read_text(encoding="utf-8").strip()


def render(name: str, ctx: "ToolContext | None" = None) -> str:
    """The text of one topic. `ctx` adds the asking agent's live values where a topic has them."""
    if name not in TOPICS:
        raise KeyError(name)
    if name == "status":
        return status(ctx)
    if name == "tools":
        return tools_reference(ctx)
    text = read_topic(name)
    if name == "configuration":
        text += "\n\n" + settings_reference(ctx.settings if ctx else None)
    return text


# --------------------------------------------------------------------------- generated: settings

def _allowed(field: Any) -> str:
    from ..llm import reasoning

    if field.kind == "choice":
        return " / ".join(field.choices)
    if field.kind == "bool":
        return "on / off"
    if field.kind == "reasoning":
        return " / ".join(reasoning.choices("deepseek")) + " (HKGAI: " + " / ".join(reasoning.choices("hkgai")) + ")"
    if field.kind == "model":
        return "a model id of the provider"
    if field.kind == "memory":
        return "a size such as 512m or 2g"
    if field.kind in {"int", "cpus", "float"}:
        lo, hi = (int(v) if float(v).is_integer() else v for v in (field.lo, field.hi))
        return f"{lo:,} – {hi:,}" if isinstance(lo, int) and isinstance(hi, int) else f"{lo} – {hi}"
    return ""


def _show(value: Any) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int):
        return f"{value:,}"
    return "—" if value is None else str(value)


def settings_reference(settings: AgentSettings | None = None) -> str:
    """Every field of the Settings page with its allowed values, built-in default and the asking agent's value."""
    from ..server.settings import FIELDS, flat_values

    defaults = flat_values(AgentSettings.from_dict(None))
    mine = flat_values(settings) if settings else {}
    head = "| Setting (`profile.yaml` path) | What it does | Allowed | Built-in default |" + (" Yours now |" if mine else "")
    lines = [head, "|---|---|---|---|" + ("---|" if mine else "")]
    for name, field in FIELDS.items():
        row = f"| `{'.'.join(field.path)}` | {SETTING_NOTES[name]} | {_allowed(field)} | {_show(defaults[name])} |"
        lines.append(row + (f" {_show(mine[name])} |" if mine else ""))
    extra = ["", "Set only in `profile.yaml` (no row on the Settings page):"]
    extra += [f"- `{path}` — {note}" for path, note in FILE_ONLY_NOTES.items()]
    return "\n".join(lines + extra)


def documented_setting_paths() -> set[str]:
    """Dotted paths the configuration topic covers (for the drift test)."""
    from ..server.settings import FIELDS

    return {".".join(f.path) for f in FIELDS.values()} | set(FILE_ONLY_NOTES)


def all_setting_paths() -> set[str]:
    """Every settable field of AgentSettings as a dotted path (secrets excluded: keys are environment-only)."""
    out: set[str] = set()
    base = AgentSettings()
    for f in fields(AgentSettings):
        value = getattr(base, f.name)
        if hasattr(value, "__dataclass_fields__"):
            out |= {f"{f.name}.{g.name}" for g in fields(value) if g.name != "api_key"}
        else:
            out.add(f.name)
    return out


# --------------------------------------------------------------------------- generated: tools

TOOLSET_NOTES = {
    "files": "read and change files in the conversation's folder",
    "code": "run commands and Python in the sandbox",
    "web": "search and read the web",
    "git": "version control on the host, with the user's credentials for push",
    "memory": "your own notes, experiences, skills and past conversations",
    "plan": "the visible work plan",
    "hitl": "ask the human",
    "delegation": "hand work to teammates or temporary subagents",
    "team": "messages, file hand-over and the task board",
    "platform": "facts about the platform itself (always available)",
}


def _first_sentence(text: str) -> str:
    text = " ".join(text.split())
    m = re.search(r"(?<!e\.g)(?<!i\.e)\.(?= )", text)  # the first full stop that ends a sentence
    return text[: m.end()] if m else text


def tools_reference(ctx: "ToolContext | None" = None) -> str:
    from ..tools import load_builtin_tools
    from ..tools.registry import TOOLS

    load_builtin_tools()
    have = set(ctx.agent.tools) if ctx else None
    lines = ["# Tools", "Tools are grouped in toolsets; a bot's `toolsets` setting decides which groups it gets."]
    for toolset, note in TOOLSET_NOTES.items():
        members = [t for t in TOOLS.values() if t.toolset == toolset]
        if not members:
            continue
        lines.append(f"\n## {toolset} — {note}")
        for t in members:
            missing = have is not None and t.name not in have
            lines.append(f"- `{t.name}`{' (not available to you in this run)' if missing else ''} — {_first_sentence(t.description)}")
    if have is not None:
        gone = sorted(t.name for t in TOOLS.values() if t.name not in have)
        lines.append("\nYou have " + str(len(have)) + " tools in this run." + (
            " Not available: " + ", ".join(gone) + " (toolset switched off for this bot, a temporary subagent's "
            "restrictions, the delegation depth limit, or no other bot exists to message)." if gone else ""))
    return "\n".join(lines)


# --------------------------------------------------------------------------- generated: live status

SESSION_KINDS = {
    "chat": "an ordinary conversation",
    "bot_chat": "this bot's permanent Bot Chat",
    "room_member": "your private view of a group room",
    "delegation": "a task a teammate delegated to you",
    "subagent": "a temporary subagent's task",
}


def status(ctx: "ToolContext | None") -> str:
    """The asking agent's own setup, read from the running objects. Never includes a key or a key's location."""
    if ctx is None:
        return "Live status is only available from inside a run."
    from ..llm import reasoning
    from ..memory import ExperienceStore, NotesMemory, SkillStore
    from ..sessions import SessionStore

    agent, prof, s, rt = ctx.agent, ctx.profile, ctx.settings, ctx.runtime
    try:
        cfg = s.model.resolved()
        model, key_set = cfg.model or "(not set)", bool(cfg.api_key)
    except ValueError:
        model, key_set = s.model.model or "(not set)", False
    try:
        sess = SessionStore(prof).get(ctx.session_id)
        kind, meta = sess.kind, sess.meta
    except KeyError:
        kind, meta = "chat", {}
    thinking = reasoning.current(s.model.thinking, s.model.reasoning_effort)
    chat_reasoning = str(meta.get("reasoning") or "").strip()
    out = ["# Your current setup (live)"]
    who = f"{prof.title} (@{prof.name})" + (", a bot in the roster" if prof.is_bot else ", the default single agent"
                                             if prof.name == "default" else ", a plain profile")
    out.append(f"- You: {who}. This session: {SESSION_KINDS.get(kind, kind)}; role in this run: {agent.role}"
               + (f"; delegation chain: {' → '.join(agent.chain)}" if agent.chain else "") + ".")
    out.append(f"- Model: provider `{s.model.provider}`, model `{model}`"
               + (" (chosen for this conversation)" if meta.get("model") else "")
               + f"; API key {'is set' if key_set else 'is NOT set'}.")
    out.append(f"- Thinking intensity: {chat_reasoning + ' (chosen for this conversation)' if chat_reasoning else thinking}"
               + f"; output cap {_show(s.model.max_tokens)} tokens per reply.")
    out.append(f"- Approvals: `{s.approvals.mode}` (wait {int(s.approvals.timeout)} s for the human; unattended requests: "
               f"{s.approvals.unattended}).")
    out.append(f"- Sandbox: backend `{ctx.backend.name}` (setting `{s.sandbox.backend}`, os_sandbox `{s.sandbox.os_sandbox}`); "
               f"command timeout {int(s.sandbox.command_timeout)} s"
               + (f"; container network `{s.sandbox.docker_network}`" if s.sandbox.backend == "docker" else "") + ".")
    out.append(f"- Folder: {ctx.workspace} — " + ("a folder the user chose for this conversation" if agent.custom_workspace
                                                  else "your private workspace")
               + (f"; group shared folder: `shared/` → {ctx.mounts['shared']}" if "shared" in ctx.mounts else "") + ".")
    on = [ts for ts in TOOLSET_NOTES if any(t.toolset == ts for t in agent.tools.values())]
    off = [ts for ts in TOOLSET_NOTES if ts not in on]
    out.append(f"- Tools: {len(agent.tools)} available, from toolsets {', '.join(on)}"
               + (f". Without: {', '.join(off)}" if off else "") + ". (`tools` topic lists each one.)")
    out.append(f"- Limits: {_show(s.max_iterations)} steps per run; run budget {agent.budget.describe()}"
               + ("" if agent.is_root else " — shared with the run that delegated to you")
               + f"; delegation depth {agent.depth} of {s.max_delegation_depth}; up to {s.max_parallel_delegations} "
               f"delegations in parallel; context compacted above {_show(s.context_char_budget)} characters.")
    notes = NotesMemory(prof)
    used = {t: notes.usage(t) for t in ("memory", "user")}
    try:
        n_exp = len(ExperienceStore(prof).all())
    except Exception:  # an unreadable store must not break a status report
        n_exp = 0
    out.append(f"- Memory: notes {len(notes.entries('memory'))} entries ({used['memory'][0]}/{used['memory'][1]} characters), "
               f"user profile {len(notes.entries('user'))} entries ({used['user'][0]}/{used['user'][1]}), "
               f"{n_exp} experiences, {len(SkillStore(prof).list())} skills; reflection "
               f"{'on' if s.reflection else 'off'}, {s.experience_top_k} experiences attached per task.")
    mates = [p for p in rt.profiles.list(bots_only=True) if p.name != prof.name and not p.meta.get("hidden")]
    if mates:
        out.append("- Other bots: " + ", ".join(f"@{p.name} ({p.title})" for p in mates) + ".")
    else:
        out.append("- Other bots: none — the user has not created a team; you work alone (temporary subagents are still possible).")
    rooms = [r for r in rt.rooms.list() if prof.name in (r.get("members") or [])]
    for r in rooms:
        lead = (r.get("settings") or {}).get("lead")
        here = " (this conversation)" if ctx.room_id and r["id"] == ctx.room_id else ""
        out.append(f"- Group '{r['name']}'{here}: members {', '.join('@' + m for m in r['members'])}; "
                   f"lead {('@' + lead) if lead else 'chosen per request'}; "
                   f"Fast Mode {'on' if (r.get('settings') or {}).get('fast_mode') else 'off'}.")
    out.append("You cannot change these yourself; the `configuration` topic says where the user changes each one.")
    return "\n".join(out)
