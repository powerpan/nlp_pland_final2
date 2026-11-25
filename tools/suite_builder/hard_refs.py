"""Reference implementations for the `hard` suite, kept as source strings: the validator writes them into scratch
workspaces as 'agent output', and hard_data.py executes some of them to compute expected values."""

from textwrap import dedent

# =========================================================================== 01 TTL/LRU cache
TTLCACHE = dedent('''
    """Thread-safe LRU cache with per-key TTL, size limit and eviction callbacks (reference solution)."""
    import math
    import threading
    import time
    from collections import OrderedDict

    __all__ = ["TTLCache"]

    _MISSING = object()


    def _check_ttl(ttl, what="ttl"):
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or math.isnan(ttl) or not ttl > 0:
            raise ValueError(f"{what} must be a positive number of seconds")


    class TTLCache:
        def __init__(self, maxsize, *, default_ttl=None, sizeof=None, on_evict=None, clock=time.monotonic):
            if isinstance(maxsize, bool) or not isinstance(maxsize, int) or maxsize <= 0:
                raise ValueError("maxsize must be a positive int")
            if default_ttl is not None:
                _check_ttl(default_ttl, "default_ttl")
            if sizeof is not None and not callable(sizeof):
                raise ValueError("sizeof must be callable")
            if on_evict is not None and not callable(on_evict):
                raise ValueError("on_evict must be callable")
            if not callable(clock):
                raise ValueError("clock must be callable")
            self.maxsize = maxsize
            self.default_ttl = default_ttl
            self._sizeof = sizeof
            self._on_evict = on_evict
            self._clock = clock
            self._data = OrderedDict()  # key -> [value, expires_at or None, size]; least recently used first
            self._size = 0
            self._lock = threading.Lock()
            self._inflight = {}  # key -> threading.Event of a running get_or_set factory

        # ------------------------------------------------------------ internals (lock held)
        def _expired(self, entry, now):
            return entry[1] is not None and now >= entry[1]

        def _remove(self, key):
            entry = self._data.pop(key)
            self._size -= entry[2]
            return entry

        def _purge(self, now, removed):
            for key in [k for k, e in self._data.items() if self._expired(e, now)]:
                removed.append((key, self._remove(key)[0], "expired"))

        def _live(self, key, now, removed):
            entry = self._data.get(key)
            if entry is None:
                return None
            if self._expired(entry, now):
                removed.append((key, self._remove(key)[0], "expired"))
                return None
            return entry

        def _notify(self, removed):
            if self._on_evict is None:
                return
            for key, value, reason in removed:
                try:
                    self._on_evict(key, value, reason)
                except Exception:
                    pass

        def _size_of(self, value):
            size = 1 if self._sizeof is None else self._sizeof(value)
            if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
                raise ValueError("sizeof must return a positive int")
            if size > self.maxsize:
                raise ValueError("value is larger than maxsize")
            return size

        # ------------------------------------------------------------ public API
        def set(self, key, value, ttl=None):
            if ttl is None:
                ttl = self.default_ttl
            else:
                _check_ttl(ttl)
            size = self._size_of(value)
            removed = []
            with self._lock:
                now = self._clock()
                self._purge(now, removed)
                if key in self._data:
                    old = self._remove(key)
                    removed.append((key, old[0], "replaced"))
                self._data[key] = [value, None if ttl is None else now + ttl, size]
                self._size += size
                while self._size > self.maxsize:
                    victim = next(iter(self._data))
                    if victim == key:  # cannot happen: size <= maxsize; kept as a guard
                        break
                    removed.append((victim, self._remove(victim)[0], "capacity"))
            self._notify(removed)

        def get(self, key, default=None):
            removed = []
            with self._lock:
                entry = self._live(key, self._clock(), removed)
                if entry is not None:
                    self._data.move_to_end(key)
                    value = entry[0]
                else:
                    value = default
            self._notify(removed)
            return value

        def peek(self, key, default=None):
            removed = []
            with self._lock:
                entry = self._live(key, self._clock(), removed)
                value = default if entry is None else entry[0]
            self._notify(removed)
            return value

        def __contains__(self, key):
            removed = []
            with self._lock:
                found = self._live(key, self._clock(), removed) is not None
            self._notify(removed)
            return found

        def pop(self, key, default=_MISSING):
            removed = []
            with self._lock:
                entry = self._live(key, self._clock(), removed)
                if entry is not None:
                    self._remove(key)
            self._notify(removed)
            if entry is not None:
                return entry[0]
            if default is _MISSING:
                raise KeyError(key)
            return default

        def _purged(self, fn):
            removed = []
            with self._lock:
                before = len(self._data)
                self._purge(self._clock(), removed)
                out = fn(before)
            self._notify(removed)
            return out

        def __len__(self):
            return self._purged(lambda before: len(self._data))

        def keys(self):
            return self._purged(lambda before: list(self._data))

        @property
        def size(self):
            return self._purged(lambda before: self._size)

        def expire(self):
            return self._purged(lambda before: before - len(self._data))

        def clear(self):
            with self._lock:
                self._data.clear()
                self._size = 0

        def get_or_set(self, key, factory, ttl=None):
            while True:
                removed = []
                with self._lock:
                    entry = self._live(key, self._clock(), removed)
                    if entry is not None:
                        self._data.move_to_end(key)
                        hit, value, owner, event = True, entry[0], False, None
                    else:
                        hit = False
                        event = self._inflight.get(key)
                        owner = event is None
                        if owner:
                            event = self._inflight[key] = threading.Event()
                self._notify(removed)
                if hit:
                    return value
                if not owner:
                    event.wait()
                    continue
                try:
                    value = factory()
                    self.set(key, value, ttl)
                    return value
                finally:
                    with self._lock:
                        self._inflight.pop(key, None)
                    event.set()
''')

TTLCACHE_TESTS = dedent('''
    import threading
    import time

    import pytest
    from ttlcache import TTLCache


    class Clock:
        def __init__(self):
            self.t = 0.0

        def __call__(self):
            return self.t


    def test_get_set():
        c = TTLCache(3)
        c.set("a", 1)
        assert c.get("a") == 1 and c.get("x", 7) == 7

    def test_lru_eviction():
        ev = []
        c = TTLCache(2, on_evict=lambda k, v, r: ev.append((k, r)))
        c.set("a", 1); c.set("b", 2); c.get("a"); c.set("c", 3)
        assert c.keys() == ["a", "c"] and ev == [("b", "capacity")]

    def test_peek_and_in_do_not_touch():
        c = TTLCache(2)
        c.set("a", 1); c.set("b", 2)
        assert "a" in c and c.peek("a") == 1
        c.set("c", 3)
        assert "a" not in c

    def test_expiry_boundary():
        clk = Clock()
        c = TTLCache(5, default_ttl=10, clock=clk)
        c.set("a", 1)
        clk.t = 9.99
        assert c.get("a") == 1
        clk.t = 10
        assert c.get("a") is None

    def test_per_key_ttl_and_reset():
        clk = Clock()
        c = TTLCache(5, default_ttl=10, clock=clk)
        c.set("a", 1, ttl=2)
        clk.t = 1
        c.set("a", 2)
        clk.t = 10.5
        assert c.get("a") == 2

    def test_len_purges_with_callback():
        clk, ev = Clock(), []
        c = TTLCache(5, clock=clk, on_evict=lambda k, v, r: ev.append((k, r)))
        c.set("a", 1, ttl=1); c.set("b", 2)
        clk.t = 1
        assert len(c) == 1 and ev == [("a", "expired")]

    def test_weighted_capacity():
        ev = []
        c = TTLCache(5, sizeof=len, on_evict=lambda k, v, r: ev.append((k, r)))
        c.set("a", "xx"); c.set("b", "xx"); c.set("c", "xxx")
        assert c.keys() == ["b", "c"] and c.size == 5 and ev == [("a", "capacity")]

    def test_oversize_rejected_unchanged():
        c = TTLCache(3, sizeof=len)
        c.set("a", "x")
        with pytest.raises(ValueError):
            c.set("b", "xxxx")
        assert c.keys() == ["a"]

    def test_replaced_callback():
        ev = []
        c = TTLCache(3, on_evict=lambda k, v, r: ev.append((k, v, r)))
        c.set("a", 1); c.set("a", 2)
        assert ev == [("a", 1, "replaced")] and c.get("a") == 2

    def test_pop():
        ev = []
        c = TTLCache(3, on_evict=lambda *a: ev.append(a))
        c.set("a", 1)
        assert c.pop("a") == 1 and c.pop("a", None) is None and ev == []
        with pytest.raises(KeyError):
            c.pop("a")

    @pytest.mark.parametrize("bad", [0, -1, True, 2.5, "3"])
    def test_bad_maxsize(bad):
        with pytest.raises(ValueError):
            TTLCache(bad)

    @pytest.mark.parametrize("bad", [0, -1, True, "5"])
    def test_bad_ttl(bad):
        c = TTLCache(3)
        with pytest.raises(ValueError):
            c.set("a", 1, ttl=bad)

    def test_callback_can_reenter():
        seen = []
        c = TTLCache(1, on_evict=lambda k, v, r: seen.append(len(c)))
        c.set("a", 1); c.set("b", 2)
        assert seen == [1]

    def test_callback_exception_ignored():
        def boom(*a):
            raise RuntimeError("x")
        c = TTLCache(1, on_evict=boom)
        c.set("a", 1); c.set("b", 2)
        assert c.keys() == ["b"]

    def test_get_or_set_single_factory():
        c, calls = TTLCache(10), []
        def factory():
            calls.append(1)
            time.sleep(0.1)
            return 42
        out = []
        ts = [threading.Thread(target=lambda: out.append(c.get_or_set("k", factory))) for _ in range(5)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert out == [42] * 5 and len(calls) == 1
''')

# =========================================================================== 03 data cleaning
CLEAN = dedent('''
    """Shipment export cleaner (reference solution)."""
    import csv
    import io
    import json
    import re
    import unicodedata
    from datetime import date, datetime, timezone
    from decimal import ROUND_HALF_UP, Decimal
    from pathlib import Path

    RAW, OUT = Path("raw"), Path("out")
    MISSING = {"", "n/a", "na", "null", "none", "-"}
    LB = Decimal("0.45359237")


    def norm(v):
        if v is None:
            return None
        s = " ".join(unicodedata.normalize("NFC", str(v)).split())
        return None if s.casefold() in MISSING else s


    def norm_id(v):
        s = norm(v)
        if s is None:
            return None
        s = re.sub(r"[ -]", "", s.upper())
        return s if re.fullmatch(r"[A-Z]{2}[0-9]{5}", s) else None


    def mkdate(y, m, d):
        try:
            return date(int(y), int(m), int(d)).isoformat()
        except ValueError:
            return None


    def eu_date(s):
        m = re.fullmatch(r"(\\d{1,2})\\.(\\d{1,2})\\.(\\d{4})", s or "")
        return mkdate(m.group(3), m.group(2), m.group(1)) if m else None


    def us_date(s):
        m = re.fullmatch(r"(\\d{1,2})/(\\d{1,2})/(\\d{4})", s or "")
        return mkdate(m.group(3), m.group(1), m.group(2)) if m else None


    def web_date(s):
        if not isinstance(s, str) or not re.fullmatch(r"\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(Z|[+-]\\d{2}:\\d{2})", s):
            return None
        try:
            ts = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
        return ts.astimezone(timezone.utc).date().isoformat()


    def kg(value):
        if value is None or value <= 0:
            return None
        return value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


    def eu_weight(s):
        if s is None:
            return None
        if re.fullmatch(r"\\d{1,3}(\\.\\d{3})+(,\\d+)?|\\d+(,\\d+)?", s):
            return kg(Decimal(s.replace(".", "").replace(",", ".")))
        return None


    def us_weight(s):
        if s is None:
            return None
        if re.fullmatch(r"\\d{1,3}(,\\d{3})+(\\.\\d+)?|\\d+(\\.\\d+)?", s):
            return kg(Decimal(s.replace(",", "")) * LB)
        return None


    def web_weight(v):
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return kg(Decimal(str(v)))
        s = norm(v)
        m = re.fullmatch(r"(\\d+(?:\\.\\d+)?) ?(kg|g|lb)", s or "", re.IGNORECASE)
        if not m:
            return None
        factor = {"kg": Decimal(1), "g": Decimal("0.001"), "lb": LB}[m.group(2).lower()]
        return kg(Decimal(m.group(1)) * factor)


    def load_countries():
        with open(RAW / "countries.csv", encoding="utf-8", newline="") as fh:
            return {norm(r["alias"]).casefold(): r["code"].strip() for r in csv.DictReader(fh)}


    def check(rec, countries):
        """rec: dict with id, customer, date (already parsed or None), weight (Decimal or None), country (raw)."""
        sid = norm_id(rec["id"])
        if sid is None:
            return None, "bad_id"
        customer = norm(rec["customer"])
        if customer is None:
            return None, "missing_customer"
        if rec["date"] is None:
            return None, "bad_date"
        if rec["weight"] is None:
            return None, "bad_weight"
        country = norm(rec["country"])
        code = countries.get(country.casefold()) if country else None
        if code is None:
            return None, "unknown_country"
        return {"shipment_id": sid, "date": rec["date"], "customer": customer, "country": code,
                "weight_kg": rec["weight"]}, None


    def csv_rows(name, encoding, delimiter, header, conv):
        text = (RAW / name).read_bytes().decode(encoding)
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
        first = next(reader)
        assert [h.strip() for h in first] == header, (name, first)
        for row in reader:
            line = reader.line_num
            if all(not c.strip() for c in row):
                continue
            if len(row) != len(header):
                yield name, line, None
                continue
            yield name, line, conv(row)


    def eu(row):
        sid, d, cust, country, w = row
        return {"id": sid, "customer": cust, "date": eu_date(norm(d)), "weight": eu_weight(norm(w)), "country": country}


    def us(row):
        sid, d, cust, country, w = row
        return {"id": sid, "customer": cust, "date": us_date(norm(d)), "weight": us_weight(norm(w)), "country": country}


    def web_rows(name):
        text = (RAW / name).read_text(encoding="utf-8")
        for line, raw in enumerate(text.split("\\n"), 1):
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
            except ValueError:
                obj = None
            if not isinstance(obj, dict):
                yield name, line, None
                continue
            yield name, line, {"id": obj.get("id"), "customer": obj.get("customer"), "date": web_date(obj.get("created_at")),
                               "weight": web_weight(obj.get("weight")), "country": obj.get("country")}


    def main():
        countries = load_countries()
        sources = [
            csv_rows("eu_shipments.csv", "utf-8-sig", ";", ["Shipment ID", "Date", "Customer", "Country", "Weight (kg)"], eu),
            csv_rows("us_shipments.csv", "cp1252", ",", ["shipment_id", "ship_date", "customer_name", "country", "weight_lb"], us),
            web_rows("web_shipments.jsonl"),
        ]
        kept, rejects, dups = {}, [], 0
        for src in sources:
            for name, line, rec in src:
                if rec is None:
                    rejects.append((name, line, "bad_json" if name.endswith(".jsonl") else "bad_row"))
                    continue
                row, reason = check(rec, countries)
                if reason:
                    rejects.append((name, line, reason))
                    continue
                if row["shipment_id"] in kept:
                    dups += 1
                    del kept[row["shipment_id"]]
                kept[row["shipment_id"]] = row
        rows = sorted(kept.values(), key=lambda r: (r["date"], r["shipment_id"]))
        OUT.mkdir(exist_ok=True)
        with open(OUT / "shipments.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, lineterminator="\\n")
            w.writerow(["shipment_id", "date", "customer", "country", "weight_kg"])
            for r in rows:
                w.writerow([r["shipment_id"], r["date"], r["customer"], r["country"], f"{r['weight_kg']:.3f}"])
        with open(OUT / "rejects.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, lineterminator="\\n")
            w.writerow(["source", "line", "reason"])
            w.writerows(rejects)
        by_country = {}
        for r in rows:
            by_country[r["country"]] = by_country.get(r["country"], 0) + 1
        total = sum((r["weight_kg"] for r in rows), Decimal(0))
        summary = {"valid": len(rows), "rejected": len(rejects), "duplicates": dups,
                   "total_weight_kg": float(total), "by_country": dict(sorted(by_country.items()))}
        (OUT / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")


    if __name__ == "__main__":
        main()
''')

# =========================================================================== 05 semver (team review loop)
SEMVER = dedent('''
    """Strict SemVer 2.0.0 parsing, precedence and npm-style ranges (reference solution)."""
    import re

    __all__ = ["Version", "parse", "compare", "satisfies", "max_satisfying"]

    _NUM = r"0|[1-9][0-9]*"
    _IDS = r"[0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*"
    _VERSION = re.compile(rf"({_NUM})\\.({_NUM})\\.({_NUM})(?:-({_IDS}))?(?:\\+({_IDS}))?")
    _COMPARATOR = re.compile(r"(<=|>=|<|>|=|\\^|~)?\\s*([^\\s<>=^~]+)")


    class Version:
        def __init__(self, major, minor, patch, prerelease=(), build=(), text=None):
            self.major, self.minor, self.patch = major, minor, patch
            self.prerelease, self.build = tuple(prerelease), tuple(build)
            self.text = text

        @property
        def triple(self):
            return (self.major, self.minor, self.patch)

        def __str__(self):
            return self.text

        def __repr__(self):
            return f"Version({self.text!r})"


    def parse(text):
        if not isinstance(text, str):
            raise ValueError("version must be a string")
        m = _VERSION.fullmatch(text)
        if not m:
            raise ValueError(f"invalid version: {text!r}")
        pre = []
        if m.group(4) is not None:
            for ident in m.group(4).split("."):
                if ident.isdigit():
                    if len(ident) > 1 and ident[0] == "0":
                        raise ValueError(f"numeric prerelease identifier with a leading zero: {text!r}")
                    pre.append(int(ident))
                else:
                    pre.append(ident)
        build = m.group(5).split(".") if m.group(5) is not None else []
        return Version(int(m.group(1)), int(m.group(2)), int(m.group(3)), pre, build, text)


    def _cmp_pre(a, b):
        if not a or not b:
            return (not a) - (not b)
        for x, y in zip(a, b):
            if x == y:
                continue
            if isinstance(x, int) and isinstance(y, int):
                return -1 if x < y else 1
            if isinstance(x, int) != isinstance(y, int):
                return -1 if isinstance(x, int) else 1
            return -1 if x < y else 1
        return (len(a) > len(b)) - (len(a) < len(b))


    def _cmp(a, b):
        if a.triple != b.triple:
            return -1 if a.triple < b.triple else 1
        return _cmp_pre(a.prerelease, b.prerelease)


    def compare(a, b):
        return _cmp(parse(a), parse(b))


    def _comparator_set(part):
        part = part.strip()
        if not part:
            raise ValueError("empty comparator set")
        tests, written, pos = [], [], 0
        while pos < len(part):
            m = _COMPARATOR.match(part, pos)
            if not m:
                raise ValueError(f"invalid comparator at {part[pos:]!r}")
            op, v = m.group(1) or "=", parse(m.group(2))
            written.append(v)
            if op == "^":
                if v.major:
                    hi = (v.major + 1, 0, 0)
                elif v.minor:
                    hi = (0, v.minor + 1, 0)
                else:
                    hi = (0, 0, v.patch + 1)
                tests += [(">=", v), ("<", Version(*hi))]
            elif op == "~":
                tests += [(">=", v), ("<", Version(v.major, v.minor + 1, 0))]
            else:
                tests.append((op, v))
            pos = m.end()
            while pos < len(part) and part[pos].isspace():
                pos += 1
        return tests, written


    def _parse_range(text):
        if not isinstance(text, str):
            raise ValueError("range must be a string")
        return [_comparator_set(part) for part in text.split("||")]


    _OPS = {"<": lambda c: c < 0, "<=": lambda c: c <= 0, ">": lambda c: c > 0, ">=": lambda c: c >= 0,
            "=": lambda c: c == 0}


    def _satisfies(v, sets):
        for tests, written in sets:
            if not all(_OPS[op](_cmp(v, w)) for op, w in tests):
                continue
            if v.prerelease and not any(w.prerelease and w.triple == v.triple for w in written):
                continue
            return True
        return False


    def satisfies(version, range_):
        sets = _parse_range(range_)
        return _satisfies(parse(version), sets)


    def max_satisfying(versions, range_):
        sets = _parse_range(range_)
        best = None
        for text in versions:
            try:
                v = parse(text)
            except ValueError:
                continue
            if _satisfies(v, sets) and (best is None or _cmp(v, best[1]) > 0):
                best = (text, v)
        return best[0] if best else None
''')

SEMVER_TESTS = dedent('''
    import pytest
    from semver import compare, max_satisfying, parse, satisfies

    ORDER = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11",
             "1.0.0-rc.1", "1.0.0", "2.0.0", "2.1.0", "2.1.1", "10.0.0"]


    def test_parse_fields():
        v = parse("1.2.3-rc.1+build.7")
        assert (v.major, v.minor, v.patch, v.prerelease, v.build) == (1, 2, 3, ("rc", 1), ("build", "7"))
        assert str(v) == "1.2.3-rc.1+build.7"

    @pytest.mark.parametrize("bad", ["1.2", "01.2.3", "1.2.3-", "1.2.3-01", "v1.2.3", " 1.2.3", "1.2.3-a..b", "1.2.3+"])
    def test_parse_invalid(bad):
        with pytest.raises(ValueError):
            parse(bad)

    @pytest.mark.parametrize("i", range(len(ORDER) - 1))
    def test_precedence_chain(i):
        assert compare(ORDER[i], ORDER[i + 1]) == -1 and compare(ORDER[i + 1], ORDER[i]) == 1

    def test_build_ignored():
        assert compare("1.0.0+a", "1.0.0+b") == 0

    @pytest.mark.parametrize("v,r,ok", [("1.9.9", "^1.2.3", True), ("2.0.0", "^1.2.3", False),
                                        ("0.2.9", "^0.2.3", True), ("0.3.0", "^0.2.3", False),
                                        ("0.0.4", "^0.0.3", False), ("1.2.9", "~1.2.3", True),
                                        ("1.3.0", "~1.2.3", False), ("1.2.3-alpha.7", ">1.2.3-alpha.3", True),
                                        ("3.4.5-alpha.9", ">1.2.3-alpha.3", False), ("1.5.0", "<1.0.0 || >=1.4.0 <1.6.0", True),
                                        ("1.2.3", ">= 1.2.3", True)])
    def test_satisfies(v, r, ok):
        assert satisfies(v, r) is ok

    def test_invalid_range():
        with pytest.raises(ValueError):
            satisfies("1.0.0", "^1.2")

    def test_max_satisfying():
        assert max_satisfying(["1.2.3", "1.2.4-beta", "1.2.4", "1.3.0"], "~1.2.0") == "1.2.4"
        assert max_satisfying(["1.0.0+b", "1.0.0+a"], "1.0.0") == "1.0.0+b"
        assert max_satisfying(["0.1.0"], ">=1.0.0") is None
''')
