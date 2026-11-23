"""Reference solutions for the final suite (scripted, no model)."""

import json
import subprocess
import sys
import urllib.request
from datetime import date

import final_data as D
import final_refs as R
from ref_dev import deleg, hitl


def run_py(c, args, cwd="."):
    r = subprocess.run([sys.executable, *args], cwd=str(c.path(cwd)), capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    return r


# ----------------------------------------------------------------------------- 01
def calc(c, impl=None):
    c.write("calc/__init__.py", impl or R.CALC_INIT)
    c.write("calc/__main__.py", R.CALC_MAIN)
    c.write("tests/test_calc.py", R.CALC_TESTS)
    if impl:
        return {}

    def uses_eval(c2):
        c2.write("calc/__init__.py", "class CalcError(ValueError):\n    pass\n\n\ndef evaluate(expr, variables=None):\n"
                                     "    try:\n        return eval(expr, {'__builtins__': {}, 'min': min, 'max': max, 'abs': abs}, dict(variables or {}))\n"
                                     "    except Exception as e:\n        raise CalcError(str(e))\n")
        c2.write("calc/__main__.py", R.CALC_MAIN)
        c2.write("tests/test_calc.py", R.CALC_TESTS)
        return {"expect_fail": ["no-eval"]}

    def left_assoc_pow(c2):  # ** parsed left-associative and below unary minus
        bad = R.CALC_INIT.replace("exp = self.unary()", "exp = self.atom()")
        calc(c2, impl=bad)
        return {"expect_fail": ["hidden-values"]}
    return {"negatives": {"uses-eval": uses_eval, "pow-binds-wrong": left_assoc_pow}}


# ----------------------------------------------------------------------------- 02
def pipeline(c):
    c.write("pipeline.py", R.PIPELINE)
    run_py(c, ["pipeline.py"])

    def hard_coded(c2):  # writes the right outputs for THIS data but ignores the inputs
        c2.write("out/summary.json", json.dumps(D.PIPE_MAIN[0]))
        c2.write("out/clean_orders.csv", D.PIPE_MAIN[1])
        c2.write("pipeline.py", "import json, pathlib\npathlib.Path('out').mkdir(exist_ok=True)\n"
                                f"pathlib.Path('out/summary.json').write_text(json.dumps({D.PIPE_MAIN[0]!r}))\n"
                                f"pathlib.Path('out/clean_orders.csv').write_text({D.PIPE_MAIN[1]!r})\n")
        return {"expect_fail": ["rerun-on-new-data"]}

    def dup_of_invalid_counted_invalid(c2):
        block_ok = ("        if oid in seen:\n            dups += 1\n            continue\n        seen.add(oid)\n")
        block_inv = ("        if q is None or p is None or sku not in products or cur not in fx or d is None:\n"
                     "            invalid += 1\n            continue\n")
        assert block_ok in R.PIPELINE and block_inv in R.PIPELINE
        bad = R.PIPELINE.replace(block_ok, "").replace(block_inv, block_inv + block_ok)
        assert bad != R.PIPELINE
        c2.write("pipeline.py", bad)
        run_py(c2, ["pipeline.py"])
        return {"expect_fail": ["summary-counts", "summary-full", "rerun-on-new-data"]}
    return {"negatives": {"hard-coded-outputs": hard_coded, "dup-rule-wrong": dup_of_invalid_counted_invalid}}


# ----------------------------------------------------------------------------- 03
def fix_invoicing(c, bankers=False):
    def sub(rel, old, new):
        p = c.path(rel)
        t = p.read_text()
        assert old in t, (rel, old)
        p.write_text(t.replace(old, new))
    sub("invoicing/models.py", "def __init__(self, customer, items=[]):\n        self.customer = customer\n        self.items = items",
        "def __init__(self, customer, items=None):\n        self.customer = customer\n        self.items = list(items) if items is not None else []")
    sub("invoicing/parser.py", "return int(float(text) * 100)", "from decimal import Decimal\n    return int(Decimal(text.strip()) * 100)")
    sub("invoicing/parser.py", "for line in lines[1:-1]:", "for line in lines[1:]:")
    sub("invoicing/pricing.py", "if qty > min_qty:", "if qty >= min_qty:")
    sub("invoicing/pricing.py", "return gross * (100 - pct) // 100",
        "return round(gross * (100 - pct) / 100)" if bankers else "return (gross * (100 - pct) + 50) // 100")
    sub("invoicing/report.py", "rows.sort(key=lambda r: (r[1], r[0]))", "rows.sort(key=lambda r: (-r[1], r[0]))")


def invoicing(c):
    fix_invoicing(c)

    def bankers(c2):
        fix_invoicing(c2, bankers=True)
        return {"expect_fail": ["tests-pass", "hidden-pricing-report"]}

    def weakened_tests(c2):
        fix_invoicing(c2)
        p = c2.path("tests/test_pricing.py")
        p.write_text(p.read_text().replace("== 1599", ">= 1598"))
        return {"expect_fail": ["tests-unchanged"]}
    return {"negatives": {"bankers-rounding": bankers, "edited-tests": weakened_tests}}


# ----------------------------------------------------------------------------- 04
NEW_GREETER = 'def greet(name=None):\n    name = (name or "").strip()\n    return f"Hello, {name}!" if name else "Hello, world!"\n'
NEW_TEST = D.GREETER_TEST + '\n\ndef test_named():\n    assert greet(" Ada ") == "Hello, Ada!"\n    assert greet("  ") == "Hello, world!"\n'


def git_release(c, *, lightweight=False, ff=False):
    c.sh("git checkout -q -b feature/greet-name", "app")
    c.write("app/greeter.py", NEW_GREETER)
    c.write("app/test_greeter.py", NEW_TEST)
    c.sh("git commit -qam 'feat: greet(name)'", "app")
    c.sh("git checkout -q main && git merge -q " + ("--ff-only" if ff else "--no-ff -m 'Merge branch feature/greet-name'") + " feature/greet-name", "app")
    c.write("app/VERSION", "0.2.0\n")
    c.write("app/CHANGELOG.md", "# Changelog\n\n## 0.2.0\n\n- greet() accepts an optional name.\n\n## 0.1.0\n\n- Initial release.\n")
    c.sh("git commit -qam 'chore(release): 0.2.0'", "app")
    c.sh("git tag v0.2.0" if lightweight else "git tag -a v0.2.0 -m 'Release 0.2.0'", "app")
    c.sh("git push -q origin main feature/greet-name v0.2.0", "app")
    if lightweight or ff:
        return {}
    return {"hitl": [hitl("approval", "git push", choice="once")],
            "negatives": {"lightweight-tag": lambda c2: (git_release(c2, lightweight=True), {"expect_fail": ["annotated-tag"]})[1],
                          "fast-forward": lambda c2: (git_release(c2, ff=True), {"expect_fail": ["main-pushed"]})[1]}}


# ----------------------------------------------------------------------------- 05
def research(c, include_eol=False):
    data = json.load(urllib.request.urlopen(urllib.request.Request("https://endoflife.date/api/python.json",
                                                                   headers={"User-Agent": "ref"}), timeout=30))
    today = date.today()
    sup = [x for x in data if isinstance(x["eol"], str) and (include_eol or date.fromisoformat(x["eol"]) > today)]
    sup.sort(key=lambda x: tuple(map(int, x["cycle"].split("."))), reverse=True)
    if include_eol:
        sup = sup[:7]
    live = [x for x in sup if date.fromisoformat(x["eol"]) > today]
    rows = "\n".join(f"| {x['cycle']} | {x['latest']} | {x['latestReleaseDate']} | {x['eol']} | PEP {int(x['pep'].split('-')[1])} |" for x in sup)
    old = live[-1]
    pip = json.load(urllib.request.urlopen("https://pypi.org/pypi/pip/json", timeout=30))["info"]
    c.write("python_support.md", "# Supported Python versions\n\n| Cycle | Latest | Latest release date | EOL | PEP |\n|---|---|---|---|---|\n"
            f"{rows}\n\nOldest supported: {old['cycle']} (EOL {old['eol']}, {(date.fromisoformat(old['eol']) - today).days} days from today)\n"
            f"Newest: {live[0]['cycle']}\n\npip: {pip['version']} (requires Python {pip['requires_python']})\n")
    if include_eol:
        return {"expect_fail": ["supported-rows"]}
    return {"negatives": {"lists-eol-cycles": lambda c2: research(c2, include_eol=True)}}


# ----------------------------------------------------------------------------- 06
def crm(c):
    c.write("export/convert.py", R.CONVERT)
    run_py(c, ["export/convert.py", "data/users.json", "export/users.csv"])

    def guessed(c2):
        users = json.loads(c2.path("data/users.json").read_text())
        c2.write("export/users.csv", "id,email,name\n" + "\n".join(f"{u['id']},{u['email']},{u['first_name']}" for u in users) + "\n")
        c2.write("export/convert.py", "import sys\n")
        return {"expect_fail": ["asked-format", "export-exact", "converter-rerun"]}
    return {"hitl": [hitl("clarify", "What format does the CRM importer expect?", D.CRM_SPEC)], "negatives": {"guessed-format": guessed}}


# ----------------------------------------------------------------------------- 07
def logkit(c, stats_src=None):
    base = "shared/logkit/"
    c.write(base + "logkit/__init__.py", R.LOGKIT_INIT)
    c.write(base + "logkit/parser.py", R.LOGKIT_PARSER)
    c.write(base + "logkit/stats.py", stats_src or R.LOGKIT_STATS)
    c.write(base + "logkit/__main__.py", R.LOGKIT_MAIN)
    c.write(base + "tests/test_logkit.py", R.LOGKIT_TESTS)
    c.write(base + "README.md", "# logkit\n\n`parse_line(line)`, `summarize(records)`; CLI: `python -m logkit app.log`\n")
    ev = [deleg("coder"), deleg("coder"), deleg("tester")]
    board = [{"status": "done"}] * 4
    if stats_src:
        return {"events": ev, "board": board, "expect_fail": ["hidden-stats", "hidden-cli"]}

    def last_tie(c2):  # ties go to the LAST record instead of the first
        return logkit(c2, stats_src=R.LOGKIT_STATS.replace("int(ms) > slowest", "int(ms) >= slowest"))
    return {"events": ev, "board": board, "negatives": {"tie-to-last": last_tie,
                                                        "no-team": lambda c2: (logkit(c2), {"events": [], "board": [],
                                                                                            "expect_fail": ["delegated", "board-planned"]})[1]}}


# ----------------------------------------------------------------------------- 08
def audit(c):
    c.write("shared/audit/audit.py", R.AUDIT)
    run_py(c, ["audit.py", "../requirements.txt", "report.md"], cwd="shared/audit")

    def string_compare(c2):  # compares versions as strings -> 2.10 < 2.9
        c2.write("shared/audit/audit.py", R.AUDIT.replace("return _key(pinned) < _key(latest)", "return pinned < latest"))
        run_py(c2, ["audit.py", "../requirements.txt", "report.md"], cwd="shared/audit")
        return {"events": [deleg("coder"), deleg("researcher")], "expect_fail": ["hidden-unit"]}
    return {"events": [deleg("researcher"), deleg("coder"), deleg("researcher")], "negatives": {"string-version-compare": string_compare}}


REFS = {
    "final-calc-evaluator": calc,
    "final-data-pipeline": pipeline,
    "final-debug-invoicing": invoicing,
    "final-git-release": git_release,
    "final-research-python-support": research,
    "final-hitl-crm-export": crm,
    "final-team-logkit": logkit,
    "final-team-deps-audit": audit,
}
