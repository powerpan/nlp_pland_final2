"""memory_evolution suite: 6 tasks of the same kind (request-log statistics in an exact format).

The team conventions that decide the numbers are given ONLY in task 1's clarification answer. In tasks 2-6 the
simulated user refuses to repeat them ("same as last time"), so only memory (notes, experiences, skills) carried over
from earlier tasks lets the agent get them right."""

import json
import math
import random
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from common import code, lit, write_suite, write_task

SUITE = "memory_evolution"

CONVENTIONS = lit("""
    Our team conventions for request-log statistics (please keep them for all future log reports):
    1. Health checks don't count: drop every request whose path starts with /health (e.g. /health, /healthz,
       /health/ready) before computing anything.
    2. Only server errors are errors: status 500-599. 4xx responses are client mistakes and are NOT errors.
    3. An endpoint is the path without its query string (/search?q=a and /search?q=b are both /search).
    4. Latencies are reported in whole milliseconds: convert other units (s, µs) to ms and round to the nearest integer.
    5. p95 uses the nearest-rank method: sort the latencies ascending and take the value at 1-based rank ceil(0.95 × N).
    6. Lines that cannot be parsed as a request are skipped and not counted anywhere.
    7. slowest_endpoint is the endpoint with the highest mean latency; ties go to the alphabetically first endpoint.
""").strip()
REFUSE = "Same conventions as always — I explained them in detail last time and I'm not going to repeat them."

OUTPUT_SPEC = lit("""
    The file must contain exactly these five lines, in this order, and nothing else:
    requests: <number of requests counted>
    errors: <number of requests counted as errors>
    error_rate: <errors / requests × 100, with exactly two decimals>%
    p95_ms: <95th-percentile latency in whole milliseconds>
    slowest_endpoint: <endpoint with the highest mean latency>
""").strip()


# --------------------------------------------------------------------------- statistics
def stats(reqs, *, include_health=False, errors_4xx=False, keep_query=False, interp_p95=False):
    """reqs: list of (path_with_query, status, latency_ms_float_or_int). Returns the five output values."""
    rows = []
    for path, status, ms in reqs:
        if not include_health and path.split("?")[0].startswith("/health"):
            continue
        ep = path if keep_query else path.split("?")[0]
        rows.append((ep, status, int(math.floor(ms + 0.5))))
    n = len(rows)
    errs = sum(1 for _, s, _ in rows if (400 if errors_4xx else 500) <= s <= 599)
    lat = sorted(ms for _, _, ms in rows)
    if interp_p95:
        p95 = round(statistics.quantiles(lat, n=100, method="inclusive")[94])
    else:
        p95 = lat[math.ceil(0.95 * n) - 1]
    by = defaultdict(list)
    for ep, _, ms in rows:
        by[ep].append(ms)
    means = {ep: sum(v) / len(v) for ep, v in by.items()}
    top = max(means.values())
    slow = sorted(ep for ep, m in means.items() if m == top)
    rate = errs / n * 100
    # avoid ambiguous half-way rounding of error_rate
    assert abs(rate * 100 - math.floor(rate * 100) - 0.5) > 1e-6
    return {"requests": n, "errors": errs, "error_rate": f"{rate:.2f}", "p95_ms": p95, "slowest_endpoint": slow[0],
            "_tie": len(slow) > 1}


ENDPOINTS = [("/api/users", 40, 140), ("/api/orders", 60, 220), ("/api/items", 30, 120), ("/login", 80, 260),
             ("/api/cart", 50, 180)]


def gen_requests(seed, n, *, slow_ep, slow_range, search_spike):
    """Generate (path, status, ms) tuples with the traps every task needs."""
    rnd = random.Random(seed)
    reqs = []
    for _ in range(n):
        r = rnd.random()
        if r < 0.15:
            path = rnd.choice(["/api/search?q=" + rnd.choice(["shoes", "hat", "red+shirt", "bag", "socks"]),
                               "/api/search?q=" + rnd.choice(["coat", "scarf"]) + "&page=" + str(rnd.randint(2, 4))])
            lo, hi = 90, 260
        elif r < 0.25:
            path, (lo, hi) = slow_ep, slow_range
        else:
            ep, lo, hi = rnd.choice(ENDPOINTS)
            path = ep + (f"?id={rnd.randint(1, 99)}" if rnd.random() < 0.3 else "")
        s = rnd.random()
        status = 200 if s < 0.72 else rnd.choice([201, 204, 304]) if s < 0.80 else rnd.choice([400, 401, 403, 404, 404]) if s < 0.92 \
            else rnd.choice([500, 502, 503])
        reqs.append((path, status, rnd.uniform(lo, hi)))
    # health checks: slow "deep" checks, always 200 — counting them changes requests, p95 and slowest endpoint
    for _ in range(max(4, n // 9)):
        reqs.insert(rnd.randrange(len(reqs)), (rnd.choice(["/health", "/healthz", "/health/ready"]), 200, rnd.uniform(1400, 2600)))
    # one very slow search with a unique query string: only the slowest endpoint if query strings are NOT stripped
    reqs.insert(rnd.randrange(len(reqs)), (f"/api/search?q={search_spike}", 200, slow_range[1] * 1.6))
    return reqs


def verify_traps(name, reqs, unit_trap=None):
    good = stats(reqs)
    assert not good["_tie"], name
    diffs = {
        "health": stats(reqs, include_health=True),
        "4xx": stats(reqs, errors_4xx=True),
        "query": stats(reqs, keep_query=True),
        "p95": stats(reqs, interp_p95=True),
    }
    report = {}
    for k, v in diffs.items():
        changed = [f for f in ("requests", "errors", "error_rate", "p95_ms", "slowest_endpoint") if v[f] != good[f]]
        assert changed, f"{name}: convention '{k}' does not change any output"
        report[k] = changed
    if unit_trap:
        report["unit"] = unit_trap
    return good, report


# --------------------------------------------------------------------------- formats
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def times(seed, n, day):
    rnd = random.Random(seed * 7)
    t = datetime(2026, 10, day, 8, 0, 0, tzinfo=timezone.utc)
    out = []
    for _ in range(n):
        t += timedelta(seconds=rnd.randint(1, 40))
        out.append(t)
    return out


def method_for(path, status):
    return "POST" if path.startswith(("/login", "/api/orders")) and status in (201, 400, 401) else "GET"


def snap_ms(ms, decimals):
    """Value as written in the log, avoiding exact .5 ms rounding ties."""
    v = round(ms, decimals)
    if decimals and abs((v * 1) - math.floor(v) - 0.5) < 1e-9:
        v += 0.1
    return v


def fmt_nginx(reqs, seed):  # task 1: response time in seconds (3 decimals) → exact ms
    ts = times(seed, len(reqs), 1)
    rnd = random.Random(seed)
    lines, parsed = [], []
    for (path, status, ms), t in zip(reqs, ts):
        sec = round(ms / 1000, 3)
        parsed.append((path, status, sec * 1000))
        ip = f"10.0.{rnd.randint(0, 3)}.{rnd.randint(2, 250)}"
        lines.append(f'{ip} - - [{t.day:02d}/{MONTHS[t.month - 1]}/{t.year}:{t:%H:%M:%S} +0000] '
                     f'"{method_for(path, status)} {path} HTTP/1.1" {status} {rnd.randint(120, 9000)} rt={sec:.3f}')
    return "\n".join(lines) + "\n", parsed


def fmt_jsonl(reqs, seed):  # task 2: float ms + 2 malformed lines
    ts = times(seed, len(reqs), 2)
    lines, parsed = [], []
    for (path, status, ms), t in zip(reqs, ts):
        v = snap_ms(ms, 1)
        parsed.append((path, status, v))
        lines.append(json.dumps({"time": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "req": {"method": method_for(path, status), "url": path},
                                 "res": {"status": status}, "duration_ms": v}))
    lines.insert(len(lines) // 3, '{"time": "2026-10-02T09:13:07Z", "req": {"method": "GET", "url": "/api/users"')
    lines.insert(2 * len(lines) // 3, '{"time": "2026-10-02T09:41:55Z", "req": {"meth')
    return "\n".join(lines) + "\n", parsed


def fmt_csv(reqs, seed):  # task 3: latency with unit suffix, mixed ms / s
    ts = times(seed, len(reqs), 3)
    rnd = random.Random(seed)
    lines, parsed = ["timestamp,client,method,endpoint,status,latency"], []
    for (path, status, ms), t in zip(reqs, ts):
        if rnd.random() < 0.4:
            sec = round(ms / 1000, 3)
            lat, val = f"{sec:g}s", sec * 1000
        else:
            val = int(round(ms))
            lat = f"{val}ms"
        parsed.append((path, status, val))
        ep = f'"{path}"' if "," in path else path
        lines.append(f"{t:%Y-%m-%dT%H:%M:%SZ},c{rnd.randint(100, 999)},{method_for(path, status)},{ep},{status},{lat}")
    return "\n".join(lines) + "\n", parsed


def fmt_logfmt(reqs, seed):  # task 4: logfmt, took=<n>ms or <x>s, plus non-request lines and garbage
    ts = times(seed, len(reqs), 4)
    rnd = random.Random(seed)
    lines, parsed = [], []
    for (path, status, ms), t in zip(reqs, ts):
        if rnd.random() < 0.3:
            sec = round(ms / 1000, 3)
            took, val = f"{sec:g}s", sec * 1000
        else:
            val = int(round(ms))
            took = f"{val}ms"
        parsed.append((path, status, val))
        lvl = "error" if status >= 500 else "warn" if status >= 400 else "info"
        lines.append(f"ts={t:%Y-%m-%dT%H:%M:%SZ} level={lvl} method={method_for(path, status)} path={path} status={status} took={took}")
    extra = ['ts=2026-10-04T08:00:00Z level=info msg="server started" port=8080',
             'ts=2026-10-04T08:20:13Z level=info msg="cache warmed" entries=5120',
             'ts=2026-10-04T08:47:02Z level=warn msg="slow disk" device=sda1',
             "#### log rotated ####"]
    for i, e in enumerate(extra):
        lines.insert(min(len(lines), i * len(lines) // len(extra)), e)
    return "\n".join(lines) + "\n", parsed


def fmt_apache_us(reqs, seed):  # task 5: Apache common log + %D (microseconds)
    ts = times(seed, len(reqs), 5)
    rnd = random.Random(seed)
    lines, parsed = [], []
    for (path, status, ms), t in zip(reqs, ts):
        us = int(ms * 1000)
        if us % 1000 == 500:
            us += 7
        parsed.append((path, status, us / 1000))
        user = rnd.choice(["-", "-", "bob", "carol"])
        lines.append(f'192.168.{rnd.randint(0, 9)}.{rnd.randint(2, 250)} - {user} [{t.day:02d}/{MONTHS[t.month - 1]}/{t.year}:{t:%H:%M:%S} +0000] '
                     f'"{method_for(path, status)} {path} HTTP/1.1" {status} {rnd.randint(100, 9000)} {us}')
    return "\n".join(lines) + "\n", parsed


def fmt_pipe_rotated(reqs, seed):  # task 6: two rotated files, pipe-separated, seconds, a malformed line
    ts = times(seed, len(reqs), 6)
    lines, parsed = [], []
    for (path, status, ms), t in zip(reqs, ts):
        sec = round(ms / 1000, 3)
        parsed.append((path, status, sec * 1000))
        lines.append(f"{t:%Y-%m-%dT%H:%M:%SZ}|{method_for(path, status)}|{path}|{status}|{sec:.3f}")
    half = len(lines) // 2
    old = ["time|method|path|status|seconds"] + lines[:half]
    new = ["time|method|path|status|seconds"] + lines[half:]
    old.insert(len(old) // 2, "2026-10-06T09:14:00Z|GET|/api/users|200")  # missing a field → malformed
    new.insert(len(new) // 3, "2026-10-06T11:02:41Z|GET||not-a-status|0.1")
    return ("\n".join(old) + "\n", "\n".join(new) + "\n"), parsed


TASKS = [
    dict(n=1, seed=101, count=46, slow_ep="/api/reports/export", slow_range=(600, 1100), spike="all+products",
         fmt=fmt_nginx, files=["logs/access-01.log"], unit="seconds (rt=)",
         describe="""
            Each line of `logs/access-01.log` is an nginx access-log entry:
            `<client ip> - - [<timestamp>] "<METHOD> <path> <protocol>" <status> <response bytes> rt=<response time in seconds>`.
         """),
    dict(n=2, seed=202, count=52, slow_ep="/api/invoices/pdf", slow_range=(500, 950), spike="winter+sale",
         fmt=fmt_jsonl, files=["logs/events-02.jsonl"], unit="float ms",
         describe="""
            `logs/events-02.jsonl` has one JSON object per line:
            `{"time": ..., "req": {"method": ..., "url": <path incl. query string>}, "res": {"status": ...}, "duration_ms": <latency in ms, may have decimals>}`.
         """),
    dict(n=3, seed=303, count=50, slow_ep="/api/recommendations", slow_range=(450, 900), spike="gift+ideas",
         fmt=fmt_csv, files=["logs/requests-03.csv"], unit="mixed ms/s suffix",
         describe="""
            `logs/requests-03.csv` is a CSV file with the header `timestamp,client,method,endpoint,status,latency`;
            `endpoint` is the requested path (incl. query string) and `latency` carries a unit suffix, e.g. `87ms` or `1.25s`.
         """),
    dict(n=4, seed=404, count=48, slow_ep="/api/exports/csv", slow_range=(700, 1300), spike="black+friday",
         fmt=fmt_logfmt, files=["logs/app-04.log"], unit="took= ms/s",
         describe="""
            `logs/app-04.log` is an application log in logfmt (`key=value` pairs separated by spaces). Request lines look like
            `ts=<timestamp> level=<level> method=<METHOD> path=<path incl. query string> status=<status> took=<latency with unit, e.g. 45ms or 1.2s>`;
            the file also contains other log lines that are not requests.
         """),
    dict(n=5, seed=505, count=50, slow_ep="/api/analytics/daily", slow_range=(550, 1000), spike="new+arrivals",
         fmt=fmt_apache_us, files=["logs/apache-05.log"], unit="microseconds",
         describe="""
            `logs/apache-05.log` uses the Apache common log format followed by `%D`:
            `<client ip> - <user> [<timestamp>] "<METHOD> <path> <protocol>" <status> <bytes> <response time in MICROseconds>`.
         """),
    dict(n=6, seed=606, count=54, slow_ep="/api/batch/import", slow_range=(800, 1400), spike="clearance",
         fmt=fmt_pipe_rotated, files=["logs/web-06.log.1", "logs/web-06.log"], unit="seconds, two files",
         describe="""
            The log for this period was rotated into two files, `logs/web-06.log.1` (older part) and `logs/web-06.log`
            (newer part); both belong to the same report. Each file starts with the header line
            `time|method|path|status|seconds` followed by pipe-separated rows (`path` includes the query string,
            `seconds` is the latency in seconds).
         """),
]

write_suite(SUITE, {
    "description": lit("""
        Memory-evolution suite: six tasks of the same kind — compute request statistics from a web/application log and
        write them in an exact five-line format. Each task uses a differently formatted log (nginx with seconds, JSON
        lines with float ms and broken lines, CSV with unit suffixes, logfmt mixed with non-request lines, Apache with
        microseconds, two rotated pipe-separated files). The numbers depend on seven team conventions (exclude health
        checks, only 5xx are errors, strip query strings, convert to whole ms, nearest-rank p95, skip unparseable lines,
        tie-break) that are revealed ONLY when the agent asks in task 1. From task 2 on, the simulated user refuses to
        repeat them, so later tasks can only succeed if the agent kept them (memory notes, experiences, skills) and
        re-applies them. Compare per-field check pass rates across the six tasks and against a `--memory off` run to see
        the effect of memory. Run the tasks in order in one suite run (memory: carry).
    """).strip(),
    "defaults": {
        "timeout": 600,
        "max_iterations": 30,
        "memory": "carry",
        "hitl": {"approvals": "approve", "default_reply": REFUSE},
    },
}, header="PlanD eval suite `memory_evolution` — experience reuse across six tasks of the same kind (format: pland/eval/SCHEMA.md)")

summary = []
for t in TASKS:
    reqs = gen_requests(t["seed"], t["count"], slow_ep=t["slow_ep"], slow_range=t["slow_range"], search_spike=t["spike"])
    content, parsed = t["fmt"](reqs, t["seed"])
    expected, traps = verify_traps(f"task {t['n']}", parsed, t["unit"])
    # the unit trap: treating the raw unit as ms must change the numbers (except for float-ms JSON where rounding matters)
    if t["n"] != 2:
        raw_units = {1: 1 / 1000, 3: None, 4: None, 5: 1000, 6: 1 / 1000}[t["n"]]
        if raw_units:
            wrong = stats([(p, s, ms * raw_units) for p, s, ms in parsed])
            assert wrong["p95_ms"] != expected["p95_ms"], f"task {t['n']}: unit trap ineffective"
    files = {t["files"][0]: content} if isinstance(content, str) else dict(zip(t["files"], content))
    nn = f"{t['n']:02d}"
    out = f"stats/report-{nn}.txt"
    first = t["n"] == 1
    srcs = " and ".join(f"`{f}`" for f in t["files"])
    prompt = (f"Compute our standard request statistics for {srcs} and write them to `{out}`.\n\n"
              + lit(t["describe"]) + "\n"
              + "Apply our team's conventions for request-log statistics (if you don't know them, ask me).\n\n"
              + OUTPUT_SPEC + "\n")
    E = {k: v for k, v in expected.items() if not k.startswith("_")}
    field_code = r"""
        import re
        lines = [l.strip() for l in path(__OUT__).read_text(encoding="utf-8").splitlines() if l.strip()]
        vals = dict(l.split(":", 1) for l in lines if ":" in l)
        vals = {k.strip(): v.strip() for k, v in vals.items()}
        key, want = __KEY__, __WANT__
        assert key in vals, f"no '{key}:' line in __OUT_PLAIN__"
        got = vals[key]
    """
    checks = [
        {"id": "format", "type": "python", "code": code(r"""
            import re
            lines = [l.rstrip() for l in path(__OUT__).read_text(encoding="utf-8").strip().splitlines()]
            pats = [r"requests: \d+", r"errors: \d+", r"error_rate: \d+\.\d{2}%", r"p95_ms: \d+", r"slowest_endpoint: /\S*"]
            assert len(lines) == 5, f"expected exactly 5 lines, got {len(lines)}: {lines}"
            for line, pat in zip(lines, pats):
                assert re.fullmatch(pat, line), f"line {line!r} does not match the required format {pat!r}"
        """, OUT=out)},
    ]
    for key in ("requests", "errors", "error_rate", "p95_ms", "slowest_endpoint"):
        want = E[key]
        if key == "error_rate":
            cmp = r"""
                got_num = float(got.rstrip("%").strip())
                assert abs(got_num - float(want)) < 0.006, f"error_rate: got {got}, expected {want}%"
            """
        elif key == "slowest_endpoint":
            cmp = r"""
                assert got == want, f"slowest_endpoint: got {got!r}, expected {want!r}"
            """
        else:
            cmp = r"""
                assert re.fullmatch(r"\d+", got) and int(got) == want, f"{key}: got {got!r}, expected {want}"
            """
        checks.append({"id": key.replace("_", "-"), "type": "python",
                       "code": code(lit(field_code) + lit(cmp), OUT=out, KEY=key, WANT=want, OUT_PLAIN=out)
                       .replace(repr(out) + "\"", out + "\"")})
    if first:
        checks.append({"id": "asked-conventions", "type": "hitl", "kind": "clarify", "min": 1})
    if t["n"] == 6:
        checks.append({"id": "experiences-recorded", "type": "experience_count", "min": 5})
    task = {
        "id": f"memevo-{nn}",
        "title": f"Log statistics #{t['n']} ({t['unit']})",
        "category": "memory",
        "prompt": prompt,
        "setup": {"files": files},
        "hitl": {"replies": [{"match": ".*", "reply": CONVENTIONS if first else REFUSE}],
                 "default_reply": CONVENTIONS if first else REFUSE},
        "memory": "carry",
        "checks": checks,
        "required": ["format", "requests", "errors", "error-rate", "p95-ms", "slowest-endpoint"],
    }
    header = (f"memory_evolution {nn} — log format: {t['unit']}. "
              + ("The conventions are revealed only through the clarification answer in THIS task."
                 if first else "The simulated user refuses to repeat the conventions; only memory from earlier tasks helps.")
              + f"\nexpected: {E}\ntraps (field changed if the convention is ignored): {traps}")
    write_task(SUITE, f"{nn}-log-stats.yaml", task, header=header)
    summary.append((nn, E, traps))
for s in summary:
    print(s)
