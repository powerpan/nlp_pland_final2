"""final suite: 8 harder, longer tasks."""

import json

import final_data as D
from common import code, lit, norm_hash, write_suite, write_task
from snippets import GIT, HASH, LOAD, PYPI, PYTEST, use

SUITE = "final"


def chk(body, *snips, **subs):
    return code(use(*snips) + lit(body), **subs)


write_suite(SUITE, {
    "description": lit("""
        Final suite: 8 harder, multi-step tasks, each completable by a capable agent in roughly 40 steps / 10 minutes:
        a tokenizer+parser project with hidden tests and a CLI, a data pipeline that is re-run on unseen data, a
        debugging task spread over four modules, a git release workflow (branch, --no-ff merge, annotated tag, push to a
        local bare remote), a live-data research report verified against the source API at check time, an
        under-specified export that needs a clarification round-trip, and two team tasks — one with dependent subtasks
        (parser → stats → CLI → tests/docs) and one combining web research with coding.
    """).strip(),
    "defaults": {
        "timeout": 900,
        "max_iterations": 50,
        "memory": "carry",
        "hitl": {"approvals": "approve", "default_reply": "Use your best judgement and state any assumption you make."},
    },
}, header="PlanD eval suite `final` (format: pland/eval/SCHEMA.md)")

# =========================================================================== 01 expression evaluator
CALC_VALUES = ["1+2", "  3  ", "2*(3+4)", "2 * (3 + 4) - 5 % 3", "10 - 2 - 3", "100 / 10 / 5", "7/2", "4/2", "7//2",
               "-7 // 2", "-7 % 3", "7.5 // 2", "10 % 4 * 3", "-2**2", "(-2)**2", "2**3**2", "2**-1", "-2 ** -2",
               "2 ** -1 ** 2", "--3", "+-+3", "2 - -3", "-(3 + 4) * 2", ".5 + 1", "3.25 * 4", "2 ** 100", "0 ** 0",
               "max(1, 2.5, -3)", "min(4, 2) + abs(-3)", "abs(-2**2)", "max(min(5, 9), 2 * 3)", "(((1)))", "1 +\t2"]
CALC_VARS = [("2*x + y", {"x": 3, "y": 0.5}), ("max(x, y) ** 2", {"x": -4, "y": 3}), ("rate * 100 // 7", {"rate": 1.5}),
             ("_a1 - B2", {"_a1": 10, "B2": 2.5}), ("-x**2", {"x": 3})]
CALC_ERRORS = ["", "   ", "1 +", "(1", "1)", "2 3", "1 + * 2", "foo(1)", "x + 1", "1/0", "5 // 0", "5 % 0",
               "min()", "abs(1, 2)", "3 $ 4", "1.2.3", "()", "2 ** ", "max(1 2)"]
write_task(SUITE, "01-calc-evaluator.yaml", {
    "id": "final-calc-evaluator",
    "title": "Safe expression evaluator: tokenizer + parser, CLI, tests",
    "category": "coding",
    "prompt": lit("""
        Build a small, safe arithmetic expression evaluator as a Python package `calc/` in the workspace root
        (standard library only).

        API: `from calc import evaluate, CalcError`
        - `evaluate(expr, variables=None)` returns an `int` or a `float`; `variables` is an optional dict of names to numbers.
        - `CalcError` must be a subclass of `ValueError`. Raise it for every invalid input: syntax errors, unknown names
          or functions, wrong number of function arguments, and division or modulo by zero.

        Language — results must equal what Python itself computes for the same expression, including int vs float:
        - integer and decimal literals (`42`, `3.5`, `.5`), parentheses, and spaces/tabs anywhere between tokens;
        - binary operators `+ - * / // % **` with Python's precedence and associativity: `**` binds tighter than a unary
          minus on its left and is right-associative (`-2**2 == -4`, `2**3**2 == 512`, `2**-1 == 0.5`);
          `* / // %` bind tighter than `+ -`, all left-associative; `/` is true division (`4/2 == 2.0`);
        - unary `+` and `-`, also repeated (`--3 == 3`);
        - variables: identifiers `[A-Za-z_][A-Za-z0-9_]*` looked up in `variables`;
        - function calls `abs(x)` (exactly one argument), `min(a, b, ...)` and `max(a, b, ...)` (at least one argument).

        Do not use `eval`, `exec`, `compile` or the `ast` module anywhere in the package: write a tokenizer and a parser.

        Also provide:
        - a command-line entry point: `python -m calc "<expr>"` prints the result with `print()` and exits 0; on a
          `CalcError` it prints `error: <message>` to stderr and exits 1;
        - pytest tests in `tests/` (at least 10 test cases) that pass with `python -m pytest tests`.
    """),
    "checks": [
        {"id": "package-exists", "type": "file_exists", "path": "calc/__init__.py"},
        {"id": "no-eval", "type": "python", "code": chk(r"""
            import re
            files = sorted(path("calc").rglob("*.py"))
            assert files, "calc/ has no Python files"
            bad = []
            for f in files:
                src = re.sub(r"#.*", "", f.read_text(encoding="utf-8", errors="replace"))
                for pat in (r"(?<![\w.])(eval|exec|compile)\s*\(", r"(?m)^\s*(import\s+ast\b|from\s+ast\s+import)", r"__import__\s*\(\s*['\"]ast"):
                    bad += [f"{f.name}: {m.group(0)}" for m in re.finditer(pat, src)]
            assert not bad, f"forbidden eval/exec/compile/ast usage: {bad}"
        """)},
        {"id": "hidden-values", "type": "python", "code": chk(r"""
            import math
            from calc import evaluate, CalcError
            assert issubclass(CalcError, ValueError), "CalcError must subclass ValueError"
            env = {"__builtins__": {}, "min": min, "max": max, "abs": abs}
            cases = [(e, None) for e in __VALUES__] + __VARS__
            wrong = []
            for expr, vars_ in cases:
                want = eval(expr, dict(env, **(vars_ or {})))
                try:
                    got = evaluate(expr, vars_) if vars_ else evaluate(expr)
                except Exception as exc:
                    wrong.append(f"{expr!r} raised {type(exc).__name__}: {exc}")
                    continue
                same = type(got) is type(want) and (got == want or (isinstance(want, float) and math.isclose(got, want, rel_tol=1e-12)))
                if not same:
                    wrong.append(f"{expr!r} -> {got!r}, Python gives {want!r}")
            assert not wrong, f"{len(wrong)} wrong result(s): " + "; ".join(wrong[:8])
        """, VALUES=CALC_VALUES, VARS=CALC_VARS)},
        {"id": "hidden-errors", "type": "python", "code": chk(r"""
            from calc import evaluate, CalcError
            wrong = []
            for expr, vars_ in [(e, None) for e in __ERRORS__] + [("x + 1", {"y": 1})]:
                try:
                    evaluate(expr, vars_)
                except CalcError:
                    continue
                except Exception as exc:
                    wrong.append(f"{expr!r} raised {type(exc).__name__} instead of CalcError")
                    continue
                wrong.append(f"{expr!r} did not raise")
            assert not wrong, "; ".join(wrong)
        """, ERRORS=CALC_ERRORS)},
        {"id": "cli", "type": "python", "code": chk(r"""
            import subprocess, sys
            run = lambda e: subprocess.run([sys.executable, "-m", "calc", e], cwd=ws, capture_output=True, text=True, timeout=30)
            for expr, out in [("2*(3+4)", "14"), ("2**-1", "0.5"), ("7/2", "3.5")]:
                r = run(expr)
                assert r.returncode == 0 and r.stdout.strip() == out, f"python -m calc {expr!r}: exit {r.returncode}, stdout {r.stdout!r}, stderr {r.stderr[-300:]!r}"
            r = run("1/0")
            assert r.returncode == 1, f"python -m calc '1/0' should exit 1, got {r.returncode}"
            assert r.stderr.strip().startswith("error:"), f"stderr should start with 'error:', got {r.stderr!r}"
        """)},
        {"id": "agent-tests-pass", "type": "python", "code": chk(r"""
            pytest_in(ws, 10, "tests")
        """, PYTEST)},
    ],
}, header="final 01 — coding project: tokenizer + recursive-descent parser; hidden checks compare with Python semantics")

# =========================================================================== 02 data pipeline
RAW_MAIN = {"raw/products.csv": D.PRODUCTS, "raw/fx.csv": D.FX, "raw/store_orders.csv": D.STORE, "raw/web_orders.jsonl": D.WEB}
RAW_V2 = {"products.csv": D.PRODUCTS, "fx.csv": D.FX, "store_orders.csv": D.STORE_V2, "web_orders.jsonl": D.WEB_V2}
COMPARE = r'''
import csv, io, json, re
def compare_summary(s, E):
    assert set(s) == set(E), f"summary.json keys {sorted(s)} != {sorted(E)}"
    for k in ("valid_orders", "invalid_rows", "duplicates_removed"):
        assert s[k] == E[k], f"{k} = {s[k]!r}, expected {E[k]}"
    assert abs(float(s["total_revenue_usd"]) - E["total_revenue_usd"]) <= 0.011, f"total_revenue_usd = {s['total_revenue_usd']}, expected {E['total_revenue_usd']}"
    for k in ("revenue_by_category", "revenue_by_month"):
        assert set(s[k]) == set(E[k]), f"{k} keys {sorted(s[k])} != {sorted(E[k])}"
        for kk, v in E[k].items():
            assert abs(float(s[k][kk]) - v) <= 0.011, f"{k}[{kk}] = {s[k][kk]}, expected {v}"
    assert s["top_customer"] == E["top_customer"], f"top_customer = {s['top_customer']!r}, expected {E['top_customer']!r}"
def compare_csv(text, expected_text):
    rows = [r for r in csv.reader(io.StringIO(text)) if r]
    exp = [r for r in csv.reader(io.StringIO(expected_text)) if r]
    assert rows and rows[0] == exp[0], f"header {rows[0] if rows else None} != {exp[0]}"
    assert len(rows) == len(exp), f"{len(rows) - 1} data rows, expected {len(exp) - 1}"
    for got, want in zip(rows[1:], exp[1:]):
        assert got[:6] == want[:6], f"row {got} != expected {want}"
        assert re.fullmatch(r"\d+\.\d{2}", got[6]) and abs(float(got[6]) - float(want[6])) <= 0.011, f"revenue_usd {got[6]!r} != {want[6]}"
'''
write_task(SUITE, "02-data-pipeline.yaml", {
    "id": "final-data-pipeline",
    "title": "Re-runnable data-cleaning pipeline over messy CSV + JSONL exports",
    "category": "files",
    "prompt": lit("""
        Write a re-runnable data pipeline `pipeline.py` (single file, standard library only) in the workspace root and run
        it. `python pipeline.py`, started from the workspace root, must read the exports in `raw/` and write the results
        to `out/`. We will re-run it on next month's exports (same file names and formats, different rows), so it must
        compute everything from the files — no hard-coded values.

        Inputs:
        - `raw/store_orders.csv` — columns `order_id,date,customer,sku,qty,unit_price,currency`; `date` is either
          `YYYY-MM-DD` or `DD/MM/YYYY`; `unit_price` may contain thousands separators (`"1,049.00"`) or be empty.
        - `raw/web_orders.jsonl` — one JSON object per line with the keys `id`, `ts` (UTC timestamp such as
          `2026-10-05T14:03:00Z`), `customer`, `sku`, `quantity`, `price` (string or number; may be missing or invalid)
          and `cur` (currency).
        - `raw/products.csv` — `sku,name,category`.
        - `raw/fx.csv` — `currency,usd_rate` (the USD value of one unit of the currency).

        Rules:
        1. Process `store_orders.csv` first, then `web_orders.jsonl`, each in file order. A record whose order id already
           appeared in an earlier record (valid or not) is a duplicate: drop it and count it in `duplicates_removed`
           (duplicates are not counted as invalid).
        2. A non-duplicate record is invalid — drop it and count it in `invalid_rows` — if its quantity is not a positive
           whole number (in the CSV: digits only), its sku is not in products.csv, its price is missing or not a number,
           or its currency is not in fx.csv.
        3. Customer names: trim, collapse inner runs of whitespace to one space, then title-case (`" alice  cooper "` →
           `Alice Cooper`).
        4. `revenue_usd` of an order = quantity × unit price × usd_rate, rounded to 2 decimals.
        5. The order date is the calendar date `YYYY-MM-DD` of `date` / `ts`.

        Outputs:
        - `out/clean_orders.csv` with the header `order_id,date,customer,sku,category,qty,revenue_usd`, one row per valid
          order sorted by date, then order_id; `revenue_usd` written with exactly 2 decimals.
        - `out/summary.json` with exactly these keys: `valid_orders`, `invalid_rows`, `duplicates_removed` (integers),
          `total_revenue_usd` (sum of the per-order revenues, rounded to 2 decimals), `revenue_by_category` and
          `revenue_by_month` (objects mapping category / `YYYY-MM` to revenue, rounded to 2 decimals), and
          `top_customer` (the customer with the highest total revenue).
    """),
    "setup": {"files": RAW_MAIN},
    "checks": [
        {"id": "outputs-exist", "type": "python", "code": chk(r"""
            for f in ("pipeline.py", "out/clean_orders.csv", "out/summary.json"):
                assert path(f).is_file(), f"{f} is missing"
        """)},
        {"id": "summary-counts", "type": "python", "code": chk(r"""
            s, E = json.loads(path("out/summary.json").read_text(encoding="utf-8")), __E__
            for k in ("valid_orders", "invalid_rows", "duplicates_removed"):
                assert s.get(k) == E[k], f"{k} = {s.get(k)!r}, expected {E[k]}"
        """, COMPARE, E=D.PIPE_MAIN[0])},
        {"id": "summary-full", "type": "python", "code": chk(r"""
            compare_summary(json.loads(path("out/summary.json").read_text(encoding="utf-8")), __E__)
        """, COMPARE, E=D.PIPE_MAIN[0])},
        {"id": "clean-orders", "type": "python", "code": chk(r"""
            compare_csv(path("out/clean_orders.csv").read_text(encoding="utf-8"), __CSV__)
        """, COMPARE, CSV=D.PIPE_MAIN[1])},
        {"id": "rerun-on-new-data", "type": "python", "timeout": 180, "code": chk(r"""
            import shutil, subprocess, sys, tempfile
            with tempfile.TemporaryDirectory() as d:
                d = Path(d)
                shutil.copy(path("pipeline.py"), d / "pipeline.py")
                (d / "raw").mkdir()
                for name, text in __RAW__.items():
                    (d / "raw" / name).write_text(text, encoding="utf-8")
                r = subprocess.run([sys.executable, "pipeline.py"], cwd=d, capture_output=True, text=True, timeout=120)
                assert r.returncode == 0, "pipeline.py failed on next month's data: " + (r.stdout + r.stderr)[-800:]
                compare_summary(json.loads((d / "out/summary.json").read_text(encoding="utf-8")), __E2__)
                compare_csv((d / "out/clean_orders.csv").read_text(encoding="utf-8"), __CSV2__)
        """, COMPARE, RAW=RAW_V2, E2=D.PIPE_V2[0], CSV2=D.PIPE_V2[1])},
    ],
}, header="final 02 — data pipeline: messy multi-format inputs, exact outputs, and a hidden re-run on unseen data")

# =========================================================================== 03 multi-file debugging
INV_FILES = {"invoicing/__init__.py": '"""Invoicing toolkit."""\n', "invoicing/models.py": D.INV_MODELS,
             "invoicing/parser.py": D.INV_PARSER, "invoicing/pricing.py": D.INV_PRICING, "invoicing/report.py": D.INV_REPORT,
             "conftest.py": "# makes the project root importable for pytest\n", **D.INV_TESTS}
write_task(SUITE, "03-debug-invoicing.yaml", {
    "id": "final-debug-invoicing",
    "title": "Fix several bugs spread across a 4-module package",
    "category": "coding",
    "prompt": lit("""
        The `invoicing/` package is buggy: `python -m pytest tests` fails. The bugs are spread over several modules.
        Fix the package so that every function behaves as its docstring describes and all tests pass. Do not modify
        anything under `tests/` — the tests are correct. Keep the public API (module and function names) unchanged.
    """),
    "setup": {"files": INV_FILES},
    "checks": [
        {"id": "tests-unchanged", "type": "python", "code": chk(r"""
            for rel, h in __HASHES__.items():
                assert norm_hash(path(rel)) == h, f"{rel} was modified"
        """, HASH, HASHES={k: norm_hash(v) for k, v in D.INV_TESTS.items()})},
        {"id": "tests-pass", "type": "python", "code": chk(r"""
            pytest_in(ws, 7, "tests")
        """, PYTEST)},
        {"id": "hidden-models-parser", "type": "python", "code": chk(r"""
            from invoicing.models import Invoice, LineItem
            from invoicing.parser import parse_items, parse_price
            invs = [Invoice(c) for c in "XYZ"]
            invs[0].add(LineItem("A", 1, 1))
            assert invs[1].items == [] and invs[2].items == [], "invoices share their item list"
            for s, cents in [("0.57", 57), ("19.99", 1999), ("1.15", 115), ("7", 700), ("2.5", 250), ("0.07", 7), ("1234.56", 123456)]:
                assert parse_price(s) == cents, f"parse_price({s!r}) = {parse_price(s)!r}, expected {cents}"
            items = parse_items("sku;qty;unit_price\r\nP-1;5;1.15\r\n# skip\r\n  \r\nP-2 ;10; 0.57\r\nP-3;1;19.99")
            assert [(i.sku, i.qty, i.unit_cents) for i in items] == [("P-1", 5, 115), ("P-2", 10, 57), ("P-3", 1, 1999)], items
            assert [i.sku for i in parse_items("sku;qty;unit_price\nONLY;1;2.00")] == ["ONLY"]
            assert parse_items("sku;qty;unit_price\n") == []
        """)},
        {"id": "hidden-pricing-report", "type": "python", "code": chk(r"""
            from invoicing.models import Invoice, LineItem
            from invoicing.pricing import discount_percent, line_total
            from invoicing.report import format_report, summarize
            for q, pct in [(0, 0), (1, 0), (49, 0), (50, 5), (75, 5), (99, 5), (100, 10), (1000, 10)]:
                assert discount_percent(q) == pct, f"discount_percent({q}) = {discount_percent(q)}, expected {pct}"
            for args, cents in [(("X", 100, 15), 1350), (("Y", 50, 3), 143), (("Z", 101, 1), 91), (("W", 2, 333), 666)]:
                assert line_total(LineItem(*args)) == cents, f"line_total{args} = {line_total(LineItem(*args))}, expected {cents}"
            inv = Invoice("T", [LineItem("B", 1, 100), LineItem("A", 1, 100), LineItem("C", 2, 100)])
            assert summarize(inv) == ([("C", 200), ("A", 100), ("B", 100)], 400), summarize(inv)
            assert format_report(Invoice("Z Corp", [LineItem("K", 3, 1999)])) == "Invoice for Z Corp\nK: 59.97\nTOTAL: 59.97"
        """)},
    ],
}, header="final 03 — debugging across several files (6 bugs in 4 modules); tests must stay unchanged; hidden tests catch special-casing")

# =========================================================================== 04 git release workflow
APP_SETUP = {"app/greeter.py": D.GREETER, "app/test_greeter.py": D.GREETER_TEST, "app/VERSION": "0.1.0\n",
             "app/CHANGELOG.md": D.CHANGELOG}
write_task(SUITE, "04-git-release.yaml", {
    "id": "final-git-release",
    "title": "Feature branch, --no-ff merge, version bump, annotated tag, push",
    "category": "git",
    "prompt": lit("""
        `app/` is a git repository whose remote `origin` is the bare repository `remote/app.git` (already up to date with
        `main` and tag `v0.1.0`). Ship release 0.2.0 with this workflow:

        1. Create the branch `feature/greet-name` from `main`. On it, change `greet()` in `app/greeter.py` to
           `greet(name=None)`: it returns `Hello, <name>!` for a non-empty name (surrounding whitespace stripped) and
           `Hello, world!` when the name is None, empty or only whitespace. Add tests for the new behaviour to
           `app/test_greeter.py`. Commit on the branch.
        2. Merge the branch into `main` with a merge commit (`git merge --no-ff`); keep the branch.
        3. On `main`, change `VERSION` to `0.2.0` and add a `## 0.2.0` section describing the change to `CHANGELOG.md`,
           above `## 0.1.0`. Commit with the message `chore(release): 0.2.0`.
        4. Create the annotated tag `v0.2.0` on that commit.
        5. Push `main`, the branch `feature/greet-name` and the tag `v0.2.0` to `origin`.

        At the end the working tree must be clean and the tests must pass.
    """),
    "setup": {
        "files": APP_SETUP,
        "commands": [
            "git init -q --bare -b main remote/app.git",
            "cd app && git init -q -b main && git add -A && git commit -qm 'chore(release): 0.1.0' && "
            "git tag -a v0.1.0 -m 'Release 0.1.0' && git remote add origin ../remote/app.git && git push -q origin main v0.1.0",
        ],
    },
    "checks": [
        {"id": "clean-tree", "type": "git_clean", "repo": "app"},
        {"id": "main-pushed", "type": "python", "code": chk(r"""
            bare = str(path("remote/app.git"))
            remote_main = git("--git-dir", bare, "rev-parse", "refs/heads/main").stdout.strip()
            local_main = git("rev-parse", "refs/heads/main", cwd=path("app")).stdout.strip()
            assert remote_main and remote_main == local_main, "origin/main is not the local main (not pushed?)"
            merges = git("--git-dir", bare, "rev-list", "--merges", "--count", "v0.1.0..main").stdout.strip()
            assert merges.isdigit() and int(merges) >= 1, "main has no merge commit since v0.1.0 (use git merge --no-ff)"
        """, GIT)},
        {"id": "feature-branch", "type": "python", "code": chk(r"""
            bare = str(path("remote/app.git"))
            r = git("--git-dir", bare, "rev-parse", "refs/heads/feature/greet-name")
            assert r.returncode == 0, "branch feature/greet-name was not pushed to origin"
            anc = git("--git-dir", bare, "merge-base", "--is-ancestor", "refs/heads/feature/greet-name", "refs/heads/main")
            assert anc.returncode == 0, "feature/greet-name is not merged into main"
            changed = git("--git-dir", bare, "log", "--format=%H", "v0.1.0..refs/heads/feature/greet-name", "--", "greeter.py").stdout.split()
            assert changed, "no commit on feature/greet-name changes greeter.py"
        """, GIT)},
        {"id": "annotated-tag", "type": "python", "code": chk(r"""
            import re
            bare = str(path("remote/app.git"))
            r = git("--git-dir", bare, "cat-file", "-t", "refs/tags/v0.2.0")
            assert r.returncode == 0, "tag v0.2.0 was not pushed to origin"
            assert r.stdout.strip() == "tag", "v0.2.0 is a lightweight tag; an annotated tag is required"
            msg = git("--git-dir", bare, "log", "-1", "--format=%s", "v0.2.0^{commit}").stdout.strip()
            assert re.match(r"chore\(release\): 0\.2\.0\b", msg), f"the tagged commit's message is {msg!r}"
            anc = git("--git-dir", bare, "merge-base", "--is-ancestor", "v0.2.0^{commit}", "refs/heads/main")
            assert anc.returncode == 0, "the tagged commit is not on main"
        """, GIT)},
        {"id": "release-files", "type": "python", "code": chk(r"""
            bare = str(path("remote/app.git"))
            ver = git("--git-dir", bare, "show", "v0.2.0:VERSION").stdout.strip()
            assert ver == "0.2.0", f"VERSION at v0.2.0 is {ver!r}"
            log = git("--git-dir", bare, "show", "v0.2.0:CHANGELOG.md").stdout
            i, j = log.find("## 0.2.0"), log.find("## 0.1.0")
            assert i != -1 and j != -1 and i < j, "CHANGELOG.md at v0.2.0 needs a '## 0.2.0' section above '## 0.1.0'"
        """, GIT)},
        {"id": "code-at-tag", "type": "python", "code": chk(r"""
            import io, subprocess, sys, tarfile, tempfile
            bare = str(path("remote/app.git"))
            r = subprocess.run(["git", "--git-dir", bare, "archive", "--format=tar", "v0.2.0"], capture_output=True, timeout=60)
            assert r.returncode == 0, "cannot read the tree of v0.2.0"
            with tempfile.TemporaryDirectory() as d:
                with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tf:
                    tf.extractall(d)
                g = load("greeter_at_tag", Path(d) / "greeter.py")
                for args, want in [((), "Hello, world!"), ((None,), "Hello, world!"), (("",), "Hello, world!"),
                                   (("   ",), "Hello, world!"), (("Ada",), "Hello, Ada!"), (("  Bob ",), "Hello, Bob!")]:
                    got = g.greet(*args)
                    assert got == want, f"greet{args} = {got!r}, expected {want!r}"
                pytest_in(d, 2)
        """, LOAD, PYTEST)},
        {"id": "push-approved", "type": "hitl", "kind": "approval", "min": 1},
    ],
    "required": ["clean-tree", "main-pushed", "feature-branch", "annotated-tag", "release-files", "code-at-tag"],
}, header="final 04 — git workflow: branch, --no-ff merge, release commit, annotated tag, push branch+tag to a local bare remote")

# =========================================================================== 05 research report from live data
EOL = r'''
import json, re, urllib.request
from datetime import date, timedelta
def eol_data():
    req = urllib.request.Request("https://endoflife.date/api/python.json", headers={"User-Agent": "pland-eval"})
    data = json.load(urllib.request.urlopen(req, timeout=30))
    today = date.today()
    sup = [c for c in data if isinstance(c.get("eol"), str) and date.fromisoformat(c["eol"]) > today]
    return sorted(sup, key=lambda c: tuple(int(x) for x in c["cycle"].split(".")), reverse=True), today
def table_rows(doc):
    out = []
    for line in doc.splitlines():
        if line.strip().startswith("|"):
            cells = [c.strip().strip("`*_ ") for c in line.strip().strip("|").split("|")]
            if cells and re.fullmatch(r"(?i)(python\s*)?\d+\.\d+", cells[0]):
                out.append((re.sub(r"(?i)python\s*", "", cells[0]), cells, line))
    return out
def ok_latest(c, today):
    ok = {c["latest"]}
    if c.get("latestReleaseDate") and date.fromisoformat(c["latestReleaseDate"]) >= today - timedelta(days=2):
        major, minor, patch = c["latest"].split(".")[:3]
        if patch.isdigit() and int(patch) > 0:
            ok.add(f"{major}.{minor}.{int(patch) - 1}")
    return ok
'''
write_task(SUITE, "05-research-python-support.yaml", {
    "id": "final-research-python-support",
    "title": "Report on supported Python versions from live data",
    "category": "web",
    "prompt": lit("""
        Using live data from the endoflife.date API (`https://endoflife.date/api/python.json`), write
        `python_support.md` containing:

        1. A Markdown table of every Python release cycle that is still supported today (its `eol` date is after
           today's date), newest cycle first, with the columns `Cycle | Latest | Latest release date | EOL | PEP` —
           dates as `YYYY-MM-DD`, and PEP as the number of the cycle's release-schedule PEP (e.g. `PEP 619`).
        2. A line `Oldest supported: <cycle> (EOL <date>, <N> days from today)`.
        3. A line `Newest: <cycle>`.
        4. The latest version of `pip` on PyPI and the Python versions it requires, as the line
           `pip: <version> (requires Python <requires_python>)` — e.g. from `https://pypi.org/pypi/pip/json`.

        Do not rely on what you remember: these facts change over time.
    """),
    "checks": [
        {"id": "report-exists", "type": "file_exists", "path": "python_support.md"},
        {"id": "supported-rows", "type": "python", "code": chk(r"""
            sup, today = eol_data()
            rows = table_rows(path("python_support.md").read_text(encoding="utf-8"))
            listed = [r[0] for r in rows]
            want = [c["cycle"] for c in sup]
            assert sorted(listed) == sorted(want), f"table lists cycles {listed}, supported today are {want}"
            for c in sup:
                cells, line = next((r[1], r[2]) for r in rows if r[0] == c["cycle"])
                okv = ok_latest(c, today)
                assert any(re.search(r"(?<![\d.])" + re.escape(v) + r"(?![\d.])", line) for v in okv), f"{c['cycle']}: latest should be {c['latest']}: {line.strip()}"
                assert c["eol"] in line, f"{c['cycle']}: EOL {c['eol']} missing: {line.strip()}"
                if c["latest"] in line:
                    assert c["latestReleaseDate"] in line, f"{c['cycle']}: latest release date {c['latestReleaseDate']} missing"
                pep = c.get("pep") or ""
                num = re.sub(r"\D", "", pep).lstrip("0")
                if num:
                    assert re.search(r"(?i)pep[\s\-_]*0*" + num + r"\b", line), f"{c['cycle']}: PEP {num} missing: {line.strip()}"
        """, EOL)},
        {"id": "newest-first", "type": "python", "code": chk(r"""
            sup, today = eol_data()
            listed = [r[0] for r in table_rows(path("python_support.md").read_text(encoding="utf-8"))]
            key = lambda v: tuple(int(x) for x in v.split("."))
            assert listed and listed == sorted(listed, key=key, reverse=True), f"rows are not newest-first: {listed}"
        """, EOL)},
        {"id": "oldest-newest", "type": "python", "code": chk(r"""
            sup, today = eol_data()
            doc = path("python_support.md").read_text(encoding="utf-8")
            oldest, newest = sup[-1], sup[0]
            m = re.search(r"(?im)^\W*oldest supported\W*:?\W*(\d+\.\d+)\b(.*)$", doc)
            assert m, "no 'Oldest supported: ...' line"
            assert m.group(1) == oldest["cycle"], f"oldest supported is {oldest['cycle']}, not {m.group(1)}"
            assert oldest["eol"] in m.group(2), f"oldest-supported line lacks the EOL date {oldest['eol']}"
            days = (date.fromisoformat(oldest["eol"]) - today).days
            n = re.search(r"(-?\d+)\s*days", m.group(2))
            assert n and abs(int(n.group(1)) - days) <= 1, f"days until EOL should be {days}: {m.group(0).strip()}"
            m = re.search(r"(?im)^\W*newest\W*:?\W*(\d+\.\d+)\b", doc)
            assert m and m.group(1) == newest["cycle"], f"newest cycle is {newest['cycle']}"
        """, EOL)},
        {"id": "pip-line", "type": "python", "code": chk(r"""
            import re
            doc = path("python_support.md").read_text(encoding="utf-8")
            m = re.search(r"(?im)^\W*pip\W*:?\s*v?([0-9][\w.]*)\W*\(\s*requires\s+python\s*([^)]*)\)", doc)
            assert m, "no line 'pip: <version> (requires Python <requires_python>)'"
            info, ok = pypi("pip")
            assert m.group(1) in ok, f"pip latest is {info['version']}, not {m.group(1)}"
            norm = lambda s: re.sub(r"[\s`\\]", "", s)
            assert norm(m.group(2)) == norm(info.get("requires_python") or ""), f"pip requires_python is {info.get('requires_python')!r}"
        """, PYPI)},
    ],
}, header="final 05 — research + report with verifiable facts: the check fetches endoflife.date and PyPI at check time")

# =========================================================================== 06 under-specified export (HITL)
write_task(SUITE, "06-hitl-crm-export.yaml", {
    "id": "final-hitl-crm-export",
    "title": "Export users in 'the format our CRM importer expects' (spec only via clarification)",
    "category": "hitl",
    "prompt": lit("""
        Export our user list `data/users.json` to `export/users.csv` in the format our CRM importer expects.
        Also save the converter you used as `export/convert.py` (standard library only) so we can re-run it next month as
        `python export/convert.py <input.json> <output.csv>`.
    """),
    "setup": {"files": {"data/users.json": json.dumps(D.USERS, indent=2) + "\n"}},
    "hitl": {"replies": [{"match": ".*", "reply": D.CRM_SPEC}], "default_reply": D.CRM_SPEC},
    "checks": [
        {"id": "asked-format", "type": "hitl", "kind": "clarify", "min": 1},
        {"id": "export-exact", "type": "python", "code": chk(r"""
            got = path("export/users.csv").read_text(encoding="utf-8").replace("\r\n", "\n").rstrip("\n").split("\n")
            want = __WANT__.rstrip("\n").split("\n")
            assert got[:1] == want[:1], f"header {got[:1]} != {want[:1]}"
            assert got == want, "export differs; expected:\n" + "\n".join(want) + "\ngot:\n" + "\n".join(got)
        """, WANT=D.CRM_MAIN)},
        {"id": "converter-rerun", "type": "python", "code": chk(r"""
            import json, shutil, subprocess, sys, tempfile
            with tempfile.TemporaryDirectory() as d:
                d = Path(d)
                shutil.copy(path("export/convert.py"), d / "convert.py")
                (d / "next.json").write_text(json.dumps(__USERS__), encoding="utf-8")
                r = subprocess.run([sys.executable, "convert.py", "next.json", "next.csv"], cwd=d, capture_output=True, text=True, timeout=60)
                assert r.returncode == 0, "convert.py failed: " + (r.stdout + r.stderr)[-600:]
                got = (d / "next.csv").read_text(encoding="utf-8").replace("\r\n", "\n").rstrip("\n").split("\n")
                want = __WANT__.rstrip("\n").split("\n")
                assert got == want, "convert.py output on new data differs; expected:\n" + "\n".join(want) + "\ngot:\n" + "\n".join(got)
        """, USERS=D.USERS_V2, WANT=D.CRM_V2)},
    ],
    "required": ["export-exact", "converter-rerun"],
}, header="final 06 — HITL: the required output format is only available from the simulated user; exact output + re-run on new data")

# =========================================================================== 07 team with dependent subtasks
LOGKIT_SPEC = lit("""
    Team task — build the log-analysis package `logkit` in the room's shared folder, under `shared/logkit/`
    (standard library only). Log lines look like:

        2026-10-01T12:00:03Z INFO [auth] login ok user=alice ms=120

    i.e. `<timestamp> <LEVEL> [<component>] <message>`, single spaces between the parts.

    1. `logkit/parser.py` — `parse_line(line) -> dict | None`. Surrounding whitespace is ignored. The timestamp must
       match `YYYY-MM-DDTHH:MM:SSZ`, LEVEL is one of `DEBUG INFO WARN ERROR`, the component matches `[a-z0-9_-]+`, and
       the message (everything after `] `) must be non-empty; otherwise return `None`. Return
       `{"ts", "level", "component", "message", "fields"}` where `fields` maps every whitespace-separated message token of
       the form `key=value` (key `[A-Za-z_][A-Za-z0-9_]*`, value non-empty) to its value string; a later duplicate key wins.
    2. `logkit/stats.py` (needs the parser's record format) — `summarize(records) -> dict` with the keys `total` (number
       of records), `by_level` and `by_component` (counts, only for values that occur), `errors_by_component` (number of
       ERROR records per component, only components with at least one), and `slowest`: `{"component", "ms"}` of the
       record with the largest integer `ms` field (value made of digits only; ties → the first such record), or `None`.
    3. `logkit/__main__.py` (needs 1 and 2) — `python -m logkit <logfile>`, run from `shared/logkit/`, prints
       `json.dumps(result, sort_keys=True)` where `result` is the `summarize` output of all parseable lines plus
       `"malformed"`: the number of non-blank lines that `parse_line` rejects. A missing file: message on stderr, exit 2.
    4. `logkit/__init__.py` exporting `parse_line` and `summarize`; tests in `shared/logkit/tests/` (at least 8, passing
       with `python -m pytest tests` from `shared/logkit/`); and `shared/logkit/README.md` describing the API and the CLI.

    Plan this on the team board as separate tasks with their dependencies (parser → stats → CLI; tests and README after
    the code they cover), delegate them to the teammates, and verify the integrated package at the end.
""")
write_task(SUITE, "07-team-logkit.yaml", {
    "id": "final-team-logkit",
    "title": "Team builds a package with dependent subtasks (parser → stats → CLI → tests/docs)",
    "category": "team",
    "mode": "team",
    "team": {
        "room": True,
        "lead": "architect",
        "bots": [
            {"name": "architect", "title": "Architect", "description": "Designs interfaces, plans work with dependencies on the team board, delegates and integrates"},
            {"name": "coder", "title": "Coder", "description": "Implements Python code carefully from a specification"},
            {"name": "tester", "title": "Tester", "description": "Writes pytest test suites, runs them and reports defects"},
        ],
    },
    "prompt": LOGKIT_SPEC,
    "timeout": 1200,
    "checks": [
        {"id": "package-exists", "type": "file_exists", "path": "shared/logkit/logkit/__init__.py"},
        {"id": "hidden-parser", "type": "python", "code": chk(r"""
            import sys
            sys.path.insert(0, str(path("shared/logkit")))
            from logkit import parse_line
            r = parse_line("2026-10-01T12:00:03Z INFO [auth] login ok user=alice ms=120")
            assert r == {"ts": "2026-10-01T12:00:03Z", "level": "INFO", "component": "auth", "message": "login ok user=alice ms=120",
                         "fields": {"user": "alice", "ms": "120"}}, r
            r = parse_line("  2026-10-01T12:00:03Z WARN [db-pool_2] slow query a=1 a=2 c= =4\n")
            assert r and r["component"] == "db-pool_2" and r["fields"] == {"a": "2"}, r
            for bad in ["2026-10-01T12:00:03Z FATAL [x] boom", "2026-10-01T12:00:03Z INFO [X] upper", "2026-10-01T12:00:03Z INFO [x]",
                        "", "INFO [x] no timestamp", "2026-10-01 12:00:03 INFO [x] space ts", "2026-10-01T12:00:03Z INFO x no brackets"]:
                assert parse_line(bad) is None, f"parse_line({bad!r}) should be None"
        """)},
        {"id": "hidden-stats", "type": "python", "code": chk(r"""
            import sys
            sys.path.insert(0, str(path("shared/logkit")))
            from logkit import parse_line, summarize
            lines = ["2026-10-01T00:00:01Z INFO [a] x ms=5", "2026-10-01T00:00:02Z ERROR [b] y ms=9",
                     "2026-10-01T00:00:03Z ERROR [c] z ms=9", "2026-10-01T00:00:04Z INFO [c] w ms=x1"]
            s = summarize([parse_line(l) for l in lines])
            assert s == {"total": 4, "by_level": {"INFO": 2, "ERROR": 2}, "by_component": {"a": 1, "b": 1, "c": 2},
                         "errors_by_component": {"b": 1, "c": 1}, "slowest": {"component": "b", "ms": 9}}, s
            assert summarize([]) == {"total": 0, "by_level": {}, "by_component": {}, "errors_by_component": {}, "slowest": None}, summarize([])
        """)},
        {"id": "hidden-cli", "type": "python", "code": chk(r"""
            import json, subprocess, sys, tempfile
            cwd = path("shared/logkit")
            with tempfile.TemporaryDirectory() as d:
                log = Path(d) / "hidden.log"
                log.write_text(__LOG__, encoding="utf-8")
                r = subprocess.run([sys.executable, "-m", "logkit", str(log)], cwd=cwd, capture_output=True, text=True, timeout=60)
                assert r.returncode == 0, "python -m logkit failed: " + (r.stdout + r.stderr)[-600:]
                got = json.loads(r.stdout)
                assert got == __WANT__, f"CLI output {got} != expected {__WANT__}"
                r = subprocess.run([sys.executable, "-m", "logkit", str(Path(d) / "missing.log")], cwd=cwd, capture_output=True, text=True, timeout=60)
                assert r.returncode == 2, f"missing file should exit 2, got {r.returncode}"
        """, LOG=D.LOGKIT_HIDDEN_LOG, WANT=D.LOGKIT_EXPECT)},
        {"id": "team-tests-pass", "type": "python", "code": chk(r"""
            pytest_in(path("shared/logkit"), 8, "tests")
        """, PYTEST)},
        {"id": "readme", "type": "python", "code": chk(r"""
            text = path("shared/logkit/README.md").read_text(encoding="utf-8")
            for word in ("parse_line", "summarize", "python -m logkit"):
                assert word in text, f"README.md does not mention {word!r}"
        """)},
        {"id": "delegated", "type": "delegated", "min": 2},
        {"id": "board-planned", "type": "board_tasks", "min": 3},
    ],
    "required": ["package-exists", "hidden-parser", "hidden-stats", "hidden-cli", "team-tests-pass", "delegated", "board-planned"],
}, header="final 07 — team with dependent subtasks tracked on the board; hidden tests + CLI on an unseen log file")

# =========================================================================== 08 team: research + code
PINS = [("requests", "2.25.1"), ("six", "1.17.0"), ("attrs", "21.2.0"), ("idna", "2.10")]
AUDIT_ROWS = r'''
import re
def report_rows(doc):
    rows = []
    for line in doc.splitlines():
        if line.strip().startswith("|"):
            cells = [re.sub(r"[`*\\]", "", c).strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 5 and re.fullmatch(r"[A-Za-z0-9][\w.-]*", cells[0]) and cells[0].lower() != "package":
                rows.append(cells)
    return rows
def vkey(v):
    parts = [int(x) for x in v.split(".")]
    while parts and parts[-1] == 0:
        parts.pop()
    return parts
'''
write_task(SUITE, "08-team-deps-audit.yaml", {
    "id": "final-team-deps-audit",
    "title": "Researcher + coder build a dependency audit tool and report from live PyPI data",
    "category": "team",
    "mode": "team",
    "team": {
        "room": True,
        "lead": "lead",
        "bots": [
            {"name": "lead", "title": "Lead", "description": "Coordinates the team: plans, delegates and integrates results"},
            {"name": "researcher", "title": "Researcher", "description": "Finds and verifies facts on the web (search + fetch) and always reports the source URLs"},
            {"name": "coder", "title": "Coder", "description": "Implements Python code carefully from a specification"},
        ],
    },
    "prompt": lit("""
        Team task — dependency audit. `shared/requirements.txt` pins our production dependencies. Build a small audit
        tool and use it to produce a report:

        1. `shared/audit/audit.py` (standard library only) with
           - `parse_requirements(text) -> list[tuple[str, str]]`: the `(name, version)` pairs of all exact pins
             `name==version`, in file order, names lowercased; whitespace around `==` is allowed; comments (`# ...`, also
             at the end of a line), blank lines and every other kind of line (`-r ...`, `pkg>=1.0`, ...) are ignored;
           - `is_outdated(pinned, latest) -> bool`: compare dotted numeric versions component by component as integers
             (so `2.10` is newer than `2.9`); missing trailing components count as 0 (`1.0` equals `1.0.0`);
           - a CLI `python audit.py <requirements.txt> <report.md>` that looks up each pinned package's latest version on
             PyPI (JSON API `https://pypi.org/pypi/<name>/json`) and writes the report.
        2. `shared/audit/report.md`, produced by running the tool on `shared/requirements.txt`: a Markdown table with the
           columns `Package | Pinned | Latest | Requires-Python | Status` — one row per pin in file order, Requires-Python
           of the latest release, Status `outdated` or `up-to-date` — followed by the line `Outdated: <n> of <m>`.

        The researcher first confirms how to read the latest version and its Requires-Python from the PyPI JSON API, and
        at the end independently verifies the report's facts; the coder writes and runs the tool.
    """),
    "setup": {"files": {"shared/requirements.txt": D.REQUIREMENTS}},
    "timeout": 1200,
    "checks": [
        {"id": "hidden-unit", "type": "python", "code": chk(r"""
            a = load("audit_under_test", path("shared/audit/audit.py"))
            assert a.parse_requirements(path("shared/requirements.txt").read_text(encoding="utf-8")) == __PINS__
            text = "Django==4.2.1\n  numpy == 1.26.0  # pinned\n# x==1\nflask>=2\n-e .\n\nRequests==2.31.0\n"
            got = a.parse_requirements(text)
            assert got == [("django", "4.2.1"), ("numpy", "1.26.0"), ("requests", "2.31.0")], got
            for p, l, want in [("2.9", "2.10", True), ("2.10", "2.9", False), ("1.0", "1.0.0", False), ("1.0.0", "1.0", False),
                               ("21.2.0", "26.1.0", True), ("1.17.0", "1.17.0", False), ("0.9.9", "0.10", True), ("3.20", "3.3", False)]:
                assert a.is_outdated(p, l) is want, f"is_outdated({p!r}, {l!r}) should be {want}"
        """, LOAD, PINS=[tuple(p) for p in PINS])},
        {"id": "report-rows", "type": "python", "code": chk(r"""
            rows = report_rows(path("shared/audit/report.md").read_text(encoding="utf-8"))
            assert [r[0].lower() for r in rows] == [p for p, _ in __PINS__], f"rows {[r[0] for r in rows]} != pins in file order"
            for (name, pinned), r in zip(__PINS__, rows):
                info, ok = pypi(name)
                assert r[1] == pinned, f"{name}: pinned {r[1]!r} != {pinned}"
                assert r[2] in ok, f"{name}: latest {r[2]!r}, PyPI says {info['version']}"
                rp = re.sub(r"\s", "", info.get("requires_python") or "").replace("*", "")
                assert re.sub(r"\s", "", r[3]).replace("*", "") == rp, f"{name}: Requires-Python {r[3]!r} != {info.get('requires_python')!r}"
                want = "outdated" if vkey(pinned) < vkey(r[2]) else "up-to-date"
                assert r[4].lower() == want, f"{name}: status {r[4]!r}, expected {want}"
        """, PYPI, AUDIT_ROWS, PINS=PINS)},
        {"id": "outdated-line", "type": "python", "code": chk(r"""
            doc = path("shared/audit/report.md").read_text(encoding="utf-8")
            rows = report_rows(doc)
            n = sum(1 for r in rows if r[4].lower() == "outdated")
            m = re.search(r"(?im)^\W*outdated\W*:?\s*(\d+)\s+of\s+(\d+)", doc)
            assert m, "no 'Outdated: <n> of <m>' line"
            assert (int(m.group(1)), int(m.group(2))) == (n, __M__), f"'Outdated: {m.group(1)} of {m.group(2)}' should be {n} of __M__"
        """, AUDIT_ROWS, M=len(PINS))},
        {"id": "delegated-coder", "type": "delegated", "min": 1, "to": ["coder"]},
        {"id": "delegated-researcher", "type": "delegated", "min": 1, "to": ["researcher"]},
    ],
}, header="final 08 — team (lead/researcher/coder): research + code; unit tests hidden, report verified against PyPI at check time")
print("final written")
