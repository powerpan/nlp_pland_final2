"""Independent reference solver for the memory_evolution suite: parses the setup log files as an agent would
(it does not reuse the generator) and applies the team conventions."""

import csv
import io
import json
import math
import re
import statistics
from decimal import ROUND_HALF_UP, Decimal

from ref_dev import hitl

REQ = re.compile(r'"(?P<m>[A-Z]+) (?P<p>\S+) HTTP/[\d.]+" (?P<s>\d{3}) \d+ (?P<rest>.*)$')


def to_ms(value: str) -> float:
    v = value.strip()
    if v.endswith("ms"):
        return float(v[:-2])
    if v.endswith("s"):
        return float(v[:-1]) * 1000
    raise ValueError(v)


def parse(task_id, ws):
    out = []  # (path, status, ms)
    if task_id == "memevo-01":
        for line in (ws / "logs/access-01.log").read_text().splitlines():
            m = REQ.search(line)
            if m:
                out.append((m["p"], int(m["s"]), float(m["rest"].split("rt=")[1]) * 1000))
    elif task_id == "memevo-02":
        for line in (ws / "logs/events-02.jsonl").read_text().splitlines():
            try:
                o = json.loads(line)
                out.append((o["req"]["url"], int(o["res"]["status"]), float(o["duration_ms"])))
            except (ValueError, KeyError, TypeError):
                continue
    elif task_id == "memevo-03":
        for r in csv.DictReader(io.StringIO((ws / "logs/requests-03.csv").read_text())):
            out.append((r["endpoint"], int(r["status"]), to_ms(r["latency"])))
    elif task_id == "memevo-04":
        for line in (ws / "logs/app-04.log").read_text().splitlines():
            kv = dict(t.split("=", 1) for t in line.split() if "=" in t)
            if {"method", "path", "status", "took"} <= kv.keys():
                out.append((kv["path"], int(kv["status"]), to_ms(kv["took"])))
    elif task_id == "memevo-05":
        for line in (ws / "logs/apache-05.log").read_text().splitlines():
            m = REQ.search(line)
            if m:
                out.append((m["p"], int(m["s"]), int(m["rest"]) / 1000))
    elif task_id == "memevo-06":
        for f in ("logs/web-06.log.1", "logs/web-06.log"):
            for line in (ws / f).read_text().splitlines()[1:]:
                parts = line.split("|")
                if len(parts) != 5 or not parts[3].isdigit() or not parts[2]:
                    continue
                out.append((parts[2], int(parts[3]), float(parts[4]) * 1000))
    return out


def compute(reqs, *, conventions=True):
    rows = []
    for p, s, ms in reqs:
        ep = p.split("?")[0] if conventions else p
        if conventions and ep.startswith("/health"):
            continue
        rows.append((ep, s, int(Decimal(str(ms)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))))
    n = len(rows)
    errors = sum(1 for _, s, _ in rows if (500 if conventions else 400) <= s <= 599)
    lat = sorted(ms for _, _, ms in rows)
    p95 = lat[math.ceil(0.95 * n) - 1] if conventions else round(statistics.quantiles(lat, n=100, method="inclusive")[94])
    by = {}
    for ep, _, ms in rows:
        by.setdefault(ep, []).append(ms)
    means = {ep: sum(v) / len(v) for ep, v in by.items()}
    slow = min(ep for ep, m in means.items() if m == max(means.values()))
    return f"requests: {n}\nerrors: {errors}\nerror_rate: {errors / n * 100:.2f}%\np95_ms: {p95}\nslowest_endpoint: {slow}\n"


def make(task_id):
    n = task_id[-2:]

    def solve(c):
        c.write(f"stats/report-{n}.txt", compute(parse(task_id, c.ws)))

        def naive(c2):
            c2.write(f"stats/report-{n}.txt", compute(parse(task_id, c2.ws), conventions=False))
            return {"expect_fail": ["requests", "errors", "p95-ms", "slowest-endpoint"]}

        def chatty(c2):  # right numbers, wrong format
            c2.write(f"stats/report-{n}.txt", "# Stats\n" + compute(parse(task_id, c2.ws)).replace(": ", " = ", 1))
            return {"expect_fail": ["format", "requests"]}
        rec = {"negatives": {"no-conventions": naive, "wrong-format": chatty}}
        if n == "01":
            rec["hitl"] = [hitl("clarify", "What are the team conventions?", "...")]
        if n == "06":  # experiences the platform's reflection step would have recorded for tasks 1-6
            from pland.memory import ExperienceStore
            store = ExperienceStore(c.env.runtime.profiles.get("default"))
            for i in range(6):
                store.add(task=f"log stats {i}", outcome="success", summary="s", lessons=["exclude /health"], tags=["logs"])
        return rec
    return solve


REFS = {f"memevo-{i:02d}": make(f"memevo-{i:02d}") for i in range(1, 7)}
