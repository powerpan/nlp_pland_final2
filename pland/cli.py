"""`pland` command line.

The CLI is the everyday single-agent surface: chat with one agent (any profile via -p), manage
profiles, inspect memory, run the evaluation harness, and start the web server. Bot Mode (team
rosters, group rooms, task board) lives in the web UI, mirroring Hermes where Bot Mode is a
Desktop feature and the CLI covers profiles/sessions only.
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
        sid = prof.canonical_chat_id()
    else:
        sid = store.create(kind="chat", title="").id

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

    if store.get(sid).title == "":
        store.update(sid, title=(args.query or "chat")[:60])
    if args.query:
        ask(args.query)
        rt.wait_reflections(120)  # let background reflection record the experience before the process exits
        return 0
    console.print(f"[bold]PlanD[/] · @{prof.name} ({prof.title}) · session {sid}. Type /help for commands, Ctrl-D to quit.")
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
        if text == "/memory":
            _print_memory(prof)
            continue
        if text == "/experience":
            _print_experience(prof)
            continue
        if store.get(sid).title == "":
            store.update(sid, title=text[:60])
        ask(text)


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
    elif args.action == "create":
        settings = {}
        if args.model or args.thinking:
            settings["model"] = {k: v for k, v in {"model": args.model, "thinking": args.thinking or None}.items() if v is not None}
        if args.backend:
            settings["sandbox"] = {"backend": args.backend}
        soul = Path(args.soul_file).read_text(encoding="utf-8") if args.soul_file else None
        p = pm.create(args.name, title=args.title, description=args.description or "", soul=soul, bot=not args.no_bot,
                      settings=settings, clone_from=args.clone)
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


def cmd_memory(args) -> int:
    rt = _runtime()
    prof = rt.profiles.get(args.profile)
    _print_memory(prof)
    _print_experience(prof)
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
    console.print(f"docker          {'[green]available[/]' if DockerBackend.available() else 'not available (local backend only)'}")
    if args.probe:
        from .probe import run_probe

        ok = run_probe(console)
        return 0 if ok else 1
    return 0


# --------------------------------------------------------------------------- serve / eval

def cmd_serve(args) -> int:
    import uvicorn

    from .server.app import create_app

    app = create_app()
    console.print(f"PlanD web UI on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_eval(args) -> int:
    from .eval.cli import main as eval_main

    return eval_main(args)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="pland", description="PlanD multi-agent platform")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("chat", help="chat with a single agent (default profile)")
    c.add_argument("-p", "--profile", default="default")
    c.add_argument("-q", "--query", help="one-shot question; print the answer and exit")
    c.add_argument("-c", "--continue", dest="cont", action="store_true", help="continue the most recent chat session")
    c.add_argument("--session", help="resume a specific session id")
    c.add_argument("--bot-chat", action="store_true", help="use the profile's canonical Bot Chat session")
    c.add_argument("--yolo", action="store_true", help="skip approval prompts for this run (hardline blocklist still applies)")
    c.set_defaults(fn=cmd_chat)

    p = sub.add_parser("profile", help="manage agent profiles (bots)")
    p.add_argument("action", choices=["list", "create", "show", "delete"])
    p.add_argument("name", nargs="?")
    p.add_argument("--title")
    p.add_argument("--description")
    p.add_argument("--soul-file")
    p.add_argument("--model")
    p.add_argument("--thinking", action="store_true")
    p.add_argument("--backend", choices=["local", "docker"])
    p.add_argument("--clone")
    p.add_argument("--no-bot", action="store_true", help="plain profile, not shown in the Bot Mode roster")
    p.set_defaults(fn=cmd_profile)

    m = sub.add_parser("memory", help="show a profile's memory and experiences")
    m.add_argument("-p", "--profile", default="default")
    m.set_defaults(fn=cmd_memory)

    d = sub.add_parser("doctor", help="check configuration; --probe makes a few real API calls")
    d.add_argument("--probe", action="store_true")
    d.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("serve", help="start the web UI / API server (Bot Mode)")
    s.set_defaults(host="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(fn=cmd_serve)

    e = sub.add_parser("eval", help="run the evaluation harness")
    from .eval.cli import add_arguments

    add_arguments(e)
    e.set_defaults(fn=cmd_eval)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "action", None) in {"create", "show", "delete"} and not getattr(args, "name", None):
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
