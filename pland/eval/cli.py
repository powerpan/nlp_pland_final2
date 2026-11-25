"""`pland eval` sub-commands."""

from __future__ import annotations

import json
from pathlib import Path


def add_arguments(parser) -> None:
    sub = parser.add_subparsers(dest="eval_cmd", required=True)
    r = sub.add_parser("run", help="run a task suite (directory, task file, or a built-in suite name)")
    r.add_argument("suite", help="dev | midterm | final | hard | memory_evolution | <path>")
    r.add_argument("--out", help="output directory (default: $PLAND_HOME/eval_runs)")
    r.add_argument("--backend", choices=["local", "docker"], default="local")
    r.add_argument("--memory", choices=["on", "off"], default="on", help="off = ablation without experience/memory")
    r.add_argument("--passes", type=int, default=1, help="run the suite N times in a row with memory carried over")
    r.add_argument("--only", nargs="*", help="run only these task ids")
    r.add_argument("--model", help="override the model id (e.g. deepseek-v4-pro)")
    r.add_argument("--thinking", dest="thinking", action="store_true", default=None, help="force DeepSeek thinking mode on")
    r.add_argument("--no-thinking", dest="thinking", action="store_false", help="force DeepSeek thinking mode off")
    r.add_argument("--reasoning", metavar="LEVEL", help="thinking intensity: off|default|minimal|low|medium|high|xhigh|max")
    r.add_argument("--label", default="", help="label appended to the run directory name")
    ls = sub.add_parser("list", help="list built-in suites and their tasks")
    ls.add_argument("suite", nargs="?")
    cmp_ = sub.add_parser("compare", help="compare finished runs side by side (Markdown)")
    cmp_.add_argument("run_dirs", nargs="+", help="NAME=DIR or DIR")
    cmp_.add_argument("--out", help="write the comparison to this file")
    agg = sub.add_parser("aggregate", help="mean ± std over repeated runs of one suite (Markdown)")
    agg.add_argument("run_dirs", nargs="+")
    agg.add_argument("--name", default="")
    agg.add_argument("--out")
    rep = sub.add_parser("report", help="re-render the Markdown report of a finished run")
    rep.add_argument("run_dir")
    rep.add_argument("--copy-to", help="also copy report.md here")


def main(args) -> int:
    from rich.console import Console

    console = Console()
    if args.eval_cmd == "list":
        from .tasks import SUITES_DIR, load_suite, resolve_suite

        suites = [resolve_suite(args.suite)] if args.suite else sorted(p for p in SUITES_DIR.iterdir() if p.is_dir())
        for sp in suites:
            meta, tasks = load_suite(sp)
            console.print(f"[bold]{meta.get('name')}[/] — {len(tasks)} tasks. {' '.join(str(meta.get('description') or '').split())[:160]}")
            for t in tasks:
                console.print(f"  {t.id:<36} {t.category:<8} {t.mode:<6} {len(t.checks)} checks")
        return 0
    if args.eval_cmd == "compare":
        from .report import render_comparison
        from .runner import load_results

        runs = []
        for item in args.run_dirs:
            name, _, path = item.partition("=") if "=" in item else (Path(item).name, "", item)
            runs.append((name, load_results(Path(path).expanduser())))
        text = render_comparison(runs)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            console.print(f"wrote {args.out}")
        else:
            console.print(text)
        return 0
    if args.eval_cmd == "aggregate":
        from .report import render_aggregate
        from .runner import load_results

        runs = [(Path(p).name, load_results(Path(p).expanduser())) for p in args.run_dirs]
        text = render_aggregate(args.name or runs[0][1]["summary"].get("suite") or "suite", runs)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            console.print(f"wrote {args.out}")
        else:
            console.print(text)
        return 0
    if args.eval_cmd == "report":
        from .report import render_report
        from .runner import load_results

        data = load_results(Path(args.run_dir))
        text = render_report(data["summary"], data["tasks"])
        out = Path(args.run_dir) / "report.md"
        out.write_text(text, encoding="utf-8")
        if args.copy_to:
            Path(args.copy_to).write_text(text, encoding="utf-8")
        console.print(f"wrote {out}")
        return 0
    from .runner import RunOptions, run_suite

    opts = RunOptions(out_dir=Path(args.out).expanduser() if args.out else None, backend=args.backend, memory=args.memory,
                      passes=args.passes, only=args.only, model=args.model, thinking=args.thinking, reasoning=args.reasoning,
                      label=args.label)
    runner, summary = run_suite(args.suite, opts, progress=lambda m: console.print(m))
    console.print_json(json.dumps({k: summary[k] for k in ("goal_completion_rate", "subtask_completion_rate", "outcomes", "time", "usage")}))
    console.print(f"report: {runner.run_dir / 'report.md'}")
    return 0
