"""Setup data for the final suite (kept separate so builder and validator share it)."""

import json
import os
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from textwrap import dedent

from common import lit
from final_refs import CONVERT, PIPELINE

# --------------------------------------------------------------------------- data pipeline
PRODUCTS = lit("""
    sku,name,category
    KB-01,Mechanical keyboard,Peripherals
    MS-02,Wireless mouse,Peripherals
    MN-27,27in monitor,Displays
    MN-32,32in monitor,Displays
    DK-10,Standing desk,Furniture
    CH-20,Ergonomic chair,Furniture
    CB-05,USB-C cable,Accessories
""")
FX = lit("""
    currency,usd_rate
    USD,1.0
    EUR,1.08
    GBP,1.27
""")
STORE = lit("""
    order_id,date,customer,sku,qty,unit_price,currency
    S-1001,2026-09-02,Alice Cooper,KB-01,1,"1,049.00",EUR
    S-1002,03/09/2026,bob  marley,MS-02,2,25.50,USD
    S-1003,2026-09-05, carol king ,MN-27,1,329.99,GBP
    S-1004,07/09/2026,ALICE COOPER,CB-05,4,9.99,USD
    S-1005,2026-09-09,Dave Grohl,XX-99,1,10.00,USD
    S-1006,2026-09-12,bob marley,DK-10,1,"1,299.00",USD
    S-1007,15/09/2026,Erin Moran,CH-20,0,349.00,EUR
    S-1002,2026-09-16,Bob Marley,MS-02,1,25.50,USD
    S-1008,2026-09-20,Frank Ocean,MN-32,2,,USD
    S-1009,22/09/2026,carol  king,KB-01,1,"1,049.00",CHF
    S-1010,2026-09-28,Grace Slick,CH-20,2,349.00,EUR
    S-1011,02/10/2026,dave grohl,MN-27,1,329.99,GBP
    S-1012,2026-10-04,Alice cooper,MS-02,3,25.50,USD
""")
WEB = "\n".join(json.dumps(o) for o in [
    {"id": "W-2001", "ts": "2026-09-30T22:15:00Z", "customer": "Erin Moran", "sku": "MN-32", "quantity": 1, "price": "549.00", "cur": "USD"},
    {"id": "W-2002", "ts": "2026-10-01T08:00:00Z", "customer": "frank ocean", "sku": "CB-05", "quantity": 10, "price": 9.99, "cur": "USD"},
    {"id": "S-1012", "ts": "2026-10-04T10:00:00Z", "customer": "Alice Cooper", "sku": "MS-02", "quantity": 3, "price": "25.50", "cur": "USD"},
    {"id": "W-2003", "ts": "2026-10-06T12:30:00Z", "customer": "Grace  Slick", "sku": "DK-10", "quantity": 1, "price": "1,299.00", "cur": "GBP"},
    {"id": "W-2004", "ts": "2026-10-07T09:10:00Z", "customer": "Bob Marley", "sku": "KB-01", "quantity": -1, "price": "1049", "cur": "EUR"},
    {"id": "W-2005", "ts": "2026-10-09T18:45:00Z", "customer": "carol king", "sku": "MN-32", "quantity": 1, "price": "n/a", "cur": "USD"},
    {"id": "S-1005", "ts": "2026-10-10T11:11:00Z", "customer": "Dave Grohl", "sku": "CB-05", "quantity": 2, "price": "9.99", "cur": "USD"},
    {"id": "W-2006", "ts": "2026-10-12T07:05:00Z", "customer": "Henry Rollins", "sku": "CH-20", "quantity": 2, "price": 349, "cur": "EUR"},
    {"id": "W-2007", "ts": "2026-10-15T16:20:00Z", "customer": "erin moran", "sku": "KB-01", "quantity": 1, "price": "1,049.00", "cur": "EUR"},
    {"id": "W-2008", "ts": "2026-10-18T13:00:00Z", "customer": "Ivy Smith", "sku": "MS-02", "quantity": 2.5, "price": "25.50", "cur": "USD"},
    {"id": "W-2009", "ts": "2026-10-20T20:00:00Z", "customer": "Grace Slick", "sku": "MN-27", "quantity": 1, "price": "329.99", "cur": "USD"},
]) + "\n"

# "next month's" exports: same formats, different rows (used only by the hidden re-run check)
STORE_V2 = lit("""
    order_id,date,customer,sku,qty,unit_price,currency
    S-2001,01/11/2026,  zoe   baker,MN-32,1,549.00,EUR
    S-2002,2026-11-02,Yuri Gagarin,KB-01,2,"1,049.00",USD
    S-2003,2026-11-03,zoe baker,CB-05,12,9.99,GBP
    S-2004,05/11/2026,Xena Warrior,DK-10,1,"1,299.00",EUR
    S-2005,2026-11-06,Will Turner,CH-20,-2,349.00,USD
    S-2003,2026-11-07,Zoe Baker,CB-05,1,9.99,GBP
    S-2006,08/11/2026,will turner,MS-02,1,abc,USD
    S-2007,2026-11-30,Yuri  GAGARIN,MN-27,3,329.99,USD
    S-2008,2026-12-01,Victor Hugo,CH-20,1,349.00,JPY
""")
WEB_V2 = "\n".join(json.dumps(o) for o in [
    {"id": "W-3001", "ts": "2026-11-01T09:00:00Z", "customer": "victor hugo", "sku": "MS-02", "quantity": 4, "price": 25.5, "cur": "GBP"},
    {"id": "S-2006", "ts": "2026-11-08T10:00:00Z", "customer": "Will Turner", "sku": "MS-02", "quantity": 1, "price": "25.50", "cur": "USD"},
    {"id": "W-3002", "ts": "2026-11-15T14:00:00Z", "customer": "Xena Warrior", "sku": "MN-27", "quantity": 2, "price": "329.99", "cur": "EUR"},
    {"id": "W-3003", "ts": "2026-11-20T23:59:00Z", "customer": "Uma Thurman", "sku": "ZZ-00", "quantity": 1, "price": "5.00", "cur": "USD"},
    {"id": "W-3004", "ts": "2026-12-02T08:30:00Z", "customer": "yuri gagarin", "sku": "CB-05", "quantity": 3, "price": "9.99", "cur": "EUR"},
    {"id": "W-3005", "ts": "2026-12-03T12:00:00Z", "customer": "Uma Thurman", "sku": "DK-10", "quantity": 1, "cur": "USD"},
    {"id": "W-3006", "ts": "2026-12-04T15:45:00Z", "customer": "Zoe Baker", "sku": "CH-20", "quantity": 1, "price": "349.00", "cur": "USD"},
]) + "\n"


def run_pipeline(store, web) -> tuple[dict, str]:
    """Run the reference pipeline on a dataset; returns (summary, clean_orders.csv text)."""
    with tempfile.TemporaryDirectory() as d:
        raw = Path(d) / "raw"
        raw.mkdir()
        for name, text in {"products.csv": PRODUCTS, "fx.csv": FX, "store_orders.csv": store, "web_orders.jsonl": web}.items():
            (raw / name).write_text(text, encoding="utf-8")
        (Path(d) / "pipeline.py").write_text(PIPELINE, encoding="utf-8")
        subprocess.run([sys.executable, "pipeline.py"], cwd=d, check=True)
        summary = json.loads((Path(d) / "out/summary.json").read_text())
        clean = (Path(d) / "out/clean_orders.csv").read_text()
    # sanity: no exact half-cent rounding cases (so any reasonable rounding method agrees)
    return summary, clean


def assert_no_half_cents(store, web):
    import csv
    import io
    rates = {"USD": Decimal("1.0"), "EUR": Decimal("1.08"), "GBP": Decimal("1.27")}
    vals = []
    for r in csv.DictReader(io.StringIO(store)):
        if r["unit_price"].replace(",", "").replace(".", "").isdigit() and r["currency"] in rates and r["qty"].lstrip("-").isdigit():
            vals.append(Decimal(r["qty"]) * Decimal(r["unit_price"].replace(",", "")) * rates[r["currency"]])
    for line in web.splitlines():
        o = json.loads(line)
        p = str(o.get("price", "")).replace(",", "")
        if o.get("cur") in rates and p.replace(".", "").isdigit() and isinstance(o.get("quantity"), int):
            vals.append(Decimal(o["quantity"]) * Decimal(p) * rates[o["cur"]])
    for v in vals:
        frac = (v * 100) - int(v * 100)
        assert frac != Decimal("0.5"), f"half-cent case {v}"


assert_no_half_cents(STORE, WEB)
assert_no_half_cents(STORE_V2, WEB_V2)
PIPE_MAIN = run_pipeline(STORE, WEB)
PIPE_V2 = run_pipeline(STORE_V2, WEB_V2)


# --------------------------------------------------------------------------- multi-file debugging
INV_MODELS = lit('''
    """Data model for invoices. Money is always stored as integer cents."""


    class LineItem:
        def __init__(self, sku, qty, unit_cents):
            self.sku = sku
            self.qty = qty
            self.unit_cents = unit_cents

        def __repr__(self):
            return f"LineItem({self.sku!r}, {self.qty}, {self.unit_cents})"


    class Invoice:
        """An invoice for one customer. Every invoice owns its own list of line items."""

        def __init__(self, customer, items=[]):
            self.customer = customer
            self.items = items

        def add(self, item):
            self.items.append(item)
            return self
''')
INV_PARSER = lit('''
    """Parse line items from the semicolon-separated export format."""

    from .models import LineItem


    def parse_price(text):
        """Convert a decimal price string such as '12.50', '0.29' or '7' to integer cents, exactly."""
        return int(float(text) * 100)


    def parse_items(text):
        """Parse an export. The first line is the header `sku;qty;unit_price`; every other line that is not blank
        and does not start with '#' is one item. Whitespace around fields is ignored."""
        items = []
        lines = text.strip().splitlines()
        for line in lines[1:-1]:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            sku, qty, price = line.split(";")
            items.append(LineItem(sku.strip(), int(qty), parse_price(price.strip())))
        return items
''')
INV_PRICING = lit('''
    """Volume discounts. Discounted line totals are rounded to the nearest cent, with halves rounded up."""

    # (minimum quantity, discount percent), checked from the largest tier down
    TIERS = [(100, 10), (50, 5)]


    def discount_percent(qty):
        """10% for 100 or more units, 5% for 50 or more units, otherwise 0%."""
        for min_qty, pct in TIERS:
            if qty > min_qty:
                return pct
        return 0


    def line_total(item):
        """Total of one line item in cents after its volume discount."""
        gross = item.qty * item.unit_cents
        pct = discount_percent(item.qty)
        return gross * (100 - pct) // 100
''')
INV_REPORT = lit('''
    """Plain-text invoice report."""

    from .pricing import line_total


    def summarize(invoice):
        """Return (rows, total): rows are (sku, line total in cents) sorted by total descending, ties by sku ascending."""
        rows = [(item.sku, line_total(item)) for item in invoice.items]
        rows.sort(key=lambda r: (r[1], r[0]))
        return rows, sum(total for _, total in rows)


    def format_report(invoice):
        rows, total = summarize(invoice)
        lines = [f"Invoice for {invoice.customer}"]
        lines += [f"{sku}: {cents / 100:.2f}" for sku, cents in rows]
        lines.append(f"TOTAL: {total / 100:.2f}")
        return "\\n".join(lines)
''')
INV_TESTS = {
    "tests/test_models.py": lit('''
        from invoicing.models import Invoice, LineItem


        def test_invoices_do_not_share_items():
            a = Invoice("A")
            b = Invoice("B")
            a.add(LineItem("X", 1, 100))
            assert b.items == []
            assert len(a.items) == 1
    '''),
    "tests/test_parser.py": lit('''
        from invoicing.parser import parse_items, parse_price

        EXPORT = "sku;qty;unit_price\\nA-1;2;0.29\\n\\n# comment\\nB-2 ; 1 ; 12.50\\nC-3;3;1.10\\n"


        def test_parse_price_exact():
            assert parse_price("0.29") == 29
            assert parse_price("1.10") == 110
            assert parse_price("12.50") == 1250


        def test_parse_items_keeps_every_item():
            items = parse_items(EXPORT)
            assert [i.sku for i in items] == ["A-1", "B-2", "C-3"]
            assert [i.qty for i in items] == [2, 1, 3]
            assert [i.unit_cents for i in items] == [29, 1250, 110]
    '''),
    "tests/test_pricing.py": lit('''
        from invoicing.models import LineItem
        from invoicing.pricing import discount_percent, line_total


        def test_tier_boundaries():
            assert discount_percent(49) == 0
            assert discount_percent(50) == 5
            assert discount_percent(99) == 5
            assert discount_percent(100) == 10


        def test_line_total_rounding():
            # 51 x 0.33 = 16.83; 5% off = 15.9885 -> 15.99
            assert line_total(LineItem("A", 51, 33)) == 1599
            assert line_total(LineItem("B", 3, 110)) == 330
    '''),
    "tests/test_report.py": lit('''
        from invoicing.models import Invoice, LineItem
        from invoicing.report import format_report, summarize


        def test_summary_sorted_by_total_desc():
            inv = Invoice("ACME", [])
            inv.add(LineItem("CHEAP", 1, 100)).add(LineItem("PRICEY", 2, 5000))
            inv.add(LineItem("MID", 1, 2500)).add(LineItem("ALSO-MID", 5, 500))
            rows, total = summarize(inv)
            assert rows == [("PRICEY", 10000), ("ALSO-MID", 2500), ("MID", 2500), ("CHEAP", 100)]
            assert total == 15100


        def test_format_report():
            inv = Invoice("ACME", [LineItem("A", 50, 199)])
            assert format_report(inv) == "Invoice for ACME\\nA: 94.53\\nTOTAL: 94.53"
    '''),
}


# --------------------------------------------------------------------------- git release flow
GREETER = 'def greet():\n    return "Hello, world!"\n'
GREETER_TEST = 'from greeter import greet\n\n\ndef test_default_greeting():\n    assert greet() == "Hello, world!"\n'
CHANGELOG = "# Changelog\n\n## 0.1.0\n\n- Initial release.\n"


# --------------------------------------------------------------------------- CRM export (HITL)
USERS = [
    {"id": 1, "first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.org", "signup": "2025-12-10T08:15:00Z", "active": True},
    {"id": 2, "first_name": "Alan", "last_name": "Turing", "email": "ALAN@example.org", "signup": "2026-01-03T17:40:00Z", "active": False},
    {"id": 3, "first_name": "Grace", "last_name": "Hopper", "email": None, "signup": "2026-02-14T09:00:00Z", "active": True},
    {"id": 4, "first_name": "Edsger", "last_name": "Dijkstra", "email": " edsger@example.org ", "signup": "2025-11-30T23:59:00Z", "active": True},
    {"id": 5, "first_name": "Barbara", "last_name": "Liskov", "email": "barbara@example.org", "signup": "2026-03-01T00:00:00Z", "active": False},
    {"id": 6, "first_name": "Ken", "last_name": "Thompson", "email": "", "signup": "2026-03-05T12:00:00Z", "active": True},
    {"id": 7, "first_name": "Donald", "last_name": "Knuth", "email": "don@example.org", "signup": "2024-07-19T10:30:00Z", "active": True},
]
USERS_V2 = [
    {"id": 10, "first_name": "Margaret", "last_name": "Hamilton", "email": "Margaret.Hamilton@Example.org", "signup": "2026-04-02T06:00:00Z", "active": True},
    {"id": 11, "first_name": "Linus", "last_name": "Torvalds", "email": None, "signup": "2026-04-03T07:00:00Z", "active": True},
    {"id": 12, "first_name": "Frances", "last_name": "Allen", "email": "fran@example.org", "signup": "2026-01-31T23:00:00Z", "active": False},
    {"id": 13, "first_name": "John", "last_name": "Backus", "email": "  backus@example.org", "signup": "2025-05-09T12:00:00Z", "active": True},
]
CRM_SPEC = lit("""
    Our CRM importer expects exactly this:
    - delimiter `;` (semicolon), UTF-8, no quoting, `\\n` line endings;
    - a header row, exactly: email;full_name;signup_date;active
    - email: trimmed and lowercased; skip users whose email is missing or empty;
    - full_name: `Last, First` (e.g. `Lovelace, Ada`);
    - signup_date: `DD.MM.YYYY` — the date part of the UTC `signup` timestamp;
    - active: `1` for true, `0` for false;
    - rows sorted by email, ascending.
""").strip()


def crm_expected(users) -> str:
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "u.json", Path(d) / "o.csv"
        src.write_text(json.dumps(users), encoding="utf-8")
        (Path(d) / "convert.py").write_text(CONVERT, encoding="utf-8")
        subprocess.run([sys.executable, "convert.py", str(src), str(dst)], cwd=d, check=True)
        return dst.read_text(encoding="utf-8")


CRM_MAIN = crm_expected(USERS)
CRM_V2 = crm_expected(USERS_V2)


# --------------------------------------------------------------------------- logkit hidden log
LOGKIT_HIDDEN_LOG = lit("""
    2026-10-02T08:00:00Z INFO [api] request ok path=/users ms=35
    2026-10-02T08:00:01Z INFO [api] request ok path=/orders ms=120
    2026-10-02T08:00:02Z WARN [cache] miss key=user:42
    2026-10-02T08:00:03Z ERROR [db] query failed table=orders ms=1500
    this line is garbage
    2026-10-02T08:00:04Z DEBUG [scheduler] tick n=1

    2026-10-02T08:00:05Z ERROR [api] upstream error path=/pay ms=1500
    2026-10-02T08:00:06Z NOTICE [api] unknown level
    2026-10-02T08:00:07Z INFO [Auth] bad component case
    2026-10-02T08:00:08Z ERROR [db] deadlock ms=abc
    2026-10-02 08:00:09 INFO [api] wrong timestamp format
    2026-10-02T08:00:10Z INFO [auth] login user=bob ms=80 ms=81
""")


def logkit_expected(text: str) -> dict:
    from final_refs import LOGKIT_PARSER, LOGKIT_STATS, exec_module
    p = exec_module(LOGKIT_PARSER)["parse_line"]
    s = exec_module(LOGKIT_STATS)["summarize"]
    recs, bad = [], 0
    for line in text.splitlines():
        if not line.strip():
            continue
        r = p(line)
        if r is None:
            bad += 1
        else:
            recs.append(r)
    out = s(recs)
    out["malformed"] = bad
    return out


LOGKIT_EXPECT = logkit_expected(LOGKIT_HIDDEN_LOG)

# --------------------------------------------------------------------------- deps audit
REQUIREMENTS = lit("""
    # production pins
    requests==2.25.1
    six==1.17.0
    attrs == 21.2.0   # old pin kept for Python 3.6 compatibility

    idna==2.10
    -r dev-requirements.txt
    urllib3>=1.26
""")

if __name__ == "__main__":
    print(json.dumps(PIPE_MAIN[0], indent=1))
    print(PIPE_MAIN[1])
    print(json.dumps(PIPE_V2[0], indent=1))
    print(PIPE_V2[1])
    print(CRM_MAIN, CRM_V2, sep="\n")
    print(json.dumps(LOGKIT_EXPECT, indent=1))
