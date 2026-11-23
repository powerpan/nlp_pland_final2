"""Reference implementations for the final suite, kept as source strings (they are written into scratch
workspaces as 'agent output' by the validator) and also exec'd here to compute expected values."""

from textwrap import dedent

CALC_INIT = dedent('''
    """Safe arithmetic expression evaluator (reference solution)."""
    import re

    __all__ = ["evaluate", "CalcError"]


    class CalcError(ValueError):
        pass


    _TOKEN = re.compile(r"\\s*(?:(\\d+\\.\\d*|\\.\\d+|\\d+)|([A-Za-z_][A-Za-z0-9_]*)|(\\*\\*|//|[-+*/%(),]))")
    _FUNCS = {"abs": (abs, 1, 1), "min": (min, 1, None), "max": (max, 1, None)}


    def _tokens(src):
        pos, out = 0, []
        src = src.rstrip()
        while pos < len(src):
            m = _TOKEN.match(src, pos)
            if not m or m.end() == pos:
                raise CalcError(f"unexpected character at {pos}: {src[pos:pos + 10]!r}")
            num, name, op = m.groups()
            if num is not None:
                if num.startswith("0") and len(num) > 1 and num.isdigit():
                    raise CalcError("leading zeros are not allowed")
                out.append(("num", float(num) if "." in num else int(num)))
            elif name is not None:
                out.append(("name", name))
            else:
                out.append(("op", op))
            pos = m.end()
        out.append(("end", None))
        return out


    class _Parser:
        def __init__(self, toks, variables):
            self.t, self.i, self.vars = toks, 0, variables

        def peek(self):
            return self.t[self.i]

        def take(self, kind=None, val=None):
            tok = self.t[self.i]
            if (kind and tok[0] != kind) or (val is not None and tok[1] != val):
                raise CalcError(f"unexpected token {tok[1]!r}")
            self.i += 1
            return tok

        def expr(self):
            v = self.term()
            while self.peek() in (("op", "+"), ("op", "-")):
                op = self.take()[1]
                r = self.term()
                v = v + r if op == "+" else v - r
            return v

        def term(self):
            v = self.unary()
            while self.peek()[0] == "op" and self.peek()[1] in ("*", "/", "//", "%"):
                op = self.take()[1]
                r = self.unary()
                try:
                    v = v * r if op == "*" else v / r if op == "/" else v // r if op == "//" else v % r
                except ZeroDivisionError:
                    raise CalcError("division by zero") from None
            return v

        def unary(self):
            if self.peek() in (("op", "-"), ("op", "+")):
                op = self.take()[1]
                v = self.unary()
                return -v if op == "-" else +v
            return self.power()

        def power(self):
            base = self.atom()
            if self.peek() == ("op", "**"):
                self.take()
                exp = self.unary()
                try:
                    return base ** exp
                except ZeroDivisionError:
                    raise CalcError("division by zero") from None
            return base

        def atom(self):
            kind, val = self.peek()
            if kind == "num":
                self.take()
                return val
            if kind == "name":
                self.take()
                if self.peek() == ("op", "("):
                    if val not in _FUNCS:
                        raise CalcError(f"unknown function {val}")
                    fn, lo, hi = _FUNCS[val]
                    self.take()
                    args = []
                    if self.peek() != ("op", ")"):
                        args.append(self.expr())
                        while self.peek() == ("op", ","):
                            self.take()
                            args.append(self.expr())
                    self.take("op", ")")
                    if len(args) < lo or (hi is not None and len(args) > hi):
                        raise CalcError(f"wrong number of arguments for {val}")
                    return fn(*args)
                if val not in self.vars:
                    raise CalcError(f"unknown variable {val}")
                return self.vars[val]
            if (kind, val) == ("op", "("):
                self.take()
                v = self.expr()
                self.take("op", ")")
                return v
            raise CalcError(f"unexpected token {val!r}")


    def evaluate(expr, variables=None):
        if not isinstance(expr, str):
            raise CalcError("expression must be a string")
        p = _Parser(_tokens(expr), dict(variables or {}))
        if p.peek()[0] == "end":
            raise CalcError("empty expression")
        v = p.expr()
        if p.peek()[0] != "end":
            raise CalcError(f"unexpected token {p.peek()[1]!r}")
        return v
''')

CALC_MAIN = dedent('''
    import sys

    from . import CalcError, evaluate


    def main(argv):
        if len(argv) != 1:
            print("usage: python -m calc EXPR", file=sys.stderr)
            return 2
        try:
            print(evaluate(argv[0]))
        except CalcError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0


    sys.exit(main(sys.argv[1:]))
''')

CALC_TESTS = dedent('''
    import pytest
    from calc import CalcError, evaluate

    @pytest.mark.parametrize("expr,want", [("1+2", 3), ("2*(3+4)", 14), ("7/2", 3.5), ("7//2", 3), ("-2**2", -4),
                                           ("2**3**2", 512), ("2**-1", 0.5), ("--3", 3), ("max(1, 2.5)", 2.5), ("abs(-3)", 3)])
    def test_values(expr, want):
        assert evaluate(expr) == want

    def test_vars():
        assert evaluate("x*2", {"x": 4}) == 8

    @pytest.mark.parametrize("bad", ["", "1 +", "(1", "1/0", "y", "foo(1)"])
    def test_errors(bad):
        with pytest.raises(CalcError):
            evaluate(bad)
''')


# --------------------------------------------------------------------------- data pipeline
PIPELINE = dedent('''
    """Order data pipeline (reference solution)."""
    import csv
    import json
    import re
    from collections import defaultdict
    from pathlib import Path

    RAW, OUT = Path("raw"), Path("out")


    def norm_name(s):
        return " ".join(str(s).split()).title()


    def parse_price(v):
        if v is None or isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace(",", "")
        if not re.fullmatch(r"\\d+(\\.\\d+)?", s):
            return None
        return float(s)


    def parse_qty(v):
        if isinstance(v, bool):
            return None
        if isinstance(v, int):
            return v if v > 0 else None
        if isinstance(v, str) and re.fullmatch(r"\\d+", v.strip()):
            q = int(v.strip())
            return q if q > 0 else None
        return None


    def parse_date(s):
        s = str(s).strip()
        m = re.fullmatch(r"(\\d{2})/(\\d{2})/(\\d{4})", s)
        if m:
            return f"{m[3]}-{m[2]}-{m[1]}"
        m = re.match(r"(\\d{4}-\\d{2}-\\d{2})", s)
        return m.group(1) if m else None


    def main():
        products = {r["sku"]: r for r in csv.DictReader(open(RAW / "products.csv", encoding="utf-8"))}
        fx = {r["currency"]: float(r["usd_rate"]) for r in csv.DictReader(open(RAW / "fx.csv", encoding="utf-8"))}
        records = []
        for r in csv.DictReader(open(RAW / "store_orders.csv", encoding="utf-8")):
            records.append((r["order_id"], r["date"], r["customer"], r["sku"], r["qty"], r["unit_price"], r["currency"]))
        for line in open(RAW / "web_orders.jsonl", encoding="utf-8"):
            if line.strip():
                o = json.loads(line)
                records.append((o.get("id"), o.get("ts"), o.get("customer"), o.get("sku"), o.get("quantity"),
                                o.get("price"), o.get("cur")))
        seen, valid = set(), []
        invalid = dups = 0
        for oid, date, cust, sku, qty, price, cur in records:
            if oid in seen:
                dups += 1
                continue
            seen.add(oid)
            q, p, d = parse_qty(qty), parse_price(price), parse_date(date)
            if q is None or p is None or sku not in products or cur not in fx or d is None:
                invalid += 1
                continue
            valid.append({"order_id": oid, "date": d, "customer": norm_name(cust), "sku": sku,
                          "category": products[sku]["category"], "qty": q, "revenue_usd": round(q * p * fx[cur], 2)})
        valid.sort(key=lambda r: (r["date"], r["order_id"]))
        OUT.mkdir(exist_ok=True)
        with open(OUT / "clean_orders.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["order_id", "date", "customer", "sku", "category", "qty", "revenue_usd"])
            for r in valid:
                w.writerow([r["order_id"], r["date"], r["customer"], r["sku"], r["category"], r["qty"], f"{r['revenue_usd']:.2f}"])
        cat, month, cust = defaultdict(float), defaultdict(float), defaultdict(float)
        for r in valid:
            cat[r["category"]] += r["revenue_usd"]
            month[r["date"][:7]] += r["revenue_usd"]
            cust[r["customer"]] += r["revenue_usd"]
        summary = {
            "valid_orders": len(valid), "invalid_rows": invalid, "duplicates_removed": dups,
            "total_revenue_usd": round(sum(r["revenue_usd"] for r in valid), 2),
            "revenue_by_category": {k: round(v, 2) for k, v in sorted(cat.items())},
            "revenue_by_month": {k: round(v, 2) for k, v in sorted(month.items())},
            "top_customer": max(cust, key=cust.get),
        }
        (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary


    if __name__ == "__main__":
        main()
''')


# --------------------------------------------------------------------------- CRM export (HITL)
CONVERT = dedent('''
    """users.json -> CRM importer CSV (reference solution)."""
    import json
    import sys


    def convert(src, dst):
        users = json.load(open(src, encoding="utf-8"))
        rows = []
        for u in users:
            email = (u.get("email") or "").strip().lower()
            if not email:
                continue
            d = u["signup"][:10]
            rows.append((email, f"{u['last_name']}, {u['first_name']}", f"{d[8:10]}.{d[5:7]}.{d[0:4]}", "1" if u["active"] else "0"))
        rows.sort(key=lambda r: r[0])
        with open(dst, "w", encoding="utf-8", newline="") as fh:
            fh.write("email;full_name;signup_date;active\\n")
            for r in rows:
                fh.write(";".join(r) + "\\n")


    if __name__ == "__main__":
        convert(sys.argv[1], sys.argv[2])
''')


# --------------------------------------------------------------------------- logkit (team)
LOGKIT_PARSER = dedent('''
    import re

    LINE = re.compile(r"^(\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z) (DEBUG|INFO|WARN|ERROR) \\[([a-z0-9_-]+)\\] (.+)$")
    FIELD = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(\\S+)$")


    def parse_line(line):
        m = LINE.match(line.strip())
        if not m:
            return None
        ts, level, comp, msg = m.groups()
        fields = {}
        for tok in msg.split():
            f = FIELD.match(tok)
            if f:
                fields[f.group(1)] = f.group(2)
        return {"ts": ts, "level": level, "component": comp, "message": msg, "fields": fields}
''')
LOGKIT_STATS = dedent('''
    def summarize(records):
        by_level, by_comp, errs = {}, {}, {}
        slowest = None
        for r in records:
            by_level[r["level"]] = by_level.get(r["level"], 0) + 1
            by_comp[r["component"]] = by_comp.get(r["component"], 0) + 1
            if r["level"] == "ERROR":
                errs[r["component"]] = errs.get(r["component"], 0) + 1
            ms = r["fields"].get("ms")
            if ms is not None and ms.isdigit() and (slowest is None or int(ms) > slowest["ms"]):
                slowest = {"component": r["component"], "ms": int(ms)}
        return {"total": len(records), "by_level": by_level, "by_component": by_comp,
                "errors_by_component": errs, "slowest": slowest}
''')
LOGKIT_INIT = "from .parser import parse_line\nfrom .stats import summarize\n\n__all__ = ['parse_line', 'summarize']\n"
LOGKIT_MAIN = dedent('''
    import json
    import sys
    from pathlib import Path

    from .parser import parse_line
    from .stats import summarize


    def run(path):
        records, malformed = [], 0
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = parse_line(line)
            if r is None:
                malformed += 1
            else:
                records.append(r)
        out = summarize(records)
        out["malformed"] = malformed
        return out


    if __name__ == "__main__":
        if len(sys.argv) != 2 or not Path(sys.argv[1]).is_file():
            print("usage: python -m logkit LOGFILE", file=sys.stderr)
            sys.exit(2)
        print(json.dumps(run(sys.argv[1]), sort_keys=True))
''')
LOGKIT_TESTS = dedent('''
    from logkit import parse_line, summarize

    L1 = "2026-10-01T12:00:03Z INFO [auth] login ok user=alice ms=120"
    L2 = "2026-10-01T12:00:04Z ERROR [db] timeout ms=950 retry=1"

    def test_parse_basic():
        r = parse_line(L1)
        assert r["level"] == "INFO" and r["component"] == "auth"

    def test_parse_fields():
        assert parse_line(L1)["fields"] == {"user": "alice", "ms": "120"}

    def test_parse_message():
        assert parse_line(L2)["message"] == "timeout ms=950 retry=1"

    def test_parse_bad_level():
        assert parse_line("2026-10-01T12:00:03Z FATAL [x] boom") is None

    def test_parse_garbage():
        assert parse_line("hello") is None

    def test_summary_counts():
        s = summarize([parse_line(L1), parse_line(L2)])
        assert s["total"] == 2 and s["by_level"] == {"INFO": 1, "ERROR": 1}

    def test_summary_errors():
        assert summarize([parse_line(L1), parse_line(L2)])["errors_by_component"] == {"db": 1}

    def test_summary_slowest():
        assert summarize([parse_line(L1), parse_line(L2)])["slowest"] == {"component": "db", "ms": 950}

    def test_summary_empty():
        assert summarize([])["slowest"] is None
''')


# --------------------------------------------------------------------------- deps audit (team)
AUDIT = dedent('''
    """Dependency audit against PyPI (reference solution)."""
    import json
    import re
    import sys
    import urllib.request


    def parse_requirements(text):
        out = []
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            m = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)\\s*==\\s*([0-9][0-9.]*)", line)
            if m:
                out.append((m.group(1).lower(), m.group(2)))
        return out


    def _key(v):
        parts = [int(x) for x in v.split(".")]
        while parts and parts[-1] == 0:
            parts.pop()
        return parts


    def is_outdated(pinned, latest):
        return _key(pinned) < _key(latest)


    def main(req_path, report_path):
        pins = parse_requirements(open(req_path, encoding="utf-8").read())
        rows, n_out = [], 0
        for name, ver in pins:
            info = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{name}/json", timeout=30))["info"]
            status = "outdated" if is_outdated(ver, info["version"]) else "up-to-date"
            n_out += status == "outdated"
            rows.append(f"| {name} | {ver} | {info['version']} | {info.get('requires_python') or ''} | {status} |")
        text = ("| Package | Pinned | Latest | Requires-Python | Status |\\n|---|---|---|---|---|\\n" + "\\n".join(rows)
                + f"\\n\\nOutdated: {n_out} of {len(pins)}\\n")
        open(report_path, "w", encoding="utf-8").write(text)


    if __name__ == "__main__":
        main(sys.argv[1], sys.argv[2])
''')


def exec_module(src: str, name: str = "m") -> dict:
    ns: dict = {"__name__": name}
    exec(compile(src, name, "exec"), ns)
    return ns
