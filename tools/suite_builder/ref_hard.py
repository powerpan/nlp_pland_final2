"""Reference solutions for the hard suite (scripted, no model), plus deliberately wrong variants and alternative
correct paths. Run through validate.py, which applies them in scratch workspaces outside the repository."""

import json
import re
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import date

import hard_data as D
import hard_refs as R
from ref_dev import deleg, hitl


def run_py(c, args, cwd="."):
    r = subprocess.run([sys.executable, *args], cwd=str(c.path(cwd)), capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def mutate(src, *pairs):
    for old, new in pairs:
        assert src.count(old) >= 1, old
        src = src.replace(old, new)
    return src


# ----------------------------------------------------------------------------- 01 TTL / LRU cache
_EAGER = '''

class _Eager(list):
    """Mutation: report every removal immediately, i.e. inside the lock and in the middle of the operation."""

    def __init__(self, cache):
        super().__init__()
        self.cache = cache

    def append(self, item):
        if self.cache._on_evict is not None:
            try:
                self.cache._on_evict(*item)
            except Exception:
                pass
'''
NAIVE_GET_OR_SET = '''    def get_or_set(self, key, factory, ttl=None):
        value = self.get(key, _MISSING)
        if value is _MISSING:
            value = factory()
            self.set(key, value, ttl)
        return value
'''


def cache(c, impl=None):
    c.write("ttlcache/__init__.py", impl or R.TTLCACHE)
    c.write("tests/test_ttlcache.py", R.TTLCACHE_TESTS)
    if impl:
        return {}

    def variant(src, fails):
        return lambda c2: (cache(c2, impl=src), {"expect_fail": fails})[1]

    gos_start = R.TTLCACHE.index("    def get_or_set(")
    naive = R.TTLCACHE[:gos_start] + NAIVE_GET_OR_SET
    return {"negatives": {
        "expiry-boundary-gt": variant(mutate(R.TTLCACHE, ("now >= entry[1]", "now > entry[1]")), ["hidden-expiry"]),
        "peek-touches-lru": variant(mutate(R.TTLCACHE, (
            "            value = default if entry is None else entry[0]\n",
            "            value = default if entry is None else entry[0]\n"
            "            if entry is not None:\n                self._data.move_to_end(key)\n")), ["hidden-basics"]),
        "no-purge-before-insert": variant(mutate(R.TTLCACHE, (
            "            now = self._clock()\n            self._purge(now, removed)\n            if key in self._data:",
            "            now = self._clock()\n            if key in self._data:")), ["hidden-expiry"]),
        "callbacks-inside-rlock": variant(mutate(R.TTLCACHE + _EAGER,
                                                 ("threading.Lock()", "threading.RLock()"),
                                                 ("removed = []", "removed = _Eager(self)"),
                                                 ("        if self._on_evict is None:\n            return\n",
                                                  "        if self._on_evict is None or isinstance(removed, _Eager):\n            return\n")),
                                          ["hidden-callbacks"]),
        "naive-get-or-set": variant(naive, ["hidden-get-or-set"]),
        "no-lock": variant(mutate(R.TTLCACHE, ("self._lock = threading.Lock()", "self._lock = _NoLock()"),
                                  ('_MISSING = object()\n', '_MISSING = object()\n\n\nclass _NoLock:\n'
                                   '    def __enter__(self):\n        return self\n\n'
                                   '    def __exit__(self, *exc):\n        return False\n')), ["hidden-thread-safety"]),
    }}


# ----------------------------------------------------------------------------- 02 splitbill
def fix_split(c, skip=()):
    for i, (rel, good, bad) in enumerate(D.SPLIT_BUGS):
        if i in skip:
            continue
        p = c.path(rel)
        t = p.read_text()
        assert t.count(bad) == 1, (rel, bad)
        p.write_text(t.replace(bad, good))


def splitbill(c):
    fix_split(c)

    def visible_only(c2):  # everything the visible tests show, but not the fx rounding bug
        fix_split(c2, skip={8})
        return {"expect_fail": ["hidden-spec", "hidden-cli"]}

    def settle_left_inverted(c2):  # fixed the ledger sign only -> the compensating settle bug now shows
        fix_split(c2, skip={4, 5})
        return {"expect_fail": ["tests-pass", "hidden-spec", "hidden-cli"]}

    def edited_tests(c2):
        fix_split(c2, skip={1})
        p = c2.path("tests/test_money.py")
        p.write_text(p.read_text().replace("[334, 333, 333]", "[333, 333, 334]"))
        p = c2.path("tests/test_split.py")
        p.write_text(p.read_text().replace('{"ann": 334, "bob": 333, "cy": 333}', '{"ann": 333, "bob": 333, "cy": 334}'))
        return {"expect_fail": ["tests-unchanged", "hidden-spec"]}

    def untouched(c2):
        return {"expect_fail": ["tests-pass", "hidden-spec", "hidden-cli"]}
    return {"negatives": {"visible-bugs-only": visible_only, "settle-sign-left": settle_left_inverted,
                          "edited-tests": edited_tests, "nothing-fixed": untouched}}


# ----------------------------------------------------------------------------- 03 data cleaning
def shipments(c, src=None):
    c.write("clean.py", src or R.CLEAN)
    run_py(c, ["clean.py"])
    if src:
        return {}

    def variant(s, fails):
        return lambda c2: (shipments(c2, s), {"expect_fail": fails})[1]

    def hard_coded(c2):
        for name, text in D.SHIP_MAIN.items():
            c2.write(f"out/{name}", text)
        c2.write("clean.py", "print('outputs are already in out/')\n")
        return {"expect_fail": ["rerun-unseen-data"]}
    return {"negatives": {
        "float-rounding": variant(mutate(R.CLEAN, ('return value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)',
                                                   'return Decimal(f"{round(float(value), 3):.3f}")')),
                                  ["shipments-exact", "summary-exact", "rerun-unseen-data"]),
        "latin1-not-cp1252": variant(mutate(R.CLEAN, ('"cp1252"', '"latin-1"')), ["shipments-exact", "rerun-unseen-data"]),
        "web-local-date": variant(mutate(R.CLEAN, ("return ts.astimezone(timezone.utc).date().isoformat()",
                                                   "return ts.date().isoformat()")),
                                  ["shipments-exact", "rerun-unseen-data"]),
        "keeps-first-duplicate": variant(mutate(R.CLEAN, ('                dups += 1\n                del kept[row["shipment_id"]]\n',
                                                          '                dups += 1\n                continue\n')),
                                         ["shipments-exact", "rerun-unseen-data"]),
        "no-nfc": variant(mutate(R.CLEAN, ('unicodedata.normalize("NFC", str(v))', 'str(v)')),
                          ["shipments-exact", "rerun-unseen-data"]),
        "hard-coded-outputs": hard_coded,
    }}


# ----------------------------------------------------------------------------- 04 research
def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "pland-ref"})
    return json.load(urllib.request.urlopen(req, timeout=40))


def _vt(v):
    return tuple(int(x) for x in re.findall(r"\d+", v))


def django_matrix(c, mode="ok"):
    from packaging.specifiers import SpecifierSet

    today = date.today()
    dj = [x for x in _get("https://endoflife.date/api/django.json")
          if mode == "with-eol" or date.fromisoformat(x["eol"]) > today]
    py = [x for x in _get("https://endoflife.date/api/python.json") if date.fromisoformat(x["eol"]) > today]
    dj.sort(key=lambda x: _vt(x["cycle"]), reverse=True)
    if mode == "with-eol":
        dj = dj[:5]
    project_rp = _get("https://pypi.org/pypi/Django/json")["info"]["requires_python"]
    rows, rp_of = [], {}
    for x in dj:
        rp = project_rp if mode == "project-rp" else _get(f"https://pypi.org/pypi/Django/{x['latest']}/json")["info"]["requires_python"]
        if mode == "eol-field":
            lo, hi = re.findall(r"\d+\.\d+", x["supportedPythonVersions"])[:2]
            pys = [p["cycle"] for p in py if _vt(lo) <= _vt(p["cycle"]) <= _vt(hi)]
        else:
            pys = [p["cycle"] for p in py if SpecifierSet(rp).contains(p["cycle"])]
        pys.sort(key=_vt)
        rp_of[x["cycle"]] = pys
        days = (date.fromisoformat(x["eol"]) - today).days
        rows.append(f"| {x['cycle']} | {'yes' if x.get('lts') else 'no'} | {x['latest']} | {rp} | {', '.join(pys)} | {x['eol']} | {days} |")
    best = max((x for x in dj if x.get("lts") and date.fromisoformat(x["eol"]) > today), key=lambda x: _vt(x["cycle"]))
    c.write("django_matrix.md", "# Django / Python matrix\n\n| Django | LTS | Latest | Requires-Python | Python cycles | EOL | Days left |\n"
            "|---|---|---|---|---|---|---|\n" + "\n".join(rows) + f"\n\nRecommended: Django {best['cycle']} on Python "
            f"{max(rp_of[best['cycle']], key=_vt)}\n")
    if mode != "ok":
        return {}
    return {"negatives": {
        "project-requires-python": lambda c2: (django_matrix(c2, "project-rp"), {"expect_fail": ["requires-python"]})[1],
        "endoflife-python-field": lambda c2: (django_matrix(c2, "eol-field"), {"expect_fail": ["requires-python", "recommended"]})[1],
        "lists-eol-cycles": lambda c2: (django_matrix(c2, "with-eol"), {"expect_fail": ["django-rows"]})[1],
    }}


# ----------------------------------------------------------------------------- 05 team semver
FINDINGS = """# Review findings — semver

## Round 1
- [major] `satisfies` ignored the prerelease rule: `3.4.5-alpha.9` satisfied `>1.2.3-alpha.3`.
- [major] numeric prerelease identifiers were compared as strings (`beta.11` < `beta.2`).
- [minor] `parse("1.2.3-01")` was accepted.
Verdict: CHANGES REQUESTED

## Round 2
- No issues found (all round-1 findings verified fixed with extra edge cases).

Verdict: APPROVED
"""


def semver(c, src=None, findings=FINDINGS, events=None):
    c.write("shared/semver/semver.py", src or R.SEMVER)
    c.write("shared/semver/tests/test_semver.py", R.SEMVER_TESTS)
    if findings is not None:
        c.write("shared/review/findings.md", findings)
    ev = events if events is not None else [deleg("implementer"), deleg("reviewer"), deleg("implementer"), deleg("reviewer")]
    if src or findings is not FINDINGS or events is not None:
        return {"events": ev}

    def variant(fails, **kw):
        return lambda c2: dict(semver(c2, **kw), expect_fail=fails)
    no_pre_rule = mutate(R.SEMVER, ("if v.prerelease and not any(", "if False and not any("))
    str_ids = mutate(R.SEMVER, ("pre.append(int(ident))", "pre.append(ident)"))
    return {"events": ev, "negatives": {
        "no-prerelease-rule": variant(["hidden-satisfies", "hidden-max-satisfying"], src=no_pre_rule),
        "string-identifiers": variant(["hidden-parse", "hidden-compare"], src=str_ids),
        "no-review": variant(["review-findings", "delegated-reviewer"], findings=None, events=[deleg("implementer")]),
        "not-approved": variant(["review-findings"], findings=FINDINGS.rsplit("Verdict: APPROVED", 1)[0] + "Verdict: CHANGES REQUESTED\n"),
    }}


# ----------------------------------------------------------------------------- 06 HITL payout
def payout(c, text=None, push=True, clarify=("plan", "format")):
    c.write("payouts/2026-Q3.csv", text or D.PAYOUT_EXPECTED)
    c.sh("git add -A && git commit -qm 'Q3 2026 commission payout'", "payouts")
    log = [hitl("clarify", {"plan": "What is the 2026 commission plan?", "format": "What file format does the payroll importer expect?"}[q],
                {"plan": D.PAYOUT_PLAN_REPLY, "format": D.PAYOUT_FORMAT_REPLY}[q]) for q in clarify]
    if push:
        c.sh("git push -q origin main", "payouts")
        log.append(hitl("approval", "git push origin main", choice="once"))
    if text or not push or clarify != ("plan", "format"):
        return {"hitl": log}
    guessed = "employee_id,name,commission_eur\n" + "".join(f"{r},{n},{a:.2f}\n" for r, n, a in D.PAYOUT_ROWS)
    return {"hitl": log, "negatives": {
        "used-2025-plan": lambda c2: dict(payout(c2, D.PAYOUT_2025, clarify=("format",)),
                                          expect_fail=["asked-two-questions", "payout-amounts"]),
        "guessed-format": lambda c2: dict(payout(c2, guessed, clarify=("plan",)),
                                          expect_fail=["asked-two-questions", "payout-format"]),
        "not-pushed": lambda c2: dict(payout(c2, push=False), expect_fail=["pushed", "push-approved"]),
    }}


# ----------------------------------------------------------------------------- 07 cross-agent pricing
def persist_events(c, events):
    """Write run events into the shared.db event log next to rooms/, as the runtime's EventBus does."""
    from pland.store import SHARED_SCHEMA

    root = c.path("shared").resolve().parents[2]
    con = sqlite3.connect(str(root / "shared.db"))
    con.executescript(SHARED_SCHEMA)
    for e in events:
        fields = {k: v for k, v in e.items() if k != "type"}
        con.execute("INSERT INTO events(ts, type, profile, session_id, room_id, run_id, data) VALUES (?,?,?,?,?,?,?)",
                    (time.time(), e["type"], fields.get("profile"), fields.get("session_id"), fields.get("room_id"),
                     fields.get("run_id"), json.dumps(fields)))
    con.commit()
    con.close()


def pricing(c, quotes=None, events=None):
    c.write("shared/quotes.csv", D.quotes_csv(quotes or D.QUOTES))
    c.write("shared/quotes.md", "# Q4 2026 quotes\n\n" + "".join(f"- {q['order_id']} ({q['customer']}): EUR {q['total']}\n"
                                                                     for q in quotes or D.QUOTES))
    room = c.room_id
    ev = events if events is not None else [
        {"type": "room.member_turn", "room_id": room, "member": "catalog", "role": "member", "state": "done"},
        {"type": "delegation.finished", "room_id": room, "profile": "billing", "to": "catalog", "status": "completed"},
    ]
    persist_events(c, ev)
    if quotes is not None or events is not None:
        return {"events": [e for e in ev if e["type"] == "delegation.finished"]}
    return {"events": ev[1:], "negatives": {
        "no-communication": lambda c2: dict(pricing(c2, events=[
            {"type": "room.member_turn", "room_id": room, "member": "catalog", "role": "member", "state": "done"},
            {"type": "delegation.finished", "room_id": "other_room", "to": "catalog", "status": "completed"},
            {"type": "delegation.finished", "room_id": room, "to": "catalog", "status": "error"}]),
            expect_fail=["owner-consulted"]),
        "stale-q3-prices": lambda c2: dict(pricing(c2, quotes=D.QUOTES_STALE), expect_fail=["quotes-exact"]),
        "rules-ignored": lambda c2: dict(pricing(c2, quotes=D.QUOTES_NO_RULES), expect_fail=["quotes-exact"]),
    }, "alternatives": {
        "via-message-agent": lambda c2: pricing(c2, events=[
            {"type": "message.replied", "room_id": room, "profile": "billing", "to": "catalog", "status": "completed"}]),
        "via-room-mention": lambda c2: pricing(c2, events=[
            {"type": "room.member_turn", "room_id": room, "member": "catalog", "role": "mentioned", "state": "done"}]),
    }}


# ----------------------------------------------------------------------------- 08 git merge
CONFLICTED = {"CHANGELOG.md", "config.json", "shop/pricing.py", "tests/test_pricing.py"}


def merge(c, files=None, *, squash=False, followup=False, commit=True):
    r = c.sh("git merge " + ("--squash" if squash else "--no-ff") + " feature/tiered-discounts", "store", check=False)
    assert r.returncode != 0, "the merge was expected to conflict"
    conflicted = set(c.sh("git diff --name-only --diff-filter=U", "store").stdout.split())
    assert conflicted == CONFLICTED, conflicted
    resolved = {**D.GIT_RESOLVED, **(files or {})}
    late = {}
    if followup:
        late["shop/cart.py"] = resolved.pop("shop/cart.py")
        resolved["shop/cart.py"] = D.GIT_FEATURE_TIP["shop/cart.py"].replace(
            "from .pricing import calc_total", "from .pricing import compute_total as calc_total")
    if not commit:
        c.sh("git add -A && git commit -qm 'Merge branch feature/tiered-discounts' ", "store")
        for rel, text in resolved.items():
            c.write(f"store/{rel}", text)
        return {}
    for rel, text in resolved.items():
        c.write(f"store/{rel}", text)
    c.sh("git add -A && git commit -q " + ("-m 'Merge feature/tiered-discounts (squashed)'" if squash else "--no-edit"), "store")
    for rel, text in late.items():
        c.write(f"store/{rel}", text)
        c.sh("git commit -qam 'fix: Cart uses compute_total'", "store")
    if files or squash or followup:
        return {}
    alias = D.GIT_RESOLVED["shop/pricing.py"] + "\n\ncalc_total = compute_total  # backwards compatibility\n"
    log = D.GIT_RESOLVED["CHANGELOG.md"]
    feature_first = log.replace(
        "- Renamed `calc_total` to `compute_total`.\n- New keyword-only `currency` argument (EUR, USD, GBP).\n- VAT for Austria (AT).\n"
        "- Customer tiers (silver, gold, platinum) with a discount before VAT.\n- `Cart` helper (`shop.cart`).\n",
        "- Customer tiers (silver, gold, platinum) with a discount before VAT.\n- `Cart` helper (`shop.cart`).\n"
        "- Renamed `calc_total` to `compute_total`.\n- New keyword-only `currency` argument (EUR, USD, GBP).\n- VAT for Austria (AT).\n")
    assert feature_first != log
    cfg = json.loads(D.GIT_RESOLVED["config.json"])
    cfg["version"] = "1.2.1"
    tier_ignored = D.GIT_RESOLVED["shop/pricing.py"].replace("    if tier is not None:\n        net = net * (1 - TIERS[tier])\n", "")
    tier_positional = D.GIT_RESOLVED["shop/pricing.py"].replace('country="DE", *, tier=None, currency="EUR"',
                                                                'country="DE", tier=None, *, currency="EUR"')
    assert tier_ignored != D.GIT_RESOLVED["shop/pricing.py"] != tier_positional
    return {"negatives": {
        "squash-merge": lambda c2: dict(merge(c2, squash=True), expect_fail=["merge-commit", "pricing-resolved", "tests-pass", "changelog", "config"]),
        "fix-in-followup-commit": lambda c2: dict(merge(c2, followup=True), expect_fail=["merge-commit"]),
        "alias-kept": lambda c2: dict(merge(c2, {"shop/pricing.py": alias, "shop/cart.py": D.GIT_FEATURE_TIP["shop/cart.py"]}),
                                      expect_fail=["pricing-resolved"]),
        "tier-dropped": lambda c2: dict(merge(c2, {"shop/pricing.py": tier_ignored}), expect_fail=["pricing-resolved", "tests-pass"]),
        "tier-positional": lambda c2: dict(merge(c2, {"shop/pricing.py": tier_positional}), expect_fail=["pricing-resolved"]),
        "feature-entries-first": lambda c2: dict(merge(c2, {"CHANGELOG.md": feature_first}), expect_fail=["changelog"]),
        "main-version-kept": lambda c2: dict(merge(c2, {"config.json": json.dumps(cfg, indent=2) + "\n"}), expect_fail=["config"]),
        "conflicts-committed": lambda c2: dict(merge(c2, commit=False), expect_fail=["pricing-resolved", "tests-pass", "clean-tree"]),
    }}


REFS = {
    "hard-ttl-lru-cache": cache,
    "hard-debug-splitbill": splitbill,
    "hard-data-cleaning-shipments": shipments,
    "hard-research-django-matrix": django_matrix,
    "hard-team-semver-review": semver,
    "hard-hitl-payout-run": payout,
    "hard-team-private-pricing": pricing,
    "hard-git-merge-conflict": merge,
}
