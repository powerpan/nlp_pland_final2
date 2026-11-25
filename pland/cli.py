"""`pland` command line.

The CLI is the everyday single-agent surface: chat with one agent (any profile via -p), manage
profiles, inspect memory, run the evaluation harness, and start the web server. Bot Mode (team
rosters, group rooms, task board) lives in the web UI; the CLI covers profiles and sessions.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

console = Console()


def _runtime(hitl=None):
    from .config import load_dotenv
    from .runtime import Runtime

    load_dotenv()
    return Runtime(hitl=hitl)


# --------------------------------------------------------------------------- chat

def _render_event(ev: dict, session_id: str) -> None:
    if ev.get("session_id") != session_id and ev["type"] not in {"delegation.started", "delegation.finished"}:
        return
    t = ev["type"]
    if t == "tool.started":
        console.print(f"  [dim]⚙ {ev['tool']}({ev.get('args', '')[:160]})[/]")
    elif t == "tool.finished" and not ev.get("ok"):
        console.print(f"  [red dim]✗ {ev['tool']}: {ev.get('preview', '')[:200]}[/]")
    elif t == "delegation.started":
        console.print(f"  [magenta]→ @{ev['profile']} delegated to {ev['to']}: {ev.get('goal', '')[:120]}[/]")
    elif t == "delegation.finished":
        console.print(f"  [magenta]← {ev['to']} finished ({ev['status']}, {ev.get('duration')}s)[/]")
    elif t == "experience.retrieved":
        console.print(f"  [cyan dim]↺ recalled {len(ev['ids'])} past experience(s)[/]")
    elif t == "experience.added":
        console.print(f"  [cyan dim]✎ experience recorded ({ev['outcome']})[/]")
    elif t == "todo.updated":
        marks = {"completed": "✓", "in_progress": "▸", "pending": "○", "cancelled": "✗"}
        items = ev.get("todos") or []
        done = sum(1 for x in items if x.get("status") == "completed")
        console.print(f"  [blue]plan {done}/{len(items)}:[/] " + "  ".join(f"{marks.get(x.get('status'), '○')} {x.get('content', '')[:40]}" for x in items[:8]))
    elif t == "approval.decided":
        color = "green" if ev["allowed"] else "red"
        console.print(f"  [{color} dim]{'✓' if ev['allowed'] else '✗'} {ev['summary'][:120]} — {ev['reason']}[/]")


def cmd_chat(args) -> int:
    from .hitl import ConsoleHITL, NoHumanHITL
    from .sessions import SessionStore

    hitl = NoHumanHITL(approve=args.yolo) if args.query and not sys.stdin.isatty() else ConsoleHITL(console)
    rt = _runtime(hitl)
    if not rt.profiles.exists(args.profile):
        console.print(f"[red]No profile '{args.profile}'. Create it with: pland profile create {args.profile}[/]")
        return 1
    prof = rt.profiles.get(args.profile)
    store = SessionStore(prof)
    if args.session:
        sid = args.session
    elif args.cont:
        recent = store.list(kinds=("chat",), limit=1)
        sid = recent[0].id if recent else store.create(kind="chat").id
    elif args.bot_chat:
        sid, bot_note = _bot_chat_for(prof, args.workspace)
    else:
        sid = store.create(kind="chat", title="").id
    if args.reasoning:
        try:
            _set_chat_reasoning(store, sid, args.reasoning)
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            return 1

    def ask(text: str) -> None:
        agent = rt.agent(prof, sid)
        if args.yolo:
            agent.settings.approvals.mode = "off"
        token = rt.bus.subscribe(lambda ev: _render_event(ev, sid))
        box: dict = {}
        th = threading.Thread(target=lambda: box.setdefault("r", agent.run(text)), daemon=True)
        th.start()
        try:
            while th.is_alive():
                th.join(0.2)
        except KeyboardInterrupt:
            rt.cancel(prof.name, sid)
            console.print("[yellow]stopping…[/]")
            th.join()
        finally:
            rt.bus.unsubscribe(token)
        res = box.get("r")
        if res is None:
            return
        style = "green" if res.ok else "red"
        console.print(Panel(Markdown(res.text or "(no answer)"), title=f"@{prof.name}", border_style=style,
                            subtitle=f"{res.status} · {res.iterations} steps · {res.tool_calls} tools · {res.duration:.1f}s · "
                                     f"{res.usage.prompt_tokens + res.usage.completion_tokens} tok"))

    resumed = bool(args.session or args.cont)
    try:
        folder_note = bot_note if args.bot_chat else _choose_workspace(prof, store, sid, args.workspace, resumed=resumed)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        return 1
    if store.get(sid).title == "":
        store.update(sid, title=(args.query or "chat")[:60])
    if args.query:
        ask(args.query)
        rt.wait_reflections(120)  # let background reflection record the experience before the process exits
        return 0
    console.print(f"[bold]PlanD[/] · @{prof.name} ({prof.title}) · thinking {_chat_reasoning(prof, store, sid)[0]} · "
                  f"session {sid}. Type /help for commands, Ctrl-D to quit.")
    console.print(f"[dim]folder: {_effective_workspace(prof, store, sid)}{folder_note}[/]")
    while True:
        try:
            text = input("\n› ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return 0
        if not text:
            continue
        if text in {"/exit", "/quit"}:
            return 0
        if text == "/help":
            console.print("/new  start a new session · /sessions  list sessions · /resume <id>  switch session\n"
                          "/reasoning [off|default|minimal|low|medium|high|xhigh|max|reset]  thinking intensity for this chat\n"
                          "/model [deepseek-flash|deepseek-v4-pro|reset]  model for this chat\n"
                          "/workspace [folder|default]  the folder this chat works in\n"
                          "/memory  show memory · /experience  list experiences · /exit")
            continue
        if text == "/new":
            sid = store.create(kind="chat", title="").id
            console.print(f"[dim]new session {sid}[/]")
            continue
        if text == "/sessions":
            for s in store.list(limit=15):
                console.print(f"  {s.id}  [{s.kind}] {s.title[:60]}  ({time.strftime('%m-%d %H:%M', time.localtime(s.updated))})")
            continue
        if text.startswith("/resume "):
            sid = text.split(maxsplit=1)[1].strip()
            store.get(sid)
            console.print(f"[dim]switched to {sid}[/]")
            continue
        if text == "/workspace" or text.startswith("/workspace "):
            sid = _workspace_command(prof, store, sid, text[len("/workspace"):].strip()) or sid
            continue
        if text == "/model" or text.startswith("/model "):
            _model_command(prof, store, sid, text[len("/model"):].strip())
            continue
        if text == "/reasoning" or text.startswith("/reasoning "):
            _reasoning_command(prof, store, sid, text[len("/reasoning"):].strip())
            continue
        if text == "/memory":
            _print_memory(prof)
            continue
        if text == "/experience":
            _print_experience(prof)
            continue
        if store.get(sid).title == "":
            store.update(sid, title=text[:60])
        ask(text)


def _chat_reasoning(prof, store, sid) -> tuple[str, str]:
    """(effective choice, where it comes from) for a chat: its own override, else the profile setting."""
    from .llm import reasoning

    own = store.get(sid).meta.get("reasoning")
    if own:
        return reasoning.current(True, own), "this chat"
    m = prof.settings().model
    return reasoning.current(m.thinking, m.reasoning_effort), f"profile @{prof.name}"


def _set_chat_reasoning(store, sid, choice: str) -> str | None:
    from .llm import reasoning

    word = choice.strip().lower()
    level = None if word == "reset" else reasoning.parse(word)
    if word == "default":
        level = "default"  # explicit "provider default" for this chat, distinct from inheriting the profile
    store.patch_meta(sid, {"reasoning": level})
    return level


def _reasoning_command(prof, store, sid, arg: str) -> None:
    """`/reasoning` (show) · `/reasoning <level>` (this chat) · `/reasoning reset` (back to the profile setting).
    Session-scoped; the profile-wide default is set with `pland setup` or the web settings."""
    from .llm import reasoning

    if arg:
        try:
            _set_chat_reasoning(store, sid, arg)
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            return
    choice, source = _chat_reasoning(prof, store, sid)
    provider = prof.settings().model.provider
    console.print(f"thinking intensity: [bold]{reasoning.describe(choice, provider)}[/] ({source})")
    if not arg:
        for c in reasoning.choices(provider):
            console.print(f"  {'•' if c == choice else ' '} {c:8} {reasoning.description(c, provider)}")
        console.print("[dim]/reasoning <level> sets it for this chat · /reasoning reset uses the profile setting[/]")


def _effective_workspace(prof, store, sid) -> str:
    from .workspace import resolve

    folder, error = resolve(prof.workspace, store.get(sid).meta)
    return f"{folder}  [red](missing: {error})[/]" if error else str(folder)


def _set_workspace(prof, store, sid, value: str) -> str | None:
    """Store the folder for a chat ("default": the bot's own workspace). Raises ValueError if unsuitable."""
    from .config import pland_home
    from .workspace import check_workspace

    word = value.strip()
    if word.lower() in {"default", "reset", "private"}:
        store.patch_meta(sid, {"workspace": None})
        return None
    folder = check_workspace(Path(word).expanduser() if word.startswith(("~", "/")) else Path.cwd() / word,
                             pland_root=pland_home())
    store.patch_meta(sid, {"workspace": str(folder)})
    return str(folder)


def _choose_workspace(prof, store, sid, flag: str | None, *, resumed: bool) -> str:
    """-w wins; a new chat otherwise works in the launch folder when that is a sensible project folder;
    resumed chats and Bot Chats keep the folder stored with them. Returns a note for the header."""
    from .config import pland_home
    from .workspace import launch_folder_default

    if flag:
        _set_workspace(prof, store, sid, flag)
        return " (from -w)"
    if resumed:
        return ""
    folder, reason = launch_folder_default(Path.cwd(), pland_root=pland_home())
    if folder:
        store.patch_meta(sid, {"workspace": str(folder)})
        return " (the folder you started pland in)"
    return f" (@{prof.name}'s own workspace: {reason}; use -w <folder> or /workspace to pick one)"


def _bot_chat_for(prof, flag: str | None) -> tuple[str, str]:
    """A bot keeps one Bot Chat per folder: the one for -w, else for the launch folder when that is a project
    folder, else its home Bot Chat (private workspace). Returns (session id, note for the header)."""
    from .config import pland_home
    from .workspace import check_workspace, launch_folder_default

    if flag:
        word = flag.strip()
        if word.lower() in {"default", "reset", "private"}:
            return prof.bot_chat_id(None), " (from -w)"
        folder = check_workspace(Path(word).expanduser() if word.startswith(("~", "/")) else Path.cwd() / word,
                                 pland_root=pland_home())
        return prof.bot_chat_id(str(folder)), f" (@{prof.name}'s Bot Chat for this folder)"
    folder, reason = launch_folder_default(Path.cwd(), pland_root=pland_home())
    if folder:
        return prof.bot_chat_id(str(folder)), f" (@{prof.name}'s Bot Chat for the folder you started pland in)"
    return prof.bot_chat_id(None), f" (@{prof.name}'s home Bot Chat: {reason})"


def _workspace_command(prof, store, sid, arg: str) -> str | None:
    """`/workspace` (show) · `/workspace <folder>` · `/workspace default`. In a Bot Chat these switch to the bot's
    chat for that folder (one context per folder); `/workspace move <folder>` takes this conversation along
    instead. Returns the session to continue in when it changed."""
    from .config import pland_home
    from .workspace import check_workspace

    switched = None
    if arg:
        bot_chat = store.get(sid).kind == "bot_chat"
        move = arg.split(maxsplit=1)[0] == "move"
        target = arg.split(maxsplit=1)[1] if move and " " in arg else ("" if move else arg)
        try:
            if bot_chat and not move:
                word = target.strip()
                folder = None if word.lower() in {"default", "reset", "private"} else str(check_workspace(
                    Path(word).expanduser() if word.startswith(("~", "/")) else Path.cwd() / word, pland_root=pland_home()))
                new = prof.bot_chat_id(folder)
                if new != sid:
                    switched = sid = new
                    console.print(f"[dim]switched to @{prof.name}'s Bot Chat for this folder (session {sid}); "
                                  "the previous one is kept and you can switch back the same way[/]")
            else:
                if bot_chat and target.strip().lower() not in {"default", "reset", "private"}:
                    other = prof.bot_chat_id(str(check_workspace(Path(target.strip()).expanduser(), pland_root=pland_home())),
                                             create=False)
                    if other and other != sid:
                        raise ValueError(f"@{prof.name} already has a Bot Chat for that folder; use /workspace <folder> to switch")
                _set_workspace(prof, store, sid, target)
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            return None
    own = store.get(sid).meta.get("workspace")
    console.print(f"folder: [bold]{_effective_workspace(prof, store, sid)}[/] "
                  f"({'chosen for this conversation' if own else f'@{prof.name} own workspace'})")
    if not arg:
        if store.get(sid).kind == "bot_chat":
            console.print("[dim]/workspace <folder> switches to the Bot Chat for that folder (its own context) · "
                          "/workspace move <folder> takes this conversation along · /workspace default: home Bot Chat[/]")
            for chat in prof.bot_chats():
                console.print(f"[dim]  {'•' if chat['id'] == sid else ' '} {chat['workspace'] or '(private workspace)'}[/]")
        else:
            console.print("[dim]/workspace <folder> works there from the next message · /workspace default goes back[/]")
    return switched


def _model_command(prof, store, sid, arg: str) -> None:
    """`/model` (show) · `/model <id>` (this chat) · `/model reset` (back to the profile's model)."""
    if arg:
        word = arg.strip()
        if word.lower() not in {"reset", "default"} and prof.settings().model.provider == "deepseek" and not word.startswith("deepseek-"):
            console.print("[red]this profile uses DeepSeek; choose a deepseek-* model[/]")
            return
        store.patch_meta(sid, {"model": None if word.lower() in {"reset", "default"} else word})
    own = store.get(sid).meta.get("model")
    base = prof.settings().model.resolved().model
    console.print(f"model: [bold]{own or base}[/] ({'this chat' if own else f'profile @{prof.name}'})")
    if not arg:
        console.print(f"[dim]choices: {', '.join(MODELS)} · /model <id> sets it for this chat · /model reset[/]")


def _print_memory(prof) -> None:
    from .memory import NotesMemory, SkillStore

    console.print(Panel(NotesMemory(prof).render(), title=f"memory of @{prof.name}"))
    skills = SkillStore(prof).list()
    if skills:
        console.print("skills: " + ", ".join(s["name"] for s in skills))


def _print_experience(prof) -> None:
    from .memory import ExperienceStore

    table = Table("id", "outcome", "task", "uses", "helpful", "utility")
    for e in ExperienceStore(prof).all()[-30:]:
        table.add_row(e.id, e.outcome, e.task[:70], str(e.uses), f"{e.helpful}/{e.helpful + e.unhelpful}", f"{e.utility:.2f}")
    console.print(table)


# --------------------------------------------------------------------------- profiles

def cmd_profile(args) -> int:
    rt = _runtime()
    pm = rt.profiles
    if args.action == "list":
        table = Table("name", "title", "bot", "model", "backend", "description")
        for p in pm.list():
            s = p.summary()
            table.add_row(p.name, p.title, "✓" if p.is_bot else "", f"{s['provider']}/{s['model']}", s["backend"], p.description[:50])
        console.print(table)
    elif args.action in {"create", "set"}:
        try:
            settings = _profile_settings(args)
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            return 1
        soul = Path(args.soul_file).read_text(encoding="utf-8") if args.soul_file else None
        if args.action == "set":
            p = pm.update(args.name, title=args.title, description=args.description, soul=soul, settings=settings)
            console.print(f"updated profile [bold]{p.name}[/]")
        else:
            p = pm.create(args.name, title=args.title, description=args.description or "", soul=soul,
                          bot=not args.no_bot, settings=settings, clone_from=args.clone)
            console.print(f"created profile [bold]{p.name}[/] at {p.home}")
    elif args.action == "show":
        p = pm.get(args.name)
        console.print_json(json.dumps(p.summary(), default=str))
        console.print(Panel(p.soul, title="SOUL.md"))
        _print_memory(p)
    elif args.action == "delete":
        pm.delete(args.name)
        console.print(f"deleted {args.name}")
    return 0


def _profile_settings(args) -> dict:
    from .llm import reasoning

    settings: dict = {}
    model: dict = {}
    if args.model:
        model["model"] = args.model
    if args.thinking:
        model["thinking"] = True
    if args.reasoning:
        model.update(reasoning.to_settings(args.reasoning))
    if model:
        settings["model"] = model
    if args.backend:
        settings["sandbox"] = {"backend": args.backend}
    return settings


def cmd_team(args) -> int:
    from .team.templates import apply_template, list_templates

    if args.action == "list" or not args.template:
        for t in list_templates():
            console.print(f"[bold]{t['id']}[/] — {t['title']}: {t['description']}")
            for b in t["bots"]:
                console.print(f"  @{b['name']:<11} {b['title']:<16} thinking {b.get('reasoning') or 'default':<8} "
                              f"{b.get('backend') or 'local':<7} {', '.join(b.get('toolsets') or [])}")
            for g in t["groups"]:
                console.print(f"  group {g['name']!r}: {', '.join('@' + m for m in g['members'])} (lead @{g.get('lead')})")
        if args.action == "apply":
            console.print("[red]name a template: pland team apply <id>[/]")
            return 2
        return 0
    rep = apply_template(_runtime(), args.template, update=args.update)
    for key, label in (("created", "created"), ("updated", "updated"), ("skipped", "already existed (kept; --update to overwrite)")):
        if rep[key]:
            console.print(f"{label}: {', '.join('@' + n for n in rep[key])}")
    for g in rep["groups"]:
        console.print(f"group {g['name']!r}: {g['status']}")
    for note in rep["notes"]:
        console.print(f"[yellow]{note}[/]")
    console.print("Open the web UI (pland serve) → Bots to chat with them or message a group.")
    return 0


def cmd_memory(args) -> int:
    rt = _runtime()
    prof = rt.profiles.get(args.profile)
    _print_memory(prof)
    _print_experience(prof)
    return 0


# --------------------------------------------------------------------------- setup

MODELS = ("deepseek-flash", "deepseek-v4-pro")


def cmd_setup(args) -> int:
    """Interactive setup: API key (if missing) → model → thinking intensity → sandbox → approvals, saved to
    a profile (the default agent unless -p is given). Flags skip the matching prompt; without a terminal
    only the flags are applied."""
    import os
    from getpass import getpass

    from rich.prompt import Prompt

    from .config import PROVIDERS, default_provider, pland_home
    from .llm import reasoning
    from .sandbox import DockerBackend

    rt = _runtime()
    if not rt.profiles.exists(args.profile):
        console.print(f"[red]No profile '{args.profile}'.[/]")
        return 1
    prof = rt.profiles.get(args.profile)
    s = prof.settings()
    interactive = sys.stdin.isatty() and not args.yes
    console.print(f"[bold]PlanD setup[/] · profile @{prof.name} · PLAND_HOME {pland_home()}")

    spec = PROVIDERS[default_provider()]
    if not os.environ.get(spec.key_env):
        if not interactive:
            console.print(f"[red]{spec.key_env} is not set.[/] Put it in {pland_home() / '.env'} and run setup again.")
            return 1
        key = getpass(f"{spec.key_env} (input hidden, saved to {pland_home() / '.env'}): ").strip()
        if not key:
            console.print("[red]No key entered; nothing saved.[/]")
            return 1
        env = pland_home() / ".env"
        env.parent.mkdir(parents=True, exist_ok=True)
        lines = [ln for ln in (env.read_text().splitlines() if env.exists() else []) if not ln.startswith(spec.key_env + "=")]
        env.write_text("\n".join(lines + [f"{spec.key_env}={key}"]) + "\n")
        env.chmod(0o600)
        os.environ[spec.key_env] = key
        console.print(f"[green]saved {spec.key_env}[/] to {env}")

    model = args.model or s.model.model or spec.default_model or MODELS[0]
    if interactive and not args.model and spec.name == "deepseek":
        model = Prompt.ask("Model", choices=list(MODELS), default=model if model in MODELS else MODELS[0])

    # The thinking intensity is offered right after the model is chosen.
    choice = args.reasoning or reasoning.current(s.model.thinking, s.model.reasoning_effort)
    if spec.supports_thinking and interactive and not args.reasoning:
        offered = reasoning.choices(spec.name)
        console.print("Thinking intensity:")
        for c in offered:
            console.print(f"  {c:8} {reasoning.description(c, spec.name)}")
        choice = Prompt.ask("Thinking intensity", choices=list(offered), default=choice if choice in offered else "default")
    try:
        model_settings = {"model": model, **reasoning.to_settings(choice)}
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        return 1

    backend = args.backend or s.sandbox.backend
    if interactive and not args.backend:
        backends = ["local", "docker"] if DockerBackend.available() else ["local"]
        backend = Prompt.ask("Sandbox backend", choices=backends, default=backend if backend in backends else "local")
    approvals = args.approvals or s.approvals.mode
    if interactive and not args.approvals:
        approvals = Prompt.ask("Approvals (manual asks before risky actions)", choices=["manual", "smart", "off"],
                               default=approvals)

    rt.profiles.update(prof.name, settings={"model": model_settings, "sandbox": {"backend": backend},
                                            "approvals": {"mode": approvals}})
    console.print(f"[green]saved[/] @{prof.name}: model {model} · thinking {reasoning.describe(choice, spec.name)} · "
                  f"sandbox {backend} · approvals {approvals}")
    console.print("[dim]Per chat: /reasoning <level> in `pland chat`, or the thinking menu next to the web composer.[/]")
    return 0


# --------------------------------------------------------------------------- doctor

def cmd_doctor(args) -> int:
    from .config import ModelConfig, default_provider, pland_home
    from .llm.guard import ForbiddenProviderError, check_endpoint
    from .sandbox import DockerBackend

    cfg = ModelConfig(provider=default_provider()).resolved()
    console.print(f"PLAND_HOME      {pland_home()}")
    console.print(f"provider        {cfg.provider}  model={cfg.model}  base_url={cfg.base_url}")
    console.print(f"api key         {'set' if cfg.api_key else '[red]MISSING[/] (add it to .env)'}")
    try:
        check_endpoint(cfg.provider, cfg.base_url)
        console.print("provider guard  [green]ok[/] (only DeepSeek/HKGAI endpoints are allowed)")
    except ForbiddenProviderError as exc:
        console.print(f"provider guard  [red]{exc}[/]")
    try:
        from .llm import reasoning

        m = _runtime().profiles.get("default").settings().model
        console.print(f"thinking        {reasoning.describe(reasoning.current(m.thinking, m.reasoning_effort), m.provider)}"
                      " (default agent · change with `pland setup`, or /reasoning per chat)")
    except Exception:  # noqa: BLE001 - diagnostics must not fail on a broken profile
        pass
    import os as _os
    import subprocess as _sp

    # the web tools use DeepSeek's Search/Fetch APIs whenever its key is set, whichever provider runs the model
    if _os.environ.get("DEEPSEEK_API_KEY"):
        console.print("web tools       DeepSeek Search/Fetch API" + (" (HKGAI has none of its own)" if cfg.provider != "deepseek" else ""))
    else:
        console.print("web tools       [yellow]no DeepSeek key[/]: search scrapes DuckDuckGo/Bing, fetch downloads directly")

    seatbelt = sys.platform == "darwin" and _os.path.exists("/usr/bin/sandbox-exec")
    console.print(f"local sandbox   {'[green]Seatbelt (macOS) — commands confined to the workspace[/]' if seatbelt else '[yellow]none — use the docker backend for isolation[/]'}")
    if DockerBackend.available():
        image = _sp.run(["docker", "image", "inspect", "pland-sandbox:py3.11"], capture_output=True).returncode == 0
        console.print(f"docker          [green]available[/] · sandbox image {'built' if image else 'not built yet (built on first use)'}")
    else:
        console.print("docker          not available (local backend only)")
    if args.probe:
        from .probe import run_probe

        ok = run_probe(console)
        return 0 if ok else 1
    return 0


# --------------------------------------------------------------------------- serve / desktop / eval

def cmd_serve(args) -> int:
    import uvicorn

    from .server.app import create_app

    allowed = [h.strip() for h in (getattr(args, "allowed_hosts", "") or "").split(",") if h.strip()]
    app = create_app(bind_host=args.host, allowed_hosts=allowed)
    console.print(f"PlanD web UI on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _is_pland_server(pid: int) -> bool:
    """Whether `pid` still is a PlanD server: pids are reused after a reboot, so a stale pid file must never
    stop an unrelated program."""
    import subprocess

    try:
        out = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "pland.cli" in out and "serve" in out


def _pland_running(url: str) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(f"{url}/api/status", timeout=1.5) as r:
            return r.status == 200 and json.loads(r.read().decode("utf-8")).get("app") == "pland"
    except (OSError, ValueError):
        return False


def _open_app_window(url: str, *, plain: bool = False) -> str:
    """Open the UI like a desktop app: a Chromium-family browser's --app window (no tabs or address bar),
    else the default browser."""
    import shutil
    import subprocess
    import webbrowser

    if not plain:
        if sys.platform == "darwin":
            for app in ("Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium"):
                if any((Path(base) / f"{app}.app").exists() for base in ("/Applications", Path.home() / "Applications")):
                    subprocess.Popen(["open", "-na", app, "--args", f"--app={url}"])
                    return f"{app} app window"
        else:
            for exe in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "msedge",
                        "brave-browser"):
                path = shutil.which(exe)
                if path:
                    subprocess.Popen([path, f"--app={url}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
                    return f"{exe} app window"
    webbrowser.open(url)
    return "default browser"


def cmd_desktop(args) -> int:
    """`pland desktop`: the web UI as a desktop app, from any folder. Reuses a PlanD
    server already on the port, otherwise starts one in the background (log in PLAND_HOME/logs/server.log)."""
    import os
    import signal
    import socket
    import subprocess

    from .config import pland_home

    url = f"http://{args.host}:{args.port}"
    pidfile = pland_home() / "run" / "server.pid"
    if args.stop:
        try:
            pid = int(pidfile.read_text().strip())
        except (OSError, ValueError):
            pid = 0
        if pid > 1 and _is_pland_server(pid):
            try:
                os.killpg(pid, signal.SIGTERM)
                console.print(f"stopped the PlanD server (pid {pid})")
            except OSError:
                console.print("no background PlanD server started by `pland desktop` is running")
        else:
            console.print("no background PlanD server started by `pland desktop` is running"
                          + (f" (stale pid file: pid {pid} is not a PlanD server)" if pid else ""))
        pidfile.unlink(missing_ok=True)
        return 0
    if _pland_running(url):
        console.print(f"PlanD is already running at {url}")
    else:
        with socket.socket() as s:
            if s.connect_ex((args.host, args.port)) == 0:
                console.print(f"[red]port {args.port} is in use by another program[/]; try: pland desktop --port 8770")
                return 1
        log = pland_home() / "logs" / "server.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        pidfile.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "ab") as out:
            proc = subprocess.Popen([sys.executable, "-I", "-m", "pland.cli", "serve", "--host", args.host, "--port", str(args.port)],
                                    stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, cwd=str(pland_home()),
                                    start_new_session=True)
        pidfile.write_text(str(proc.pid))
        for _ in range(100):
            if _pland_running(url):
                break
            if proc.poll() is not None:
                console.print(f"[red]the server exited (code {proc.returncode}); see {log}[/]")
                return 1
            time.sleep(0.2)
        else:
            console.print(f"[red]the server did not come up within 20 s; see {log}[/]")
            return 1
        console.print(f"started PlanD at {url} in the background (log: {log})")
    if not args.no_open:
        console.print(f"opened in the {_open_app_window(url, plain=args.browser)}")
    console.print("[dim]stop the background server with: pland desktop --stop[/]")
    return 0


def cmd_eval(args) -> int:
    from .eval.cli import main as eval_main

    return eval_main(args)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="pland", description="PlanD multi-agent platform")
    sub = ap.add_subparsers(dest="cmd")  # no command: chat

    c = sub.add_parser("chat", help="chat with a single agent (default profile)")
    c.add_argument("-p", "--profile", default="default")
    c.add_argument("-q", "--query", help="one-shot question; print the answer and exit")
    c.add_argument("-c", "--continue", dest="cont", action="store_true", help="continue the most recent chat session")
    c.add_argument("--session", help="resume a specific session id")
    c.add_argument("--bot-chat", action="store_true", help="use the profile's canonical Bot Chat session")
    c.add_argument("--yolo", action="store_true", help="skip approval prompts for this run (hardline blocklist still applies)")
    c.add_argument("--reasoning", metavar="LEVEL", help="thinking intensity for this chat: off|default|minimal|low|medium|high|xhigh|max")
    c.add_argument("-w", "--workspace", metavar="FOLDER",
                   help="folder this chat works in (default for a new chat: the folder you start pland in; "
                        "'default' = the bot's own workspace)")
    c.set_defaults(fn=cmd_chat)

    p = sub.add_parser("profile", help="manage agent profiles (bots)")
    p.add_argument("action", choices=["list", "create", "set", "show", "delete"])
    p.add_argument("name", nargs="?")
    p.add_argument("--title")
    p.add_argument("--description")
    p.add_argument("--soul-file")
    p.add_argument("--model")
    p.add_argument("--thinking", action="store_true")
    p.add_argument("--reasoning", metavar="LEVEL", help="thinking intensity: off|default|minimal|low|medium|high|xhigh|max")
    p.add_argument("--backend", choices=["local", "docker"])
    p.add_argument("--clone")
    p.add_argument("--no-bot", action="store_true", help="plain profile, not shown in the Bot Mode roster")
    p.set_defaults(fn=cmd_profile)

    tm = sub.add_parser("team", help="list or apply team templates (ready-made bots and groups)")
    tm.add_argument("action", choices=["list", "apply"])
    tm.add_argument("template", nargs="?")
    tm.add_argument("--update", action="store_true", help="overwrite settings of bots that already exist")
    tm.set_defaults(fn=cmd_team)

    m = sub.add_parser("memory", help="show a profile's memory and experiences")
    m.add_argument("-p", "--profile", default="default")
    m.set_defaults(fn=cmd_memory)

    st = sub.add_parser("setup", help="set up the API key, model, thinking intensity, sandbox and approvals")
    st.add_argument("-p", "--profile", default="default")
    st.add_argument("--model", choices=MODELS)
    st.add_argument("--reasoning", metavar="LEVEL", help="thinking intensity: off|default|minimal|low|medium|high|xhigh|max")
    st.add_argument("--backend", choices=["local", "docker"])
    st.add_argument("--approvals", choices=["manual", "smart", "off"])
    st.add_argument("-y", "--yes", action="store_true", help="no prompts: apply only the given flags")
    st.set_defaults(fn=cmd_setup)

    d = sub.add_parser("doctor", help="check configuration; --probe makes a few real API calls")
    d.add_argument("--probe", action="store_true")
    d.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("serve", help="start the web UI / API server (Bot Mode)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--allowed-hosts", default="", metavar="HOSTS",
                   help="comma-separated host names (e.g. a reverse proxy's domain) accepted as Host and as the Origin "
                        "of writes, besides this computer")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(fn=cmd_serve)

    dk = sub.add_parser("desktop", aliases=["app"], help="open the web UI as a desktop app window (starts the server if needed)")
    dk.add_argument("--host", default="127.0.0.1")
    dk.add_argument("--port", type=int, default=8765)
    dk.add_argument("--browser", action="store_true", help="open a normal browser tab instead of an app window")
    dk.add_argument("--no-open", action="store_true", help="only make sure the server is running")
    dk.add_argument("--stop", action="store_true", help="stop the background server started by `pland desktop`")
    dk.set_defaults(fn=cmd_desktop)

    e = sub.add_parser("eval", help="run the evaluation harness")
    from .eval.cli import add_arguments

    add_arguments(e)
    e.set_defaults(fn=cmd_eval)
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0].startswith("-") and argv[0] not in {"-h", "--help"}):
        argv = ["chat", *argv]  # `pland`, `pland -w DIR`, `pland -q "..."` mean chat
    args = build_parser().parse_args(argv)
    if getattr(args, "action", None) in {"create", "set", "show", "delete"} and not getattr(args, "name", None):
        console.print("[red]a profile name is required[/]")
        return 2
    try:
        return int(args.fn(args) or 0)
    except KeyboardInterrupt:
        return 130
    except (KeyError, ValueError) as exc:
        console.print(f"[red]{exc}[/]")
        return 1


if __name__ == "__main__":
    sys.exit(main())
