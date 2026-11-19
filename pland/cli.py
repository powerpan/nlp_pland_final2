import argparse
import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

console = Console()


def _runtime(hitl=None):
    from .config import load_dotenv
    from .runtime import Runtime

    load_dotenv()
    return Runtime(hitl=hitl)


def cmd_chat(args) -> int:
    from .sessions import SessionStore

    rt = _runtime()
    try:
        profile = rt.profiles.get("default")
        store = SessionStore(profile)
        if args.session:
            session = store.get(args.session)
        else:
            session = store.create(kind="chat", title=(args.query or "Chat")[:60])
        if not args.query:
            console.print(f"Session {session.id}. Type /exit to leave.")
        while True:
            text = args.query or input("› ").strip()
            if text in {"/exit", "/quit"}:
                return 0
            if not text:
                continue
            result = rt.agent(profile, session.id).run(text)
            console.print(Panel(Markdown(result.text or result.error or "(no answer)")))
            if args.query:
                return 0 if result.ok else 1
    except EOFError:
        return 0
    finally:
        rt.shutdown()


def cmd_serve(args) -> int:
    import uvicorn

    from .server.app import create_app

    app = create_app()
    console.print(f"PlanD web UI on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pland", description="PlanD")
    commands = parser.add_subparsers(dest="cmd", required=True)
    chat = commands.add_parser("chat", help="Chat with the default agent")
    chat.add_argument("-q", "--query")
    chat.add_argument("--session")
    chat.set_defaults(fn=cmd_chat)
    serve = commands.add_parser("serve", help="Start the local Web UI")
    serve.add_argument("--port", type=int, default=8765)
    serve.set_defaults(fn=cmd_serve, host="127.0.0.1")
    doctor = commands.add_parser("doctor", help="Check provider and sandbox configuration")
    doctor.add_argument("--probe", action="store_true")
    doctor.set_defaults(fn=cmd_doctor)
    return parser


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
