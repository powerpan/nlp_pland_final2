"""hard suite: 8 discriminating tasks (the earlier suites are solved ~95-100%)."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import hard_data as D
import hard_refs as R
from common import code, lit, norm_hash, write_suite, write_task
from snippets import GIT, HASH, LOAD, PYTEST, use

SUITE = "hard"


def chk(body, *snips, **subs):
    return code(use(*snips) + lit(body), **subs)


write_suite(SUITE, {
    "description": lit("""
        Hard suite: 8 long, discriminating tasks, each fully specified by prompt + setup + simulated-user replies and
        verified only by objective checks: a thread-safe TTL/LRU cache with eviction callbacks and per-key factories
        (hidden tests, incl. concurrency), a debugging task with six interacting bugs in a 9-module package (one bug
        only visible to a hidden spec test), a data-cleaning script with many edge cases (encodings, BOM, CRLF,
        whitespace, time zones, units, half-up rounding, duplicates) re-run on unseen data, a research task combining
        endoflife.date and per-release PyPI metadata verified live at check time, a three-bot implement/review loop on a
        strict SemVer library with hidden tests, an under-specified payout run that needs two separate clarifications
        and an approved push, a cross-agent task where the needed price list lives only in another bot's private
        workspace, and a git merge with textual and semantic conflicts resolved by stated rules.
    """).strip(),
    "defaults": {
        "timeout": 1500,
        "max_iterations": 60,
        "memory": "carry",
        "hitl": {"approvals": "approve", "default_reply": "Use your best judgement and state any assumption you make."},
    },
}, header="PlanD eval suite `hard` (format: pland/eval/SCHEMA.md)")

# =========================================================================== 01 TTL / LRU cache
CACHE_PROMPT = lit("""
    Build a thread-safe in-memory cache as the Python package `ttlcache/` in the workspace root (standard library
    only), plus pytest tests in `tests/` (at least 12 test cases, passing with `python -m pytest tests`).

    API: `from ttlcache import TTLCache`

    `TTLCache(maxsize, *, default_ttl=None, sizeof=None, on_evict=None, clock=time.monotonic)`
    - `maxsize`: the capacity, a positive `int` (`bool` is not accepted). The sizes of the stored entries sum to at
      most `maxsize`.
    - `sizeof`: optional function `value -> size`; an entry's size is `sizeof(value)`, or 1 when `sizeof` is None.
      A size must be a positive `int` (not `bool`).
    - `default_ttl`: `None` (no expiry) or a positive number of seconds (`int`/`float`, not `bool`, not NaN).
    - `on_evict`: optional callback `on_evict(key, value, reason)` with `reason` one of `"expired"`, `"capacity"`,
      `"replaced"`.
    - `clock`: function returning the current time in seconds (tests pass a fake clock).
    - Invalid constructor arguments raise `ValueError`.

    Expiry: an entry stored at time `t` with a TTL of `T` seconds is expired as soon as `clock() >= t + T`. An expired
    entry is never returned or counted; whenever the cache removes one it reports it with reason `"expired"`.

    Recency: entries are kept in least-recently-used (LRU) order. Only `set`, `get` (on a hit) and `get_or_set` (on a
    hit or when it stores) make an entry the most recently used; `peek`, `in`, `keys` and `pop` never change the order.

    Methods:
    - `set(key, value, ttl=None)` — `ttl=None` means `default_ttl`; otherwise `ttl` must be a positive number. Steps:
      1. If `ttl` is invalid, or the value's size is invalid or larger than `maxsize`: raise `ValueError` — the cache
         is not changed at all (nothing removed, no callback).
      2. Remove every expired entry (reason `"expired"`).
      3. If `key` is still present, report its old value with reason `"replaced"`. Store the new value, size and
         expiry (computed from `clock()` now); the entry becomes the most recently used.
      4. While the total size exceeds `maxsize`, evict the least recently used *other* entry (reason `"capacity"`).
    - `get(key, default=None)` — the value of a live entry (which becomes the most recently used), else `default`.
    - `peek(key, default=None)` — like `get`, without changing the order.
    - `key in cache` — whether `key` has a live entry.
    - `pop(key, default=<none given>)` — remove a live entry and return its value; this is an explicit removal, so no
      `on_evict` call. For a missing key return `default`, or raise `KeyError` when no default was given.
    - `get`, `peek`, `in` and `pop` remove the requested key if it has expired (and report it). `len(cache)`,
      `cache.keys()` (a list, least → most recently used), the property `cache.size` (total size of the live entries)
      and `cache.expire()` (returns how many entries it removed) first remove every expired entry.
    - `clear()` — remove everything, without `on_evict` calls.
    - `get_or_set(key, factory, ttl=None)` — for a live entry behaves like `get`. Otherwise calls `factory()`, stores
      the result with `set(key, result, ttl)` and returns it. While a factory runs for a key, other `get_or_set` calls
      for the same key wait and then return the value it stored (the factory runs once). A running factory must not
      block calls for other keys or any other method. If the factory raises, the exception propagates to its caller,
      nothing is stored, and one of the waiting callers then runs its own factory.

    Callbacks: `on_evict` is called after the operation has finished changing the cache and without holding any
    internal lock, so a callback may use the cache itself. Removals are reported in the order they happened
    (expired entries in LRU order). Exceptions raised by `on_evict` are ignored (the remaining callbacks still run).

    Thread safety: every method may be called concurrently from many threads.
""")
CACHE_PRELUDE = r'''
import threading
from ttlcache import TTLCache
class Clock:
    def __init__(self, t=0.0):
        self.t = t
    def __call__(self):
        return self.t
def recorder(full=False):
    log = []
    return log, (lambda k, v, r: log.append((k, v, r) if full else (k, r)))
def raises(exc, fn, what):
    try:
        fn()
    except exc:
        return
    except Exception as e:
        raise AssertionError(f"{what}: raised {type(e).__name__} instead of {exc.__name__}") from None
    raise AssertionError(f"{what}: should raise {exc.__name__}")
def within(seconds, fn, what):
    box = {}
    def run():
        try:
            box["v"] = fn()
        except BaseException as e:
            box["e"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    assert not t.is_alive(), what
    if "e" in box:
        raise box["e"]
    return box.get("v")
'''
write_task(SUITE, "01-ttl-lru-cache.yaml", {
    "id": "hard-ttl-lru-cache",
    "title": "Thread-safe LRU cache with per-key TTL, size limit, eviction callbacks and single-flight factories",
    "category": "coding",
    "prompt": CACHE_PROMPT,
    "checks": [
        {"id": "package-exists", "type": "file_exists", "path": "ttlcache/__init__.py"},
        {"id": "hidden-basics", "type": "python", "code": chk(r"""
            for bad in (0, -3, True, 2.5, "3", None):
                raises(ValueError, lambda: TTLCache(bad), f"TTLCache({bad!r})")
            for bad in (0, -1, True, "5", float("nan")):
                raises(ValueError, lambda: TTLCache(3, default_ttl=bad), f"TTLCache(3, default_ttl={bad!r})")
            c = TTLCache(3)
            for bad in (0, -1, False, "5", float("nan")):
                raises(ValueError, lambda: c.set("k", 1, ttl=bad), f"set('k', 1, ttl={bad!r})")
            assert c.keys() == [] and len(c) == 0, "a rejected set() must not store anything"
            c.set("a", 1); c.set("b", 2); c.set("c", 3)
            assert c.get("a") == 1 and c.get("zz") is None and c.get("zz", 5) == 5
            assert c.keys() == ["b", "c", "a"], f"get() must make the entry the most recently used: {c.keys()}"
            assert c.peek("b") == 2 and "c" in c and "zz" not in c and c.peek("zz", 9) == 9
            assert c.keys() == ["b", "c", "a"], f"peek / in / keys must not change the LRU order: {c.keys()}"
            c.set("d", 4)
            assert c.keys() == ["c", "a", "d"], f"set() on a full cache must evict the least recently used entry: {c.keys()}"
            c.set("c", 33)
            assert c.keys() == ["a", "d", "c"] and c.get("c") == 33, f"updating a key makes it the most recently used: {c.keys()}"
            assert c.pop("a") == 1 and c.keys() == ["d", "c"], c.keys()
            assert c.pop("a", "dflt") == "dflt" and c.pop("a", None) is None
            raises(KeyError, lambda: c.pop("a"), "pop() of a missing key without a default")
            assert len(c) == 2 and c.size == 2, (len(c), c.size)
            c.clear()
            assert len(c) == 0 and c.keys() == [] and c.size == 0
            c.set(("tuple", 1), "t")
            assert c.get(("tuple", 1)) == "t"
        """, CACHE_PRELUDE)},
        {"id": "hidden-expiry", "type": "python", "code": chk(r"""
            clk = Clock(100.0)
            ev, cb = recorder(full=True)
            c = TTLCache(10, default_ttl=10, clock=clk, on_evict=cb)
            c.set("a", 1)
            c.set("b", 2, ttl=5)
            c.set("n", 3, ttl=1000)
            clk.t = 104.999
            assert c.get("b") == 2 and "a" in c, "per-key ttl: b must still be live just before 105"
            clk.t = 105
            assert c.peek("b") is None, "an entry is expired as soon as clock() >= stored_at + ttl"
            assert ev == [("b", 2, "expired")], f"the expired entry found by peek must be reported once: {ev}"
            assert "b" not in c and ev == [("b", 2, "expired")], ev
            clk.t = 108
            c.set("a", 11)
            assert ev[-1] == ("a", 1, "replaced"), f"overwriting a live key reports the old value as replaced: {ev}"
            clk.t = 115
            assert c.get("a") == 11, "set() on an existing key must restart its TTL"
            clk.t = 118
            assert c.get("a") is None and ev[-1] == ("a", 11, "expired"), ev
            # set() removes every expired entry first, in LRU order, before any capacity eviction
            clk2 = Clock()
            ev2, cb2 = recorder()
            d = TTLCache(3, clock=clk2, on_evict=cb2)
            d.set("x", 1, ttl=5); d.set("y", 2, ttl=50); d.set("z", 3, ttl=5)
            d.get("x")
            clk2.t = 10
            d.set("w", 4)
            assert ev2 == [("z", "expired"), ("x", "expired")], f"set() must first remove every expired entry (LRU order) instead of evicting live ones: {ev2}"
            assert d.keys() == ["y", "w"], d.keys()
            # an expired key that is set again is reported as expired, not replaced
            clk2.t = 100
            ev2.clear()
            d.set("y", 5)
            assert ev2 == [("y", "expired")] and d.keys() == ["w", "y"], f"an expired key that is set again is reported as expired, not replaced: {ev2}"
            # len / keys / size / expire purge (with callbacks, LRU order)
            clk3 = Clock()
            ev3, cb3 = recorder()
            e = TTLCache(5, clock=clk3, on_evict=cb3)
            for i, ttl in enumerate([3, None, 1, 2]):
                e.set(f"k{i}", i, ttl=ttl)
            clk3.t = 2
            assert len(e) == 2 and ev3 == [("k2", "expired"), ("k3", "expired")], f"len() must purge expired entries first (LRU order): {len(e)}, {ev3}"
            clk3.t = 7
            assert e.expire() == 1 and ev3[-1] == ("k0", "expired") and e.keys() == ["k1"], (ev3, e.keys())
            assert e.expire() == 0 and e.size == 1
            # pop of an expired key
            clk4 = Clock()
            ev4, cb4 = recorder()
            f = TTLCache(5, clock=clk4, on_evict=cb4)
            f.set("p", 1, ttl=1)
            clk4.t = 1
            assert f.pop("p", "gone") == "gone" and ev4 == [("p", "expired")], ev4
            raises(KeyError, lambda: f.pop("p"), "pop() of an expired key without default")
        """, CACHE_PRELUDE)},
        {"id": "hidden-capacity", "type": "python", "code": chk(r"""
            ev, cb = recorder(full=True)
            c = TTLCache(10, sizeof=len, on_evict=cb)
            c.set("a", "xxx"); c.set("b", "xxxx"); c.set("c", "xx")
            assert c.size == 9, c.size
            c.set("d", "xxxxx")
            assert ev == [("a", "xxx", "capacity"), ("b", "xxxx", "capacity")], f"evict LRU entries until the new one fits: {ev}"
            assert c.keys() == ["c", "d"] and c.size == 7, (c.keys(), c.size)
            ev.clear()
            c.set("c", "xxxxxxxx")
            assert ev == [("c", "xx", "replaced"), ("d", "xxxxx", "capacity")], f"replace first, then evict other entries: {ev}"
            assert c.keys() == ["c"] and c.size == 8, (c.keys(), c.size)
            ev.clear()
            raises(ValueError, lambda: c.set("big", "x" * 11), "a value larger than maxsize")
            assert c.keys() == ["c"] and ev == [], "a rejected set() must not change the cache or call on_evict"
            c.set("full", "x" * 10)
            assert c.keys() == ["full"] and c.size == 10, "a value of exactly maxsize fits (evicting everything else)"
            bad = TTLCache(10, sizeof=lambda v: v)
            for v in (0, -1, True, 1.5, "3"):
                raises(ValueError, lambda: bad.set("k", v), f"sizeof() returning {v!r}")
            assert bad.keys() == []
            # step 1 happens before anything else: a rejected set() does not even purge expired entries
            clk = Clock()
            ev5, cb5 = recorder()
            g = TTLCache(4, sizeof=len, clock=clk, on_evict=cb5)
            g.set("old", "x", ttl=1)
            clk.t = 5
            raises(ValueError, lambda: g.set("huge", "xxxxx"), "oversized value")
            assert ev5 == [], f"a rejected set() must not remove/report anything: {ev5}"
            assert g.keys() == [] and ev5 == [("old", "expired")], ev5
        """, CACHE_PRELUDE)},
        {"id": "hidden-callbacks", "type": "python", "code": chk(r"""
            seen = []
            c = TTLCache(3, sizeof=len, on_evict=lambda k, v, r: seen.append((k, r, c.size, c.keys())))
            def scenario():
                c.set("a", "x"); c.set("b", "x"); c.set("c", "x")
                c.set("d", "xx")
            within(5, scenario, "deadlock: an on_evict callback that calls the cache never returned (callbacks must run outside the lock)")
            assert seen == [("a", "capacity", 3, ["c", "d"]), ("b", "capacity", 3, ["c", "d"])], f"callbacks must run after the operation has finished: {seen}"
            log = []
            def writer(k, v, r):
                log.append((k, r))
                if k == "a":
                    c2.set("from-callback", 1)
            c2 = TTLCache(2, on_evict=writer)
            within(5, lambda: (c2.set("a", 1), c2.set("b", 2), c2.set("c", 3)), "deadlock: a callback that calls set() never returned")
            assert log[:2] == [("a", "capacity"), ("b", "capacity")] and c2.keys() == ["c", "from-callback"], (log, c2.keys())
            calls = []
            def boom(k, v, r):
                calls.append(k)
                raise RuntimeError("callback failure")
            c3 = TTLCache(3, sizeof=len, on_evict=boom)
            c3.set("a", "x"); c3.set("b", "x"); c3.set("c", "x")
            c3.set("d", "xxx")
            assert calls == ["a", "b", "c"] and c3.keys() == ["d"], f"callback exceptions must be ignored and all removals reported: {calls}, {c3.keys()}"
            gate, entered = threading.Event(), threading.Event()
            def slow(k, v, r):
                entered.set()
                gate.wait(10)
            c4 = TTLCache(1, on_evict=slow)
            c4.set("a", 1)
            t = threading.Thread(target=lambda: c4.set("b", 2), daemon=True)
            t.start()
            assert entered.wait(5), "on_evict was not called"
            try:
                other = within(3, lambda: (c4.get("b"), len(c4), "b" in c4), "the cache is locked while an on_evict callback runs")
            finally:
                gate.set()
            t.join(5)
            assert other == (2, 1, True), other
        """, CACHE_PRELUDE)},
        {"id": "hidden-get-or-set", "type": "python", "code": chk(r"""
            import time
            calls = []
            def factory():
                calls.append(1)
                time.sleep(0.3)
                return "v"
            c = TTLCache(10)
            out = []
            ts = [threading.Thread(target=lambda: out.append(c.get_or_set("k", factory)), daemon=True) for _ in range(8)]
            [t.start() for t in ts]
            [t.join(10) for t in ts]
            assert out == ["v"] * 8 and len(calls) == 1, f"8 concurrent get_or_set() calls ran the factory {len(calls)} times (results {out})"
            assert c.get_or_set("k", lambda: "other") == "v" and c.keys() == ["k"]
            gate, started = threading.Event(), threading.Event()
            def slow():
                started.set()
                gate.wait(10)
                return "slow"
            t = threading.Thread(target=lambda: c.get_or_set("s", slow), daemon=True)
            t.start()
            assert started.wait(5)
            box = {}
            def other():
                c.set("x", 1)
                box["x"] = c.get("x")
                box["len"] = len(c)
                box["y"] = c.get_or_set("y", lambda: 2)
            try:
                within(3, other, "set/get/len/get_or_set of other keys were blocked while a factory was running")
            finally:
                gate.set()
            t.join(5)
            assert box == {"x": 1, "len": 2, "y": 2} and c.get("s") == "slow", (box, c.keys())
            # a failing factory: the error reaches its caller, a waiting caller then runs its own factory
            c5, attempts, res = TTLCache(10), [], {}
            fail_gate, fail_started = threading.Event(), threading.Event()
            def failing():
                attempts.append("fail")
                fail_started.set()
                fail_gate.wait(10)
                raise RuntimeError("factory failed")
            def good():
                attempts.append("good")
                return 7
            def first():
                try:
                    c5.get_or_set("f", failing)
                except RuntimeError as exc:
                    res["first"] = str(exc)
            t1 = threading.Thread(target=first, daemon=True)
            t1.start()
            assert fail_started.wait(5)
            t2 = threading.Thread(target=lambda: res.__setitem__("second", c5.get_or_set("f", good)), daemon=True)
            t2.start()
            time.sleep(0.3)
            early = dict(res)
            fail_gate.set()
            t1.join(5)
            t2.join(5)
            assert early == {}, f"a second caller for the same key must wait for the running factory: {early}"
            assert res == {"first": "factory failed", "second": 7} and attempts == ["fail", "good"], (res, attempts)
            assert c5.get("f") == 7
        """, CACHE_PRELUDE)},
        {"id": "hidden-thread-safety", "type": "python", "timeout": 180, "code": chk(r"""
            import random, sys
            sys.setswitchinterval(1e-6)
            stats = {"replaced": 0, "capacity": 0, "expired": 0}
            lock = threading.Lock()
            def cb(k, v, r):
                with lock:
                    stats[r] += 1
            c = TTLCache(40, sizeof=len, on_evict=cb)
            counts = [{"sets": 0, "pops": 0, "factory": 0} for _ in range(8)]
            errors = []
            def worker(i):
                rnd = random.Random(i)
                mine = counts[i]
                def fac():
                    mine["factory"] += 1
                    return "y"
                try:
                    for _ in range(2500):
                        k, op = rnd.randrange(30), rnd.random()
                        if op < 0.5:
                            c.set(k, "x" * rnd.randint(1, 5))
                            mine["sets"] += 1
                        elif op < 0.72:
                            c.get(k)
                        elif op < 0.84:
                            if c.pop(k, None) is not None:
                                mine["pops"] += 1
                        elif op < 0.95:
                            c.get_or_set(k, fac)
                        else:
                            len(c)
                            c.keys()
                except Exception as exc:
                    errors.append(f"{type(exc).__name__}: {exc}")
            threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(8)]
            [t.start() for t in threads]
            [t.join(120) for t in threads]
            assert not any(t.is_alive() for t in threads), "worker threads hung (deadlock?)"
            assert not errors, f"exceptions under concurrent use: {errors[:3]}"
            keys = c.keys()
            total = sum(len(c.peek(k)) for k in keys)
            assert total == c.size <= 40, f"size bookkeeping broken under concurrency: size={c.size}, sum of entries={total}"
            stored = sum(x["sets"] + x["factory"] for x in counts)
            gone = stats["replaced"] + stats["capacity"] + sum(x["pops"] for x in counts)
            assert stored - gone == len(keys), f"lost or duplicated entries: {stored} stored - {gone} removed != {len(keys)} live"
        """, CACHE_PRELUDE)},
        {"id": "agent-tests-pass", "type": "python", "code": chk(r"""
            pytest_in(ws, 12, "tests")
        """, PYTEST)},
    ],
}, header="hard 01 — long-horizon coding: TTL + LRU + weighted size + callbacks outside the lock + single-flight get_or_set; hidden tests")

# =========================================================================== 02 multi-file bug hunt
SPLIT_TEST_FILES = {k: v for k, v in D.SPLIT_SETUP.items() if k.startswith("tests/") or k == "conftest.py"}


def _count_tests() -> int:
    with tempfile.TemporaryDirectory() as d:
        for rel, text in {**D.SPLIT_OK, **SPLIT_TEST_FILES}.items():
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"], cwd=d,
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stdout + r.stderr
        return int(r.stdout.split(" passed")[0].split()[-1])


def _split_hidden_values():
    """Expected results of the spec-derived hidden calls, computed with the correct package."""
    calls = {
        "convert": [(1000, "USD", "EUR"), (1, "EUR", "X"), (5, "X", "EUR"), (3, "X", "EUR"), (100000, "SEK", "EUR"),
                    (4550, "CHF", "EUR"), (1080, "USD", "EUR"), (999, "EUR", "USD"), (12345, "USD", "SEK"), (7, "EUR", "EUR")],
        "allocate": [(10, [1, 1, 1, 1]), (7, [0, 1, 1]), (100, [1, 1, 1]), (5, [2, 1, 2]), (1, [1, 1]), (2, [1, 3, 1, 3]),
                     (1001, [5, 3, 2]), (0, [1, 2])],
        "parse": ["0.5", "1,000", "10.05", "1,234,567.8", " 3 "],
        "parse_bad": ["1,0000", "1 000", "12.345", "-0.10", "1,23.45", ""],
        "format": [-5, -1205, 7, 100, 0],
    }
    script = lit("""
        import json, sys
        from splitbill.fx import convert
        from splitbill.money import allocate, format_cents, parse_amount
        from splitbill.ledger import balances
        from splitbill.models import Expense
        from splitbill.settle import settle
        calls = json.loads(sys.argv[1])
        R = {"EUR": "1", "USD": "1.08", "SEK": "11.37", "CHF": "0.94", "X": "2"}
        out = {"convert": [convert(c, f, t, R) for c, f, t in calls["convert"]],
               "allocate": [allocate(t, w) for t, w in calls["allocate"]],
               "parse": [parse_amount(s) for s in calls["parse"]],
               "format": [format_cents(c) for c in calls["format"]]}
        es = [Expense("h1", "2026-10-01", "dora", 10000, "USD", ["dora", "emil", "finn"]),
              Expense("h2", "2026-10-02", "emil", 4550, "CHF", ["dora", "finn"], [2, 1]),
              Expense("h3", "2026-10-03", "finn", 1001, "EUR", ["dora", "emil", "finn"], [5, 3, 2])]
        out["balances"] = balances(es, "EUR", R)
        out["settle"] = settle(out["balances"])
        for s in calls["parse_bad"]:
            try:
                parse_amount(s)
            except ValueError:
                continue
            raise SystemExit(f"reference accepts {s!r}")
        print(json.dumps(out))
    """)
    with tempfile.TemporaryDirectory() as d:
        for rel, text in D.SPLIT_OK.items():
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        r = subprocess.run([sys.executable, "-c", script, json.dumps(calls)], cwd=d, capture_output=True, text=True,
                           timeout=60)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
    return calls, out


SPLIT_NTESTS = _count_tests()
SPLIT_CALLS, SPLIT_EXPECT = _split_hidden_values()
write_task(SUITE, "02-debug-splitbill.yaml", {
    "id": "hard-debug-splitbill",
    "title": "Fix six interacting bugs across a 9-module expense-sharing package",
    "category": "coding",
    "prompt": lit("""
        `splitbill/` is a small expense-sharing package (see `README.md`); `python -m pytest tests` fails. Several bugs are
        spread over its modules, and some of them interact. Fix the package so that every function behaves exactly as
        its docstring says — the docstrings are the specification, and hidden tests check them beyond what `tests/`
        covers (including the command line on other data). Do not modify anything under `tests/` or `conftest.py` (the
        tests are correct) and keep the public API (modules, functions, argument names) unchanged. At the end all tests
        must pass.
    """),
    "setup": {"files": D.SPLIT_SETUP},
    "checks": [
        {"id": "tests-unchanged", "type": "python", "code": chk(r"""
            for rel, h in __HASHES__.items():
                assert path(rel).is_file() and norm_hash(path(rel)) == h, f"{rel} was modified or deleted"
            extra = [p.name for p in path("tests").rglob("*") if p.is_file() and p.suffix == ".py" and str(p.relative_to(ws)) not in __HASHES__]
            assert not extra, f"new files under tests/: {extra}"
        """, HASH, HASHES={k: norm_hash(v) for k, v in SPLIT_TEST_FILES.items()})},
        {"id": "tests-pass", "type": "python", "code": chk(r"""
            pytest_in(ws, __N__, "tests")
        """, PYTEST, N=SPLIT_NTESTS)},
        {"id": "hidden-spec", "type": "python", "code": chk(r"""
            from splitbill.fx import convert
            from splitbill.money import allocate, format_cents, parse_amount
            from splitbill.ledger import balances
            from splitbill.models import Expense
            from splitbill.settle import settle
            calls, want = __CALLS__, __WANT__
            R = {"EUR": "1", "USD": "1.08", "SEK": "11.37", "CHF": "0.94", "X": "2"}
            got = [convert(c, f, t, R) for c, f, t in calls["convert"]]
            bad = [f"convert{tuple(a)} = {g}, expected {w}" for a, g, w in zip(calls["convert"], got, want["convert"]) if g != w]
            assert not bad, "fx.convert must use exact decimal arithmetic rounded half up: " + "; ".join(bad)
            for (t, w), exp in zip(calls["allocate"], want["allocate"]):
                assert allocate(t, w) == exp, f"allocate({t}, {w}) = {allocate(t, w)}, expected {exp}"
            for s, exp in zip(calls["parse"], want["parse"]):
                assert parse_amount(s) == exp, f"parse_amount({s!r}) = {parse_amount(s)}, expected {exp}"
            for s in calls["parse_bad"]:
                try:
                    v = parse_amount(s)
                except ValueError:
                    continue
                raise AssertionError(f"parse_amount({s!r}) should raise ValueError, returned {v}")
            for c, exp in zip(calls["format"], want["format"]):
                assert format_cents(c) == exp, f"format_cents({c}) = {format_cents(c)!r}, expected {exp!r}"
            es = [Expense("h1", "2026-10-01", "dora", 10000, "USD", ["dora", "emil", "finn"]),
                  Expense("h2", "2026-10-02", "emil", 4550, "CHF", ["dora", "finn"], [2, 1]),
                  Expense("h3", "2026-10-03", "finn", 1001, "EUR", ["dora", "emil", "finn"], [5, 3, 2])]
            b = balances(es, "EUR", R)
            assert b == want["balances"], f"balances = {b}, expected {want['balances']}"
            s = [list(x) for x in settle(b)]
            assert s == want["settle"], f"settle = {s}, expected {want['settle']}"
            assert [list(x) for x in settle({"a": 300, "b": 300, "c": -300, "d": -300})] == [["c", "a", 300], ["d", "b", 300]], "settle ties: alphabetical"
        """, CALLS=SPLIT_CALLS, WANT=SPLIT_EXPECT)},
        {"id": "hidden-cli", "type": "python", "code": chk(r"""
            import subprocess, sys, tempfile
            with tempfile.TemporaryDirectory() as d:
                (Path(d) / "trip.csv").write_text(__CSV__, encoding="utf-8")
                (Path(d) / "rates.csv").write_text(__RATES__, encoding="utf-8")
                r = subprocess.run([sys.executable, "-m", "splitbill", str(Path(d) / "trip.csv"), "--rates", str(Path(d) / "rates.csv")],
                                   cwd=ws, capture_output=True, text=True, timeout=60)
                assert r.returncode == 0, "python -m splitbill failed: " + (r.stdout + r.stderr)[-600:]
                got = [l.rstrip() for l in r.stdout.strip().splitlines()]
                want = [l.rstrip() for l in __OUT__.strip().splitlines()]
                assert got == want, "CLI report differs. expected: " + " | ".join(want) + "  got: " + " | ".join(got)
        """, CSV=D.SPLIT_HIDDEN_CSV, RATES=D.SPLIT_HIDDEN_RATES, OUT=D.SPLIT_HIDDEN_OUT)},
    ],
}, header="hard 02 — debugging: 6 bugs in 5 modules (a compensating sign-bug pair, one bug only a hidden spec test sees); tests must stay unchanged")

# =========================================================================== 03 data cleaning
SHIP_COMPARE = r'''
import csv, io, json
def cmp_csv(name, data, want):
    assert not data.startswith(b"\xef\xbb\xbf"), f"{name} must not start with a byte-order mark"
    assert b"\r" not in data, f"{name} must use \\n line endings"
    text = data.decode("utf-8")
    got = [r for r in csv.reader(io.StringIO(text)) if r]
    exp = [r for r in csv.reader(io.StringIO(want)) if r]
    assert got and got[0] == exp[0], f"{name}: header {got[:1]} != {exp[0]}"
    bad = [f"{g} != expected {e}" for g, e in zip(got[1:], exp[1:]) if g != e]
    assert len(got) == len(exp) and not bad, f"{name}: {len(got) - 1} data rows (expected {len(exp) - 1}); " + "; ".join(bad[:4])
def cmp_summary(data, want):
    s, e = json.loads(data.decode("utf-8")), json.loads(want)
    assert set(s) == set(e), f"summary.json keys {sorted(s)} != {sorted(e)}"
    for k in ("valid", "rejected", "duplicates", "by_country"):
        assert s[k] == e[k], f"summary.json {k} = {s[k]!r}, expected {e[k]!r}"
    assert abs(float(s["total_weight_kg"]) - e["total_weight_kg"]) < 0.0005, f"total_weight_kg = {s['total_weight_kg']}, expected {e['total_weight_kg']}"
'''
SHIP_SETUP_CMD = ("python3 -c \"import pathlib; eu = pathlib.Path('raw/eu_shipments.csv'); "
                  "eu.write_bytes(b'\\xef\\xbb\\xbf' + eu.read_bytes()); us = pathlib.Path('raw/us_shipments.csv'); "
                  "us.write_bytes(us.read_text(encoding='utf-8').replace('\\n', '\\r\\n').encode('cp1252'))\"")
write_task(SUITE, "03-data-cleaning-shipments.yaml", {
    "id": "hard-data-cleaning-shipments",
    "title": "Clean three messy shipment exports (encodings, BOM, CRLF, time zones, units, duplicates) — re-run on unseen data",
    "category": "files",
    "prompt": lit("""
        Write `clean.py` (one file, standard library only) in the workspace root and run it. `python clean.py`, started
        from the workspace root, reads the shipment exports in `raw/` and writes the results to `out/`. It will be re-run
        on future exports (same formats, different rows), so everything must be computed from the files.

        Inputs (processing order: EU file, then US file, then web file; rows in file order):
        1. `raw/eu_shipments.csv` — UTF-8 with a byte-order mark, `;`-separated with standard CSV quoting, header
           `Shipment ID;Date;Customer;Country;Weight (kg)`. Dates are `D.M.YYYY` (day first; day and month have 1 or 2
           digits). Weights are kilograms with a decimal comma and optional `.` thousands separators (`1.250,5`).
        2. `raw/us_shipments.csv` — Windows-1252 encoded, CRLF line endings, `,`-separated with standard CSV quoting,
           header `shipment_id,ship_date,customer_name,country,weight_lb`. Dates are `M/D/YYYY` (month first). Weights
           are pounds with a decimal point and optional `,` thousands separators.
        3. `raw/web_shipments.jsonl` — UTF-8, one JSON object per line with the keys `id`, `created_at`, `customer`,
           `country`, `weight`. `created_at` is `YYYY-MM-DDTHH:MM:SS` followed by `Z` or a `±HH:MM` offset. `weight` is
           either a JSON number (kilograms) or a string `<number><unit>` with an optional single space before the unit;
           the number uses a decimal point and the unit is `kg`, `g` or `lb` in any letter case.
        4. `raw/countries.csv` — `alias,code`: country names and codes mapped to ISO codes.

        Cleaning rules:
        - Text values are Unicode-NFC-normalized, stripped, and every inner run of whitespace (including tabs and
          non-breaking spaces) becomes one space. After that, an empty value or one of `n/a`, `na`, `null`, `none`, `-`
          (any letter case) is missing; a JSON `null` or absent key is missing too.
        - `shipment_id`: upper-case it and remove all spaces and `-`; the result must match `[A-Z]{2}[0-9]{5}`.
        - `customer`: the normalized text, letter case unchanged.
        - `date`: `YYYY-MM-DD`; for web records the calendar date of `created_at` converted to UTC.
        - `country`: the ISO code of the normalized value, looked up case-insensitively among the (equally normalized)
          aliases of `countries.csv`.
        - `weight_kg`: the weight in kilograms (1 lb = 0.45359237 kg, 1 g = 0.001 kg), which must be greater than 0,
          rounded half up to 3 decimals (exact decimal rounding of the value as written: `2,0625` kg → `2.063`).
        - Blank rows — empty lines, whitespace-only lines and CSV rows whose fields are all empty — are skipped
          silently. Every other row is either valid or rejected with the first failing reason in this order:
          `bad_row` (CSV row with a wrong number of fields) / `bad_json` (web line that is not a JSON object),
          `bad_id`, `missing_customer`, `bad_date` (missing, wrong format or impossible date), `bad_weight` (missing,
          unparseable — a JSON boolean is not a number — or not > 0), `unknown_country` (missing or unknown).
        - Duplicates: of valid rows with the same `shipment_id`, keep only the LAST one in processing order; each
          dropped row counts as a duplicate (rejected rows never count as duplicates).

        Outputs (UTF-8 without BOM, `\\n` line endings):
        - `out/shipments.csv` — header `shipment_id,date,customer,country,weight_kg`; the kept rows sorted by date,
          then shipment_id; weight_kg with exactly 3 decimals; standard CSV quoting (Python's csv module defaults).
        - `out/rejects.csv` — header `source,line,reason`; `source` is the input file name (e.g. `eu_shipments.csv`),
          `line` the 1-based physical line number in that file (a CSV header is line 1); ordered by processing order,
          then line.
        - `out/summary.json` — exactly the keys `valid` (rows in shipments.csv), `rejected` (rows in rejects.csv),
          `duplicates`, `total_weight_kg` (sum of the weight_kg column, a number rounded to 3 decimals) and
          `by_country` (object: ISO code → number of rows in shipments.csv).
    """),
    "setup": {
        "files": {"raw/eu_shipments.csv": D.EU_MAIN, "raw/us_shipments.csv": D.US_MAIN,
                  "raw/web_shipments.jsonl": D.WEB_MAIN, "raw/countries.csv": D.COUNTRIES},
        "commands": [SHIP_SETUP_CMD],
    },
    "checks": [
        {"id": "outputs-exist", "type": "python", "code": chk(r"""
            for f in ("clean.py", "out/shipments.csv", "out/rejects.csv", "out/summary.json"):
                assert path(f).is_file(), f"{f} is missing"
        """)},
        {"id": "shipments-exact", "type": "python", "code": chk(r"""
            cmp_csv("shipments.csv", path("out/shipments.csv").read_bytes(), __WANT__)
        """, SHIP_COMPARE, WANT=D.SHIP_MAIN["shipments.csv"])},
        {"id": "rejects-exact", "type": "python", "code": chk(r"""
            cmp_csv("rejects.csv", path("out/rejects.csv").read_bytes(), __WANT__)
        """, SHIP_COMPARE, WANT=D.SHIP_MAIN["rejects.csv"])},
        {"id": "summary-exact", "type": "python", "code": chk(r"""
            cmp_summary(path("out/summary.json").read_bytes(), __WANT__)
        """, SHIP_COMPARE, WANT=D.SHIP_MAIN["summary.json"])},
        {"id": "rerun-unseen-data", "type": "python", "timeout": 180, "code": chk(r"""
            import shutil, subprocess, sys, tempfile
            with tempfile.TemporaryDirectory() as d:
                d = Path(d)
                shutil.copy(path("clean.py"), d / "clean.py")
                (d / "raw").mkdir()
                for name, data in __RAW__.items():
                    (d / "raw" / name).write_bytes(data)
                r = subprocess.run([sys.executable, "clean.py"], cwd=d, capture_output=True, text=True, timeout=120)
                assert r.returncode == 0, "clean.py failed on next month's exports: " + (r.stdout + r.stderr)[-800:]
                cmp_csv("shipments.csv", (d / "out/shipments.csv").read_bytes(), __SHIP__)
                cmp_csv("rejects.csv", (d / "out/rejects.csv").read_bytes(), __REJ__)
                cmp_summary((d / "out/summary.json").read_bytes(), __SUM__)
        """, SHIP_COMPARE, RAW=D.ship_bytes(D.EU_V2, D.US_V2, D.WEB_V2), SHIP=D.SHIP_V2["shipments.csv"],
            REJ=D.SHIP_V2["rejects.csv"], SUM=D.SHIP_V2["summary.json"])},
    ],
}, header="hard 03 — data cleaning: BOM / Windows-1252 / CRLF / NBSP / NFC / time zones / units / half-up / duplicates; hidden re-run")

# =========================================================================== 04 multi-source research
DJ = r'''
import html, json, re, urllib.request
from datetime import date, timedelta
def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "pland-eval"})
    return json.load(urllib.request.urlopen(req, timeout=40))
def vt(v):
    return tuple(int(x) for x in re.findall(r"\d+", v))
def admits(spec, ver):
    try:
        from packaging.specifiers import SpecifierSet
        return SpecifierSet(spec or "").contains(ver, prereleases=True)
    except ImportError:
        pass
    v = vt(ver)
    for part in [p.strip() for p in (spec or "").split(",") if p.strip()]:
        m = re.fullmatch(r"(~=|==|!=|<=|>=|<|>)\s*([0-9.]+?)(\.\*)?", part)
        if not m:
            continue
        op, s, star = m.group(1), vt(m.group(2)), m.group(3)
        if star:
            if (op == "==") != (v[:len(s)] == s):
                return False
            continue
        n = max(len(v), len(s))
        a, b = v + (0,) * (n - len(v)), s + (0,) * (n - len(s))
        ok = {"==": a == b, "!=": a != b, "<=": a <= b, ">=": a >= b, "<": a < b, ">": a > b,
              "~=": a >= b and v[:len(s) - 1] == s[:-1]}[op]
        if not ok:
            return False
    return True
def supported(cycles, today):
    # -> (cycles that must be listed, cycles that may be listed): EOL after today; +-1 day and brand-new cycles are optional
    req, opt = [], []
    for c in cycles:
        eol = c.get("eol")
        d = date.fromisoformat(eol) if isinstance(eol, str) else None
        if eol is False or (d and d > today + timedelta(days=1)):
            rel = c.get("releaseDate")
            (opt if rel and date.fromisoformat(rel) >= today - timedelta(days=2) else req).append(c)
        elif d and abs((d - today).days) <= 1:
            opt.append(c)
    return req, opt
def ok_latest(c, today):
    ok = {c["latest"]}
    if c.get("latestReleaseDate") and date.fromisoformat(c["latestReleaseDate"]) >= today - timedelta(days=2):
        parts = c["latest"].split(".")
        if parts[-1].isdigit() and int(parts[-1]) > 0:
            ok.add(".".join(parts[:-1] + [str(int(parts[-1]) - 1)]))
    return ok
def table(doc):
    out = []
    for line in doc.splitlines():
        s = line.strip()
        if s.startswith("|"):
            cells = [html.unescape(x).strip().strip("`*_ ") for x in s.strip("|").split("|")]
            if cells and re.fullmatch(r"(?i)(django\s*)?\d+\.\d+", cells[0]):
                out.append((re.sub(r"(?i)django\s*", "", cells[0]), cells, s))
    return out
_RP = {}
def requires_python(version):
    if version not in _RP:
        _RP[version] = fetch(f"https://pypi.org/pypi/Django/{version}/json")["info"].get("requires_python") or ""
    return _RP[version]
def live():
    today = date.today()
    dj = fetch("https://endoflife.date/api/django.json")
    py = fetch("https://endoflife.date/api/python.json")
    return today, dj, supported(dj, today), supported(py, today)
'''
write_task(SUITE, "04-research-django-matrix.yaml", {
    "id": "hard-research-django-matrix",
    "title": "Django/Python compatibility matrix from endoflife.date + per-release PyPI metadata (verified live)",
    "category": "web",
    "prompt": lit("""
        Build a Django / Python compatibility matrix from live data and write it to `django_matrix.md`:

        1. From the endoflife.date API (`https://endoflife.date/api/django.json` and
           `https://endoflife.date/api/python.json`) take every Django release cycle and every Python release cycle that
           is still supported today (its `eol` date is after today's date).
        2. For each supported Django cycle take its latest patch release (`latest` on endoflife.date) and look up the
           `requires_python` metadata of exactly that release on PyPI (`https://pypi.org/pypi/Django/<version>/json`).
        3. The Python cycles a Django release supports are the supported Python cycles `X.Y` whose version `X.Y`
           satisfies that `requires_python` specifier (PEP 440; e.g. `3.13` satisfies `>=3.12`). Use only this rule — no
           other compatibility information.

        Write a Markdown table with one row per supported Django cycle, newest cycle first, with exactly the columns
        `Django | LTS | Latest | Requires-Python | Python cycles | EOL | Days left` — LTS as `yes`/`no`, Python cycles as
        a comma-separated list in ascending order, EOL as `YYYY-MM-DD`, Days left = number of days from today until the
        EOL date. Below the table add the line `Recommended: Django <cycle> on Python <cycle>` naming the newest supported
        LTS Django cycle and the newest Python cycle it supports. Use the live data, not what you remember: it changes
        over time.
    """),
    "checks": [
        {"id": "matrix-exists", "type": "file_exists", "path": "django_matrix.md"},
        {"id": "django-rows", "type": "python", "code": chk(r"""
            today, dj, (dj_req, dj_opt), _ = live()
            rows = table(path("django_matrix.md").read_text(encoding="utf-8"))
            listed = [r[0] for r in rows]
            assert len(listed) == len(set(listed)), f"duplicate rows: {listed}"
            missing = [c["cycle"] for c in dj_req if c["cycle"] not in listed]
            extra = [x for x in listed if x not in {c["cycle"] for c in dj_req + dj_opt}]
            assert not missing and not extra, f"supported Django cycles today: {[c['cycle'] for c in dj_req]}; missing {missing}, not supported {extra}"
            for cyc, cells, line in rows:
                c = next(x for x in dj if x["cycle"] == cyc)
                assert len(cells) >= 7, f"row for {cyc} needs 7 columns: {line}"
                assert cells[1].lower() == ("yes" if c.get("lts") else "no"), f"{cyc}: LTS should be {'yes' if c.get('lts') else 'no'}: {line}"
                assert cells[2] in ok_latest(c, today), f"{cyc}: latest patch is {c['latest']}, row says {cells[2]!r}"
                assert c["eol"] in cells[5], f"{cyc}: EOL {c['eol']} missing: {line}"
                days = re.search(r"-?\d+", cells[6])
                want = (date.fromisoformat(c["eol"]) - today).days
                assert days and abs(int(days.group()) - want) <= 1, f"{cyc}: days left should be {want}: {line}"
            assert listed == sorted(listed, key=vt, reverse=True), f"rows must be newest cycle first: {listed}"
        """, DJ)},
        {"id": "requires-python", "type": "python", "code": chk(r"""
            today, dj, (dj_req, dj_opt), (py_req, py_opt) = live()
            rows = table(path("django_matrix.md").read_text(encoding="utf-8"))
            assert rows, "no table rows"
            norm = lambda s: re.sub(r"[\s`\\]", "", html.unescape(s))
            for cyc, cells, line in rows:
                c = next((x for x in dj if x["cycle"] == cyc), None)
                assert c is not None and len(cells) >= 7, f"bad row: {line}"
                version = cells[2] if cells[2] in ok_latest(c, today) else c["latest"]
                rp = requires_python(version)
                assert norm(cells[3]) == norm(rp), f"{cyc}: Requires-Python of Django {version} on PyPI is {rp!r}, row says {cells[3]!r}"
                want = sorted((p["cycle"] for p in py_req if admits(rp, p["cycle"])), key=vt)
                maybe = {p["cycle"] for p in py_opt if admits(rp, p["cycle"])}
                got = re.findall(r"\d+\.\d+", cells[4])
                assert [x for x in got if x not in maybe] == want, f"{cyc}: supported Python cycles admitted by {rp!r} are {want} (ascending); row says {cells[4]!r}"
        """, DJ)},
        {"id": "recommended", "type": "python", "code": chk(r"""
            today, dj, (dj_req, dj_opt), (py_req, py_opt) = live()
            doc = path("django_matrix.md").read_text(encoding="utf-8")
            m = re.search(r"(?im)^\W*recommended\W*:?\s*django\s+(\d+\.\d+)\W+on\s+python\s+(\d+\.\d+)", doc)
            assert m, "no line 'Recommended: Django <cycle> on Python <cycle>'"
            ok = set()
            for pool in (dj_req, dj_req + dj_opt):
                lts = [c for c in pool if c.get("lts")]
                if not lts:
                    continue
                best = max(lts, key=lambda c: vt(c["cycle"]))
                rp = requires_python(best["latest"])
                for pys in (py_req, py_req + py_opt):
                    cand = [p["cycle"] for p in pys if admits(rp, p["cycle"])]
                    if cand:
                        ok.add((best["cycle"], max(cand, key=vt)))
            assert (m.group(1), m.group(2)) in ok, f"recommended pair should be {sorted(ok)}, got {(m.group(1), m.group(2))}"
        """, DJ)},
    ],
}, header="hard 04 — research: endoflife.date (Django + Python) combined with per-release PyPI requires_python; checked live with drift tolerance")

# =========================================================================== 05 team: implement / review loop
SEMVER_SPEC = lit("""
    1. `parse(text) -> Version` — strict SemVer 2.0.0 `MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]`:
       - MAJOR, MINOR, PATCH are non-negative decimal integers without leading zeros (`0` is fine, `01` is not);
       - PRERELEASE is one or more dot-separated identifiers of `[0-9A-Za-z-]` (none empty); an identifier made only
         of digits is numeric and must not have a leading zero (`0` ok, `01` invalid, `0a` ok);
       - BUILD is one or more dot-separated non-empty identifiers of `[0-9A-Za-z-]` (leading zeros allowed);
       - no surrounding whitespace, no `v` prefix. Anything else (also a non-string) raises `ValueError`.
       A `Version` has `major`, `minor`, `patch` (ints), `prerelease` (tuple; numeric identifiers as `int`, others as
       `str`), `build` (tuple of `str`), and `str(version)` returns the original text.
    2. `compare(a, b) -> int` (-1, 0 or 1) for two version strings, by SemVer precedence: MAJOR, MINOR, PATCH compared
       numerically; a version with a prerelease has lower precedence than the same version without one; prerelease
       identifiers are compared left to right — numeric ones numerically, alphanumeric ones lexically in ASCII order,
       numeric identifiers always lower than alphanumeric ones, and if all shared identifiers are equal the version
       with fewer identifiers is lower. Build metadata is ignored (`1.0.0+a` equals `1.0.0+b`).
    3. `satisfies(version, range) -> bool`. A range is one or more comparator sets separated by `||` (satisfied if any
       set is); a comparator set is one or more comparators separated by whitespace (all must hold). A comparator is
       `<V`, `<=V`, `>V`, `>=V`, `=V`, `V` (same as `=V`), `^V` or `~V`, where V is a full version as in (1) and
       whitespace between the operator and V is allowed (`>= 1.2.3`).
       - `~1.2.3` means `>=1.2.3 <1.3.0`.
       - `^V` means `>=V` and below the next increment of V's left-most non-zero part: `^1.2.3` → `<2.0.0`,
         `^0.2.3` → `<0.3.0`, `^0.0.3` → `<0.0.4`, `^0.0.0` → `<0.0.1`.
       - Prerelease rule: a version with a prerelease satisfies a comparator set only if, in addition, some comparator
         of that set was written with a version that has a prerelease and the same MAJOR.MINOR.PATCH
         (`1.2.3-alpha.7` satisfies `>1.2.3-alpha.3`; `3.4.5-alpha.9` does not; `1.2.4-beta` does not satisfy
         `^1.2.3`). For `^`/`~` the version written after the operator is the one that counts.
       - An invalid version or range (empty set, unknown operator, partial version such as `^1.2`, `*`, `1.x`,
         hyphen ranges ...) raises `ValueError`.
    4. `max_satisfying(versions, range) -> str | None` — the highest-precedence string of `versions` that satisfies
       the range; invalid version strings in the list are ignored; among equal precedence (differing only in build
       metadata) the first one wins; `None` if none satisfies. An invalid range raises `ValueError`.
""")


def _semver_eval():
    ns: dict = {}
    exec(R.SEMVER, ns)
    return ns


_SV = _semver_eval()
SV_VALID = ["0.0.0", "1.2.3", "10.20.30", "1.1.2-prerelease+meta", "1.0.0-alpha.beta.1", "1.0.0-alpha0.valid",
            "1.0.0-rc.1+build.1", "2.0.0-rc.1+build.123", "10.2.3-DEV-SNAPSHOT", "1.2.3-SNAPSHOT-123",
            "1.0.0+0.build.1-rc.10000aaa-kk-0.1", "99999999999999999999999.999999999999999999.99999999999999999",
            "1.0.0-0A.is.legal", "1.0.0+001", "1.0.0-x-y-z.--", "1.0.0-0", "1.0.0-0a"]
SV_INVALID = ["1", "1.2", "1.2.3-0123", "1.2.3-0123.0123", "1.1.2+.123", "+invalid", "-invalid", "alpha", "1.2.3.DEV",
              "1.2-SNAPSHOT", "01.1.1", "1.01.1", "1.1.01", "1.2.3+", "1.2.3-", " 1.2.3", "1.2.3 ", "v1.2.3",
              "1.2.3-a_b", "1.0.0-alpha..1", "9.8.7+meta+meta", "1.2.3-é", "1.2.3-beta.01", "", "1.2.3\n"]
for _v in SV_VALID:
    _SV["parse"](_v)
for _v in SV_INVALID:
    try:
        _SV["parse"](_v)
        raise AssertionError(_v)
    except ValueError:
        pass
SV_ORDER = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.-1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2",
            "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0", "1.0.1-0", "1.0.1", "1.2.0", "1.10.0", "2.0.0", "10.0.0"]
SV_PAIRS = [("1.0.0-Alpha", "1.0.0-alpha"), ("1.0.0-2", "1.0.0-10"), ("1.0.0-rc.1+b", "1.0.0-rc.1"),
            ("1.0.0-alpha.1.2", "1.0.0-alpha.1"), ("1.0.0-a.b.c", "1.0.0-a.b.c.0"), ("1.0.0+x.1", "1.0.0+y"),
            ("2.0.0-1", "2.0.0-a"), ("1.0.0-z", "1.0.0-Z")]
SV_PAIRS_WANT = [_SV["compare"](a, b) for a, b in SV_PAIRS]
SV_SAT = [("1.2.3", "^1.2.3"), ("1.9.9", "^1.2.3"), ("2.0.0", "^1.2.3"), ("1.2.2", "^1.2.3"), ("0.2.5", "^0.2.3"),
          ("0.3.0", "^0.2.3"), ("0.0.3", "^0.0.3"), ("0.0.4", "^0.0.3"), ("0.0.0", "^0.0.0"), ("0.0.1", "^0.0.0"),
          ("1.2.9", "~1.2.3"), ("1.3.0", "~1.2.3"), ("0.2.9", "~0.2.3"), ("1.2.3-alpha.7", ">1.2.3-alpha.3"),
          ("3.4.5-alpha.9", ">1.2.3-alpha.3"), ("3.4.5", ">1.2.3-alpha.3"), ("1.2.3-beta.4", "^1.2.3-beta.2"),
          ("1.2.4-beta.1", "^1.2.3-beta.2"), ("1.2.3-alpha", "^1.2.3-beta.2"), ("2.0.0-rc.1", "^1.2.3"),
          ("2.0.0-rc.1", ">=2.0.0-rc.0 <2.0.0"), ("1.5.0", "<1.0.0 || >=1.4.0 <1.6.0"),
          ("1.2.0", "<1.0.0 || >=1.4.0 <1.6.0"), ("1.2.3", ">= 1.2.3"), ("1.2.3", "1.2.3"), ("1.2.3+build.9", "=1.2.3"),
          ("1.2.3-beta.1", ">=1.0.0 || >=1.2.3-alpha"), ("1.2.3-beta.1", ">=1.0.0"), ("1.2.4-beta", "^1.2.3"),
          ("1.2.3", "<=1.2.3 >1.2.2"), ("1.2.3", "<1.2.3 || >1.2.3"), ("0.1.0", "~0.1.0-rc.1"),
          ("0.1.0-rc.2", "~0.1.0-rc.1"), ("10.0.0", "^9.1.0 || ^10.0.0"), ("2.0.0", ">1.2.3 <=2.0.0  <3.0.0")]
SV_SAT_WANT = [_SV["satisfies"](v, r) for v, r in SV_SAT]
assert True in SV_SAT_WANT and False in SV_SAT_WANT
SV_BAD_RANGES = ["", "   ", "^1.2", ">=", "1.2.3 ||", "|| 1.2.3", "~>1.2.3", "1.2.3 - 2.0.0", ">=v1.2.3", "*", "1.x",
                 ">= 1.2.3 <", "^01.2.3", ">=1.2.3 || || <2.0.0"]
for _r in SV_BAD_RANGES:
    try:
        _SV["satisfies"]("1.2.3", _r)
        raise AssertionError(_r)
    except ValueError:
        pass
SV_MAX = [(["1.2.3", "1.2.4", "1.3.0", "2.0.0"], "~1.2.0"), (["1.2.3", "1.2.4-beta", "1.2.4"], "^1.2.3"),
          (["2.0.0-rc.1", "1.9.0"], "^1.0.0"), (["1.0.0+b1", "1.0.0+a2", "0.9.0"], "^0.9.0 || 1.0.0"),
          (["1.0.0", "garbage", "1.0.01", "1.1.0", "", "v2.0.0"], ">=1.0.0"), ([], ">=1.0.0"), (["0.1.0"], ">=1.0.0"),
          (["1.2.3-beta.1", "1.2.3-beta.11", "1.2.3-beta.2"], ">=1.2.3-beta.0"), (["0.0.2", "0.0.1"], "^0.0.1")]
SV_MAX_WANT = [_SV["max_satisfying"](v, r) for v, r in SV_MAX]
SV_LOAD = use(LOAD) + 'sv = load("semver_under_test", path("shared/semver/semver.py"))\n'
TEAM_REVIEW_BOTS = [
    {"name": "lead", "title": "Tech Lead", "description": "Plans the work, delegates to the implementer and the reviewer, runs the review loop and integrates"},
    {"name": "implementer", "title": "Implementer", "description": "Writes Python code and tests carefully from a specification and fixes review findings"},
    {"name": "reviewer", "title": "Reviewer", "description": "Reviews code strictly against the specification, probes edge cases by running code, and writes precise findings"},
]
write_task(SUITE, "05-team-semver-review.yaml", {
    "id": "hard-team-semver-review",
    "title": "Lead + implementer + reviewer: strict SemVer library through a review loop (hidden tests)",
    "category": "team",
    "mode": "team",
    "team": {"room": True, "lead": "lead", "bots": TEAM_REVIEW_BOTS},
    "prompt": lit("""
        Team task — we need a strict Semantic Versioning library in the room's shared folder: `shared/semver/semver.py`
        (standard library only) with pytest tests in `shared/semver/tests/` (at least 15 test cases, passing with
        `python -m pytest tests` run from `shared/semver/`). Specification:

    """) + SEMVER_SPEC + lit("""

        Process: the implementer writes the module and the tests. The reviewer then reviews the code against this
        specification — point by point, running edge cases — and records the findings in `shared/review/findings.md`:
        one section per review round (`## Round 1`, `## Round 2`, ...) listing every problem found (or `No issues
        found`), and as the last line of the file the current verdict, `Verdict: APPROVED` or
        `Verdict: CHANGES REQUESTED`. The implementer fixes every finding, and the review repeats until the reviewer
        approves; the final file must end with `Verdict: APPROVED`.
    """),
    "timeout": 1800,
    "checks": [
        {"id": "module-exists", "type": "file_exists", "path": "shared/semver/semver.py"},
        {"id": "hidden-parse", "type": "python", "code": chk(r"""
            bad = []
            for v in __VALID__:
                try:
                    sv.parse(v)
                except Exception as exc:
                    bad.append(f"parse({v!r}) raised {type(exc).__name__}")
            for v in __INVALID__:
                try:
                    sv.parse(v)
                    bad.append(f"parse({v!r}) accepted an invalid version")
                except ValueError:
                    pass
                except Exception as exc:
                    bad.append(f"parse({v!r}) raised {type(exc).__name__} instead of ValueError")
            assert not bad, f"{len(bad)} problem(s): " + "; ".join(bad[:8])
            v = sv.parse("1.0.0-alpha.1.x-y+001.b")
            got = (v.major, v.minor, v.patch, tuple(v.prerelease), tuple(v.build), str(v))
            assert got == (1, 0, 0, ("alpha", 1, "x-y"), ("001", "b"), "1.0.0-alpha.1.x-y+001.b"), got
            v = sv.parse("0.10.200")
            assert (v.major, v.minor, v.patch, tuple(v.prerelease), tuple(v.build)) == (0, 10, 200, (), ()), v
        """, SV_LOAD, VALID=SV_VALID, INVALID=SV_INVALID)},
        {"id": "hidden-compare", "type": "python", "code": chk(r"""
            order = __ORDER__
            bad = []
            for i, a in enumerate(order):
                for j, b in enumerate(order):
                    want = (i > j) - (i < j)
                    if sv.compare(a, b) != want:
                        bad.append(f"compare({a!r}, {b!r}) = {sv.compare(a, b)}, expected {want}")
            for (a, b), want in zip(__PAIRS__, __PAIRS_WANT__):
                if sv.compare(a, b) != want:
                    bad.append(f"compare({a!r}, {b!r}) = {sv.compare(a, b)}, expected {want}")
            assert not bad, f"{len(bad)} wrong comparison(s): " + "; ".join(bad[:8])
        """, SV_LOAD, ORDER=SV_ORDER, PAIRS=SV_PAIRS, PAIRS_WANT=SV_PAIRS_WANT)},
        {"id": "hidden-satisfies", "type": "python", "code": chk(r"""
            bad = []
            for (v, r), want in zip(__SAT__, __SAT_WANT__):
                try:
                    got = sv.satisfies(v, r)
                except Exception as exc:
                    got = f"{type(exc).__name__}"
                if got is not want:
                    bad.append(f"satisfies({v!r}, {r!r}) = {got}, expected {want}")
            for r in __BAD__:
                try:
                    sv.satisfies("1.2.3", r)
                    bad.append(f"range {r!r} should raise ValueError")
                except ValueError:
                    pass
                except Exception as exc:
                    bad.append(f"range {r!r} raised {type(exc).__name__} instead of ValueError")
            try:
                sv.satisfies("1.2", "^1.0.0")
                bad.append("an invalid version must raise ValueError")
            except ValueError:
                pass
            assert not bad, f"{len(bad)} problem(s): " + "; ".join(bad[:8])
        """, SV_LOAD, SAT=SV_SAT, SAT_WANT=SV_SAT_WANT, BAD=SV_BAD_RANGES)},
        {"id": "hidden-max-satisfying", "type": "python", "code": chk(r"""
            bad = []
            for (vs, r), want in zip(__MAX__, __MAX_WANT__):
                got = sv.max_satisfying(list(vs), r)
                if got != want:
                    bad.append(f"max_satisfying({vs}, {r!r}) = {got!r}, expected {want!r}")
            try:
                sv.max_satisfying(["1.0.0"], "^1.2")
                bad.append("max_satisfying with an invalid range must raise ValueError")
            except ValueError:
                pass
            assert not bad, "; ".join(bad)
        """, SV_LOAD, MAX=SV_MAX, MAX_WANT=SV_MAX_WANT)},
        {"id": "team-tests-pass", "type": "python", "code": chk(r"""
            pytest_in(path("shared/semver"), 15, "tests")
        """, PYTEST)},
        {"id": "review-findings", "type": "python", "code": chk(r"""
            import re
            text = path("shared/review/findings.md").read_text(encoding="utf-8")
            rounds = re.findall(r"(?im)^#{2,3}\s*round\s+(\d+)\b", text)
            assert rounds, "findings.md has no '## Round <n>' section"
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            assert re.fullmatch(r"(?i)\W*verdict\W*:?\W*approved\W*", lines[-1]), f"the last line must be 'Verdict: APPROVED', got {lines[-1]!r}"
        """)},
        {"id": "delegated-implementer", "type": "delegated", "min": 1, "to": ["implementer"]},
        {"id": "delegated-reviewer", "type": "delegated", "min": 1, "to": ["reviewer"]},
    ],
}, header="hard 05 — team review loop (lead/implementer/reviewer): subtle spec (SemVer precedence, ^0.x, prerelease rule); hidden tests")

# =========================================================================== 06 HITL: two clarifications + approval
PAYOUT_PARSE = r'''
import csv, io, re
from decimal import Decimal
def remote_file():
    bare = str(path("remote/payouts.git"))
    r = git("--git-dir", bare, "show", "refs/heads/main:2026-Q3.csv")
    assert r.returncode == 0, "2026-Q3.csv is not on main in remote/payouts.git (committed and pushed?)"
    return r.stdout
def lenient_amounts(text):
    # -> {rep_id: Decimal}, whatever delimiter / decimal mark the file uses
    head = text.splitlines()[0] if text.strip() else ""
    delim = ";" if head.count(";") >= head.count(",") and ";" in head else ("\t" if "\t" in head else ",")
    out = {}
    for row in csv.reader(io.StringIO(text), delimiter=delim):
        if not row or not re.fullmatch(r"E\d{4}", row[0].strip()):
            continue
        a = row[-1].strip().replace(" ", "").replace(" ", "")
        if "," in a and "." in a:
            a = a.replace(",", "") if a.rfind(".") > a.rfind(",") else a.replace(".", "").replace(",", ".")
        elif "," in a:
            a = a.replace(",", ".")
        out[row[0].strip()] = Decimal(a)
    return out
'''
write_task(SUITE, "06-hitl-payout-run.yaml", {
    "id": "hard-hitl-payout-run",
    "title": "Commission payout: plan and file format only via two clarifications, then an approved push",
    "category": "hitl",
    "prompt": lit("""
        Please prepare the Q3 2026 commission payout for our sales reps from `data/deals_2026Q3.csv`: compute each rep's
        commission under our 2026 commission plan and write it to `payouts/2026-Q3.csv` in the format the payroll
        importer expects. `payouts/` is a git repository whose remote `origin` (`remote/payouts.git`) is the payroll
        share: commit the file on `main` and push it so payroll picks it up. Leave the working tree clean.
    """),
    "setup": {
        "files": {"data/deals_2026Q3.csv": D.DEALS, "docs/commission_plan_2025.md": D.PLAN_2025,
                  "payouts/README.md": "# Payroll payouts\n\nCommission payout files for the payroll importer, one file per quarter (`YYYY-Qn.csv`).\n"},
        "commands": [
            "git init -q --bare -b main remote/payouts.git",
            "cd payouts && git init -q -b main && git add -A && git commit -qm 'Payroll payout share' && "
            "git remote add origin ../remote/payouts.git && git push -q origin main",
        ],
    },
    "hitl": D.PAYOUT_HITL,
    "checks": [
        {"id": "asked-two-questions", "type": "hitl", "kind": "clarify", "min": 2},
        {"id": "push-approved", "type": "hitl", "kind": "approval", "min": 1},
        {"id": "pushed", "type": "python", "code": chk(r"""
            remote_file()
            bare = str(path("remote/payouts.git"))
            remote_main = git("--git-dir", bare, "rev-parse", "refs/heads/main").stdout.strip()
            local_main = git("rev-parse", "refs/heads/main", cwd=path("payouts")).stdout.strip()
            assert remote_main and remote_main == local_main, "origin/main is not the local main (latest commit not pushed?)"
        """, GIT, PAYOUT_PARSE)},
        {"id": "payout-format", "type": "python", "code": chk(r"""
            text = remote_file()
            assert "\r" not in text, "the file must use \\n line endings"
            lines = text.rstrip("\n").split("\n")
            assert lines[0] == "employee_id;name;commission_eur", f"header is {lines[0]!r}"
            rows, total = lines[1:-1], lines[-1]
            assert rows, "no rep rows"
            names = __NAMES__
            for l in rows:
                assert re.fullmatch(r"E\d{4};[^;\"]+;\d+,\d{2}", l), f"row {l!r} is not <employee_id>;<name>;<amount with decimal comma, 2 decimals>"
                rep, name, _ = l.split(";")
                assert names.get(rep) == name, f"{rep}: name must be {names.get(rep)!r} exactly as in the deals file, not {name!r}"
            ids = [l.split(";")[0] for l in rows]
            assert ids == sorted(ids), f"rows must be sorted by employee_id: {ids}"
            assert re.fullmatch(r"TOTAL;;\d+,\d{2}", total), f"last line {total!r} must be 'TOTAL;;<sum>'"
            s = sum(Decimal(l.split(";")[2].replace(",", ".")) for l in rows)
            assert Decimal(total.split(";")[2].replace(",", ".")) == s, "TOTAL is not the sum of the rows"
        """, GIT, PAYOUT_PARSE, NAMES={r: n for r, n, _ in D.PAYOUT_ROWS} | dict(
            (row.split(",")[1], row.split(",")[2]) for row in D.DEALS.splitlines()[1:]))},
        {"id": "payout-amounts", "type": "python", "code": chk(r"""
            got = lenient_amounts(remote_file())
            want = {k: Decimal(v) for k, v in __WANT__.items()}
            assert set(got) == set(want), f"reps in the file {sorted(got)} != reps with a commission {sorted(want)}"
            wrong = [f"{k}: {got[k]} (expected {want[k]})" for k in sorted(want) if got[k] != want[k]]
            assert not wrong, "wrong commissions under the 2026 plan: " + "; ".join(wrong)
        """, GIT, PAYOUT_PARSE, WANT={r: f"{c:.2f}" for r, _, c in D.PAYOUT_ROWS})},
        {"id": "clean-tree", "type": "git_clean", "repo": "payouts"},
    ],
}, header="hard 06 — HITL: plan + format only from the simulated user (two separate clarifications), approved git push to a local bare remote")

# =========================================================================== 07 cross-agent private knowledge
QUOTES_COMPARE = r'''
import csv, io
def quote_rows(text):
    rows = [r for r in csv.reader(io.StringIO(text)) if r]
    assert rows and [h.strip() for h in rows[0]] == ["order_id", "customer", "subtotal", "discount", "shipping", "total"], f"header {rows[:1]}"
    return [[c.strip() for c in r] for r in rows[1:]]
'''
write_task(SUITE, "07-team-private-pricing.yaml", {
    "id": "hard-team-private-pricing",
    "title": "Quotes that need another bot's private price list and rules (explicit cross-agent communication)",
    "category": "team",
    "mode": "team",
    "team": {"room": True, "lead": "billing", "bots": [
        {"name": "billing", "title": "Billing", "description": "Prepares customer quotes and invoices"},
        {"name": "catalog", "title": "Catalog", "description": "Maintains the product catalogue, price lists and pricing rules"},
    ]},
    "prompt": lit("""
        @billing — please prepare price quotes for the three customer orders in your workspace (`orders/*.json`). Write
        `shared/quotes.csv` with the header `order_id,customer,subtotal,discount,shipping,total` — one row per order,
        sorted by order_id, amounts in EUR with exactly two decimals — and a short summary `shared/quotes.md` for the
        sales team. The quotes must use the current Q4 2026 price list and pricing rules; @catalog owns that information.
    """),
    "setup": {"files": {
        **{f"orders/{o['order_id']}.json": json.dumps(o, indent=2, ensure_ascii=False) + "\n" for o in D.ORDERS},
        "@catalog/pricing/price_list_2026Q4.csv": D.PRICE_Q4,
        "@catalog/pricing/price_list_2026Q3.csv": D.PRICE_Q3,
        "@catalog/pricing/rules_2026Q4.md": D.PRICING_RULES,
    }},
    "memory": "fresh",
    "timeout": 1800,
    "checks": [
        {"id": "quotes-exist", "type": "file_exists", "path": "shared/quotes.csv"},
        {"id": "quotes-exact", "type": "python", "code": chk(r"""
            rows = quote_rows(path("shared/quotes.csv").read_text(encoding="utf-8"))
            want = quote_rows(__WANT__)
            assert [r[0] for r in rows] == [r[0] for r in want], f"orders {[r[0] for r in rows]} != {[r[0] for r in want]} (sorted by order_id)"
            bad = [f"{g} != expected {w}" for g, w in zip(rows, want) if g != w]
            assert not bad, "; ".join(bad)
        """, QUOTES_COMPARE, WANT=D.quotes_csv(D.QUOTES))},
        {"id": "owner-consulted", "type": "python", "code": chk(r"""
            import json, sqlite3
            shared = path("shared").resolve()
            db = shared.parents[2] / "shared.db"
            assert db.is_file(), f"event log not found at {db}"
            con = sqlite3.connect(str(db), timeout=30)
            try:
                rows = con.execute("SELECT type, data FROM events WHERE room_id=? AND type IN ('delegation.finished', 'message.replied', 'room.member_turn')",
                                   (shared.parent.name,)).fetchall()
            finally:
                con.close()
            asked = []
            for typ, data in rows:
                d = json.loads(data)
                if typ in ("delegation.finished", "message.replied") and d.get("to") == "catalog" and d.get("status") == "completed":
                    asked.append(typ)
                elif typ == "room.member_turn" and d.get("member") == "catalog" and d.get("role") == "mentioned" and d.get("state") == "done":
                    asked.append(typ)
            assert asked, "@catalog was never asked: no completed delegation or message to catalog, and no @mention turn of catalog"
        """)},
        {"id": "summary-written", "type": "file_exists", "path": "shared/quotes.md"},
    ],
    "required": ["quotes-exist", "quotes-exact", "owner-consulted"],
}, header="hard 07 — cross-agent knowledge: the Q4 price list + rules exist only in @catalog's private workspace; billing leads")

# =========================================================================== 08 git merge with conflicts
GIT_TREE = r'''
import hashlib, io, subprocess, tarfile, tempfile
def norm(t):
    return "\n".join(l.rstrip() for l in t.strip().splitlines())
def main_parents():
    r = git("rev-list", "--parents", "-n", "1", "refs/heads/main", cwd=path("store"))
    parts = r.stdout.split()
    assert r.returncode == 0 and len(parts) == 3, f"main must point to a merge commit with exactly two parents (rev-list --parents: {parts})"
    return parts
def extract(rev, d):
    r = subprocess.run(["git", "archive", "--format=tar", rev], cwd=str(path("store")), capture_output=True, timeout=60)
    assert r.returncode == 0, f"cannot read the tree of {rev}"
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tf:
        tf.extractall(d)
    return Path(d)
'''
write_task(SUITE, "08-git-merge-conflict.yaml", {
    "id": "hard-git-merge-conflict",
    "title": "Merge a feature branch with textual and semantic conflicts, resolved by stated rules",
    "category": "git",
    "prompt": lit("""
        `store/` is a git repository. Merge the branch `feature/tiered-discounts` into `main`. Both branches changed the
        pricing code since they diverged, so the merge will conflict. Resolve it according to these rules:

        1. Create a real merge commit on `main` whose first parent is the current tip of `main` and whose second parent
           is the tip of `feature/tiered-discounts` (no rebase, squash or cherry-pick; leave the feature branch as it
           is). Resolve everything inside that merge commit: afterwards `main` must point to the merge commit itself,
           with no further commits on top.
        2. `shop/pricing.py`: keep main's API and add the feature's tier discount. The function is
           `compute_total(items, country="DE", *, tier=None, currency="EUR")`: net amount → minus the tier discount →
           plus the VAT of `country` → converted to `currency` → rounded half up to cents once, at the end. Keep every
           VAT rate, FX rate and tier from both branches. `calc_total` must no longer exist anywhere in the Python code
           (no alias): update every caller — including code that only the feature branch added — and the tests.
        3. Tests: keep all tests of both branches. The feature's tests may only change where they must call
           `compute_total` instead of `calc_total` (expected values stay as they are). `python -m pytest` must pass in
           `store/`.
        4. `CHANGELOG.md`: under `## Unreleased` keep every entry of both branches — main's entries first, then the
           feature branch's, each group in its original order. Nothing else in the file changes.
        5. `config.json`: keep every key of both sides; `version` becomes `1.3.0`; for any other key that both sides
           changed, main's value wins. It must stay valid JSON.

        At the end the working tree must be clean.
    """),
    "setup": {"files": D.GIT_SETUP_FILES, "commands": D.GIT_SETUP_COMMANDS},
    "checks": [
        {"id": "merge-commit", "type": "python", "code": chk(r"""
            head, p1, p2 = main_parents()
            feat = git("rev-parse", "refs/heads/feature/tiered-discounts", cwd=path("store")).stdout.strip()
            assert p2 == feat, "the second parent of main's merge commit must be the unchanged tip of feature/tiered-discounts"
            for rev, files, what in ((p1, __MAIN__, "first parent / previous main tip"), (p2, __FEAT__, "second parent / feature tip")):
                for f, want in files.items():
                    got = git("show", f"{rev}:{f}", cwd=path("store"))
                    same = got.returncode == 0 and hashlib.sha256(norm(got.stdout).encode("utf-8")).hexdigest() == want
                    assert same, f"{what}: {f} differs from the original — wrong parents or rewritten history"
        """, GIT, GIT_TREE, MAIN={k: norm_hash(v) for k, v in D.GIT_MAIN_TIP.items()},
            FEAT={k: norm_hash(v) for k, v in D.GIT_FEATURE_TIP.items()})},
        {"id": "pricing-resolved", "type": "python", "code": chk(r"""
            import inspect, re
            main_parents()
            with tempfile.TemporaryDirectory() as d:
                root = extract("refs/heads/main", d)
                bad = [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and re.search(r"(?m)^(<{7}|={7}|>{7})( |$)", p.read_text(errors="replace"))]
                assert not bad, f"conflict markers committed in {bad}"
                left = [str(p.relative_to(root)) for p in root.rglob("*.py") if "calc_total" in p.read_text()]
                assert not left, f"calc_total still appears in {left}"
                pricing = load("pricing_at_head", root / "shop" / "pricing.py")
                assert hasattr(pricing, "compute_total") and not hasattr(pricing, "calc_total"), "pricing.py must define compute_total and no calc_total"
                params = inspect.signature(pricing.compute_total).parameters
                kinds = {n: (p.kind.name, p.default) for n, p in params.items()}
                assert list(params)[:2] == ["items", "country"] and kinds["country"] == ("POSITIONAL_OR_KEYWORD", "DE"), kinds
                assert kinds.get("tier") == ("KEYWORD_ONLY", None) and kinds.get("currency") == ("KEYWORD_ONLY", "EUR"), f"tier and currency must be keyword-only with defaults None / 'EUR': {kinds}"
                for (args, kw), want in zip(__CASES__, __WANT__):
                    got = str(pricing.compute_total(*args, **kw))
                    assert got == want, f"compute_total{tuple(args)} {kw} = {got}, expected {want}"
                sys.path.insert(0, str(root))
                from shop.cart import Cart
                assert str(Cart("AT", tier="gold").add("10.00", 2).add("2.50").total()) == "25.65", "Cart.total() must use compute_total with the tier"
        """, GIT, LOAD, GIT_TREE, CASES=[(list(a), k) for a, k in D.GIT_PRICING_CASES], WANT=D.GIT_PRICING_EXPECTED)},
        {"id": "tests-pass", "type": "python", "code": chk(r"""
            import re
            main_parents()
            with tempfile.TemporaryDirectory() as d:
                root = extract("refs/heads/main", d)
                tests = "\n".join(p.read_text() for p in sorted((root / "tests").glob("test_*.py")))
                for name in ("test_total_de", "test_total_fr", "test_currency", "test_total_at", "test_gold_tier", "test_unknown_tier", "test_cart_total"):
                    assert re.search(rf"def {name}\(", tests), f"test {name} was dropped"
                for literal in ('"113.05"', '"69.84"', '"diamond"', '"12.85"', '"36.00"'):
                    assert literal in tests, f"expected value {literal} of a test changed or disappeared"
                pytest_in(root, 7)
        """, GIT, PYTEST, GIT_TREE)},
        {"id": "changelog", "type": "python", "code": chk(r"""
            main_parents()
            text = git("show", "refs/heads/main:CHANGELOG.md", cwd=path("store")).stdout
            got = [l.rstrip() for l in text.splitlines() if l.strip()]
            assert got == __LINES__, "CHANGELOG.md should read (blank lines ignored): " + " | ".join(__LINES__) + "  — got: " + " | ".join(got)
        """, GIT, GIT_TREE, LINES=D.GIT_CHANGELOG_LINES)},
        {"id": "config", "type": "python", "code": chk(r"""
            import json
            main_parents()
            r = git("show", "refs/heads/main:config.json", cwd=path("store"))
            try:
                cfg = json.loads(r.stdout)
            except ValueError as exc:
                raise AssertionError(f"config.json at main is not valid JSON: {exc}")
            assert cfg == __WANT__, f"config.json = {cfg}, expected {__WANT__}"
        """, GIT, GIT_TREE, WANT=D.GIT_CONFIG_EXPECTED)},
        {"id": "clean-tree", "type": "git_clean", "repo": "store"},
    ],
}, header="hard 08 — git: merge with textual conflicts (code, tests, changelog, JSON) and a semantic one (new caller of a renamed function)")
print("hard written")
