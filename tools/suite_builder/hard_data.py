"""Setup data and expected values for the `hard` suite (shared by build_hard.py and ref_hard.py).

Every expected value is computed here by running reference code, never typed by hand."""

from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
import tempfile
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from common import lit

# =========================================================================== 02 splitbill (debugging)
# The correct package. SPLIT_BUGS below turns it into the buggy setup version (exact, asserted replacements).
SPLIT_OK = {
    "splitbill/__init__.py": lit('''
        """splitbill — share group expenses and settle up."""
        from .csvio import read_expenses
        from .ledger import balances
        from .settle import settle

        __all__ = ["read_expenses", "balances", "settle"]
    '''),
    "splitbill/money.py": lit('''
        """Money helpers. All amounts are integers in cents."""
        import re

        _AMOUNT = re.compile(r"\\d{1,3}(,\\d{3})+(\\.\\d{1,2})?|\\d+(\\.\\d{1,2})?")


        def parse_amount(text):
            """Parse a non-negative decimal amount such as "12", "12.5", "12.50" or "1,234.56" into cents
            (1250 for "12.5"). Surrounding whitespace is ignored; thousands separators must group digits by three.
            Anything else (negative numbers, more than two decimals, empty text) raises ValueError."""
            s = text.strip()
            if not _AMOUNT.fullmatch(s):
                raise ValueError(f"invalid amount: {text!r}")
            whole, _, frac = s.replace(",", "").partition(".")
            return int(whole) * 100 + int((frac + "00")[:2])


        def format_cents(cents):
            """Format cents with two decimals: 1250 -> "12.50", 5 -> "0.05", -1205 -> "-12.05"."""
            sign = "-" if cents < 0 else ""
            cents = abs(cents)
            return f"{sign}{cents // 100}.{cents % 100:02d}"


        def allocate(total, weights):
            """Split `total` cents (>= 0) proportionally to the non-negative integer `weights` (largest-remainder
            method): part i first gets floor(total * w_i / sum(weights)); the cents left over are then handed out one
            each to the parts with the largest remainders, ties going to the EARLIER part. The parts always sum to
            `total`. Raises ValueError if the weights are empty, negative or all zero."""
            if not weights or any(w < 0 for w in weights) or sum(weights) == 0:
                raise ValueError("weights must be non-negative and not all zero")
            s = sum(weights)
            parts = [total * w // s for w in weights]
            rema = [total * w % s for w in weights]
            order = sorted(range(len(weights)), key=lambda i: (-rema[i], i))
            for i in order[:total - sum(parts)]:
                parts[i] += 1
            return parts
    '''),
    "splitbill/fx.py": lit('''
        """Currency conversion."""
        from decimal import ROUND_HALF_UP, Decimal


        def convert(cents, from_cur, to_cur, rates):
            """Convert an amount of `cents` in `from_cur` into cents of `to_cur`. `rates` maps a currency code to the
            number of units of that currency per 1 EUR (strings or numbers, e.g. {"EUR": "1", "USD": "1.08"}).
            The result is computed with exact decimal arithmetic and rounded half up to whole cents
            (e.g. 1000 USD-cents at 1.08 -> 925.925... -> 926 EUR-cents). Unknown currencies raise KeyError."""
            if from_cur == to_cur:
                return cents
            value = Decimal(cents) * Decimal(str(rates[to_cur])) / Decimal(str(rates[from_cur]))
            return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    '''),
    "splitbill/models.py": lit('''
        """Data model."""
        from dataclasses import dataclass, field


        @dataclass
        class Expense:
            id: str
            date: str                      # YYYY-MM-DD
            payer: str
            amount: int                    # cents, in `currency`
            currency: str
            participants: list = field(default_factory=list)
            weights: list = None           # None = equal shares
    '''),
    "splitbill/split.py": lit('''
        """How an expense is shared among its participants."""
        from .money import allocate


        def shares(expense, amount=None):
            """Return {participant: cents}: how much of the expense each participant consumed. `amount` (cents)
            replaces expense.amount, e.g. after currency conversion. Without weights everybody gets an equal share.
            The parts come from money.allocate in the order of expense.participants. A participant listed twice or
            a weights list of the wrong length raises ValueError."""
            total = expense.amount if amount is None else amount
            names = list(expense.participants)
            if not names or len(set(names)) != len(names):
                raise ValueError(f"{expense.id}: participants must be non-empty and unique")
            weights = list(expense.weights) if expense.weights else [1] * len(names)
            if len(weights) != len(names):
                raise ValueError(f"{expense.id}: {len(weights)} weights for {len(names)} participants")
            return dict(zip(names, allocate(total, weights)))
    '''),
    "splitbill/ledger.py": lit('''
        """Net balances."""
        from .fx import convert
        from .split import shares


        def balances(expenses, base="EUR", rates=None):
            """Net balance per person in cents of `base`: POSITIVE means the person is owed money (paid more than
            they consumed), NEGATIVE means the person owes money. Each expense amount is first converted to `base`
            with fx.convert and then split with split.shares; the payer is credited the converted amount and every
            participant is debited its share. Everybody who appears as payer or participant is included (also with
            a zero balance). The balances always sum to zero."""
            rates = rates or {base: "1"}
            bal = {}
            for e in expenses:
                amount = convert(e.amount, e.currency, base, rates)
                bal[e.payer] = bal.get(e.payer, 0) + amount
                for name, part in shares(e, amount).items():
                    bal[name] = bal.get(name, 0) - part
            return bal
    '''),
    "splitbill/settle.py": lit('''
        """Settle balances with as few, simple transfers as the greedy rule gives."""


        def settle(balances):
            """Turn balances (positive = is owed money, negative = owes money; see ledger.balances) into a list of
            transfers (debtor, creditor, cents). Greedy rule: repeatedly the person who owes the most pays the
            person who is owed the most (ties: alphabetically first name), transferring the smaller of the two
            open amounts. Zero balances are ignored. Transfers are returned in the order they are made."""
            debts = {n: -b for n, b in balances.items() if b < 0}
            credits = {n: b for n, b in balances.items() if b > 0}
            out = []
            while debts and credits:
                d = min(debts, key=lambda n: (-debts[n], n))
                c = min(credits, key=lambda n: (-credits[n], n))
                amount = min(debts[d], credits[c])
                out.append((d, c, amount))
                debts[d] -= amount
                credits[c] -= amount
                if not debts[d]:
                    del debts[d]
                if not credits[c]:
                    del credits[c]
            return out
    '''),
    "splitbill/csvio.py": lit('''
        """Reading expenses from CSV."""
        import csv
        import io

        from .models import Expense
        from .money import parse_amount

        HEADER = ["id", "date", "payer", "amount", "currency", "participants", "weights"]


        def read_expenses(text):
            """Parse CSV text whose first row is the header id,date,payer,amount,currency,participants,weights.
            Fields follow normal CSV quoting rules (an amount with a thousands separator, like "1,234.56", is
            quoted). `participants` and `weights` are ';'-separated lists; names are stripped of surrounding
            whitespace; an empty `weights` field means equal shares. The currency is upper-cased. Blank lines are
            skipped. A row with the wrong number of fields or a bad amount/weight raises ValueError mentioning its
            line number (the header is line 1)."""
            rows = csv.reader(io.StringIO(text))
            header = next(rows, None)
            if [h.strip() for h in header or []] != HEADER:
                raise ValueError(f"bad header: {header}")
            out = []
            for row in rows:
                line = rows.line_num
                if not row or all(not c.strip() for c in row):
                    continue
                if len(row) != len(HEADER):
                    raise ValueError(f"line {line}: expected {len(HEADER)} fields, got {len(row)}")
                rec = dict(zip(HEADER, row))
                try:
                    amount = parse_amount(rec["amount"])
                    weights = [int(w) for w in rec["weights"].split(";")] if rec["weights"].strip() else None
                except ValueError as exc:
                    raise ValueError(f"line {line}: {exc}") from None
                names = [n.strip() for n in rec["participants"].split(";") if n.strip()]
                out.append(Expense(rec["id"].strip(), rec["date"].strip(), rec["payer"].strip(), amount,
                                   rec["currency"].strip().upper(), names, weights))
            return out
    '''),
    "splitbill/report.py": lit('''
        """Plain-text report."""
        from .money import format_cents


        def render(balances, transfers, base="EUR"):
            """The report text: a line 'Balances (<base>):', then one line '  <name>: <amount>' per person sorted by
            name (format_cents, positive amounts with a leading '+', zero as '0.00'), a blank line, the line
            'Transfers:', then one line '  <debtor> -> <creditor>: <amount>' per transfer in order, or the single line
            '  nothing to settle'."""
            lines = [f"Balances ({base}):"]
            for name in sorted(balances):
                cents = balances[name]
                lines.append(f"  {name}: {'+' if cents > 0 else ''}{format_cents(cents)}")
            lines += ["", "Transfers:"]
            lines += [f"  {d} -> {c}: {format_cents(a)}" for d, c, a in transfers] or ["  nothing to settle"]
            return "\\n".join(lines)
    '''),
    "splitbill/cli.py": lit('''
        """Command line: python -m splitbill EXPENSES.csv [--base CUR] [--rates RATES.csv]"""
        import argparse
        import csv
        import sys
        from pathlib import Path

        from .csvio import read_expenses
        from .ledger import balances
        from .report import render
        from .settle import settle


        def read_rates(text):
            """RATES.csv has the header currency,per_eur (units of the currency per 1 EUR)."""
            return {r["currency"].strip().upper(): r["per_eur"].strip() for r in csv.DictReader(text.splitlines())}


        def main(argv=None):
            p = argparse.ArgumentParser(prog="splitbill")
            p.add_argument("expenses")
            p.add_argument("--base", default="EUR")
            p.add_argument("--rates")
            a = p.parse_args(argv)
            try:
                text = Path(a.expenses).read_text(encoding="utf-8")
                rates = read_rates(Path(a.rates).read_text(encoding="utf-8")) if a.rates else None
            except OSError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            try:
                bal = balances(read_expenses(text), a.base.upper(), rates)
            except (ValueError, KeyError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
            print(render(bal, settle(bal), a.base.upper()))
            return 0
    '''),
    "splitbill/__main__.py": lit('''
        import sys

        from .cli import main

        sys.exit(main())
    '''),
}

# (file, correct text, buggy text) — each must occur exactly once in the correct source.
SPLIT_BUGS = [
    # 1 parse_amount does not pad the fraction ("12.5" -> 1205)
    ("splitbill/money.py", "int((frac + \"00\")[:2])", "int(frac or 0)"),
    # 2 allocate: leftover-cent ties go to the LATER part
    ("splitbill/money.py", "key=lambda i: (-rema[i], i))", "key=lambda i: (-rema[i], -i))"),
    # 3+4 ledger signs inverted ... and settle reads them inverted too (end-to-end output stays right)
    ("splitbill/ledger.py", "bal.get(e.payer, 0) + amount", "bal.get(e.payer, 0) - amount"),
    ("splitbill/ledger.py", "bal[name] = bal.get(name, 0) - part", "bal[name] = bal.get(name, 0) + part"),
    ("splitbill/settle.py", "debts = {n: -b for n, b in balances.items() if b < 0}",
     "debts = {n: b for n, b in balances.items() if b > 0}"),
    ("splitbill/settle.py", "credits = {n: b for n, b in balances.items() if b > 0}",
     "credits = {n: -b for n, b in balances.items() if b < 0}"),
    # 5 csvio splits lines on commas itself (breaks quoted "1,234.56")
    ("splitbill/csvio.py", "rows = csv.reader(io.StringIO(text))",
     "rows = _Rows(text)"),
    ("splitbill/csvio.py", "HEADER = [\"id\", \"date\", \"payer\", \"amount\", \"currency\", \"participants\", \"weights\"]\n",
     "HEADER = [\"id\", \"date\", \"payer\", \"amount\", \"currency\", \"participants\", \"weights\"]\n\n\n"
     "class _Rows:\n"
     "    \"\"\"Iterate over the CSV rows of `text`, tracking the current line number.\"\"\"\n\n"
     "    def __init__(self, text):\n"
     "        self._lines = iter(text.splitlines())\n"
     "        self.line_num = 0\n\n"
     "    def __iter__(self):\n"
     "        return self\n\n"
     "    def __next__(self):\n"
     "        line = next(self._lines)\n"
     "        self.line_num += 1\n"
     "        return [f.strip('\"') for f in line.split(\",\")] if line.strip() else []\n"),
    # 6 (hidden) fx converts with floats and truncates instead of exact half-up rounding
    ("splitbill/fx.py", "value = Decimal(cents) * Decimal(str(rates[to_cur])) / Decimal(str(rates[from_cur]))\n"
                        "    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))",
     "return int(cents * float(rates[to_cur]) / float(rates[from_cur]))"),
]


def split_buggy() -> dict[str, str]:
    files = dict(SPLIT_OK)
    for rel, good, bad in SPLIT_BUGS:
        assert files[rel].count(good) == 1, (rel, good)
        files[rel] = files[rel].replace(good, bad)
    return files


SPLIT_TESTS = {
    "tests/test_money.py": lit('''
        import pytest
        from splitbill.money import allocate, format_cents, parse_amount


        @pytest.mark.parametrize("text,cents", [("12", 1200), ("12.5", 1250), ("12.50", 1250), (" 7.05 ", 705),
                                                ("1,234.56", 123456), ("0.99", 99)])
        def test_parse_amount(text, cents):
            assert parse_amount(text) == cents


        @pytest.mark.parametrize("bad", ["", "-1", "1.234", "1,23", "abc", "12,5"])
        def test_parse_amount_invalid(bad):
            with pytest.raises(ValueError):
                parse_amount(bad)


        def test_format_cents():
            assert [format_cents(c) for c in (1250, 5, 0, 123456)] == ["12.50", "0.05", "0.00", "1234.56"]


        def test_allocate_equal_three_ways():
            assert allocate(1000, [1, 1, 1]) == [334, 333, 333]


        def test_allocate_weighted():
            assert allocate(100, [1, 2]) == [33, 67]
            assert sum(allocate(9999, [3, 5, 7, 1])) == 9999
    '''),
    "tests/test_fx.py": lit('''
        from splitbill.fx import convert

        RATES = {"EUR": "1", "USD": "1.08", "GBP": "0.5"}


        def test_same_currency():
            assert convert(1234, "USD", "USD", RATES) == 1234


        def test_eur_to_usd():
            assert convert(1000, "EUR", "USD", RATES) == 1080


        def test_gbp_to_eur():
            assert convert(500, "GBP", "EUR", RATES) == 1000
    '''),
    "tests/test_split.py": lit('''
        import pytest
        from splitbill.models import Expense
        from splitbill.split import shares


        def test_equal_shares():
            e = Expense("e1", "2026-10-01", "ann", 1000, "EUR", ["ann", "bob", "cy"])
            assert shares(e) == {"ann": 334, "bob": 333, "cy": 333}


        def test_weighted_shares():
            e = Expense("e2", "2026-10-01", "bob", 9000, "EUR", ["ann", "bob"], [1, 2])
            assert shares(e) == {"ann": 3000, "bob": 6000}


        def test_duplicate_participant():
            with pytest.raises(ValueError):
                shares(Expense("e3", "2026-10-01", "ann", 100, "EUR", ["ann", "ann"]))
    '''),
    "tests/test_ledger.py": lit('''
        from splitbill.ledger import balances
        from splitbill.models import Expense


        def test_payer_is_owed():
            e = Expense("e1", "2026-10-01", "ann", 3000, "EUR", ["ann", "bob", "cy"])
            assert balances([e]) == {"ann": 2000, "bob": -1000, "cy": -1000}


        def test_balances_sum_to_zero():
            es = [Expense("e1", "2026-10-01", "ann", 1000, "EUR", ["ann", "bob", "cy"]),
                  Expense("e2", "2026-10-02", "bob", 4500, "EUR", ["ann", "bob"], [1, 2])]
            b = balances(es)
            assert sum(b.values()) == 0 and set(b) == {"ann", "bob", "cy"}
    '''),
    "tests/test_settle.py": lit('''
        from splitbill.settle import settle


        def test_single_creditor():
            assert settle({"ann": 500, "bob": -300, "cy": -200}) == [("bob", "ann", 300), ("cy", "ann", 200)]


        def test_nothing_to_settle():
            assert settle({"ann": 0, "bob": 0}) == []
    '''),
    "tests/test_csvio.py": lit('''
        from splitbill.csvio import read_expenses

        CSV = (
            "id,date,payer,amount,currency,participants,weights\\n"
            "e1,2026-10-01,ann,\\"1,234.56\\",eur,ann; bob ;cy,\\n"
            "\\n"
            "e2,2026-10-02,bob,30.00,EUR,ann;bob,1;2\\n"
        )


        def test_read_expenses():
            es = read_expenses(CSV)
            assert [(e.id, e.payer, e.amount, e.currency, e.participants, e.weights) for e in es] == [
                ("e1", "ann", 123456, "EUR", ["ann", "bob", "cy"], None),
                ("e2", "bob", 3000, "EUR", ["ann", "bob"], [1, 2]),
            ]
    '''),
    "tests/test_cli.py": lit('''
        import subprocess
        import sys
        from pathlib import Path

        ROOT = Path(__file__).resolve().parents[1]
        CSV = (
            "id,date,payer,amount,currency,participants,weights\\n"
            "e1,2026-10-01,ann,60.00,EUR,ann;bob;cy,\\n"
            "e2,2026-10-02,bob,30.00,EUR,bob;cy,\\n"
        )


        def run(*args):
            return subprocess.run([sys.executable, "-m", "splitbill", *args], cwd=ROOT, capture_output=True, text=True)


        def test_cli_report(tmp_path):
            f = tmp_path / "trip.csv"
            f.write_text(CSV)
            r = run(str(f))
            assert r.returncode == 0, r.stderr
            assert "  cy -> ann: 35.00" in r.stdout


        def test_cli_missing_file(tmp_path):
            r = run(str(tmp_path / "nope.csv"))
            assert r.returncode == 2 and "error" in r.stderr
    '''),
}
SPLIT_SETUP = {**split_buggy(), **SPLIT_TESTS, "conftest.py": "# makes the project root importable for pytest\n",
               "README.md": lit('''
                   # splitbill

                   Share group expenses and settle up. Amounts are integer cents everywhere; every function documents its
                   exact behaviour in its docstring (that is the specification).

                   ```
                   python -m splitbill EXPENSES.csv [--base EUR] [--rates RATES.csv]
                   ```
               ''')}

# unseen data for the hidden CLI check (foreign currencies -> exact rounding matters; uneven splits; ties)
SPLIT_HIDDEN_CSV = lit('''
    id,date,payer,amount,currency,participants,weights
    h1,2026-10-01,dora,100.05,USD,dora;emil;finn,
    h2,2026-10-02,emil,"1,000.00",SEK,dora;emil;finn;gus,1;1;1;2
    h3,2026-10-03,finn,10.5,EUR,emil;gus,
    h4,2026-10-04,gus,45.55,CHF,dora;finn,2;1
''')
SPLIT_HIDDEN_RATES = lit('''
    currency,per_eur
    EUR,1
    USD,1.08
    SEK,11.37
    CHF,0.94
''')


def _exec_split(files: dict[str, str], csv_text: str, rates: str) -> str:
    with tempfile.TemporaryDirectory() as d:
        for rel, text in files.items():
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        (Path(d) / "x.csv").write_text(csv_text, encoding="utf-8")
        (Path(d) / "r.csv").write_text(rates, encoding="utf-8")
        r = subprocess.run([sys.executable, "-m", "splitbill", "x.csv", "--rates", "r.csv"], cwd=d, capture_output=True,
                           text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        return r.stdout


SPLIT_HIDDEN_OUT = _exec_split(SPLIT_OK, SPLIT_HIDDEN_CSV, SPLIT_HIDDEN_RATES)


# =========================================================================== 03 data cleaning (shipments)
COUNTRIES = lit('''
    alias,code
    Germany,DE
    Deutschland,DE
    DE,DE
    DEU,DE
    France,FR
    FR,FR
    FRA,FR
    United States,US
    USA,US
    US,US
    U.S.A.,US
    United Kingdom,GB
    Great Britain,GB
    UK,GB
    GB,GB
    Netherlands,NL
    The Netherlands,NL
    NL,NL
    Austria,AT
    Österreich,AT
    AT,AT
    Canada,CA
    CA,CA
''')
NBSP, TAB = " ", "\t"

# Text of each file as the agent will see it after decoding (the setup command adds the BOM, re-encodes the US file
# as Windows-1252 and gives it CRLF line endings).
EU_MAIN = "\n".join([
    "Shipment ID;Date;Customer;Country;Weight (kg)",
    "EU-10001;3.9.2026;Anna Schmidt;Germany;12,5",
    f"eu 10002;15.09.2026;  Jan{TAB}de  Vries ;the netherlands;1.250",
    "EU-10003;31.09.2026;Pierre Martin;France;3,2",
    "EU-10004;20.09.2026;N/A;Germany;4",
    "EU-1005;21.09.2026;Lena Weber;Deutschland;2,0",
    f"EU-10006;22.09.2026;Lena{NBSP}Weber;DEU;2,0625",
    "EU-10007;23.09.2026;Marco Rossi;Italy;7,75",
    "EU-10008;24.09.2026;Sofie Jansen;NL;0",
    "",
    'EU-10009;25.9.2026;"Müller; Sons";Österreich;5,5',
    ";;;;",
    "EU-10010;26.09.2026;Eva Novak;AT;12.5",
    "EU-10011;27.09.2026;Tom Baker;UK;1.000,25",
    "EU-10012;2026-09-28;Ida Berg;Germany;3,3",
    "EU-10013;29.09.2026;Ole Lund;-;6,1",
    "EU-10014;30.09.2026;Kai Brandt;Germany;4,4;extra",
    "EU-10015;1.10.2026;Ruth  Klein;deutschland;0,4",
]) + "\n"
US_MAIN = "\n".join([
    "shipment_id,ship_date,customer_name,country,weight_lb",
    "US-20001,9/3/2026,Zoë Müller,USA,10",
    'US-20002,09/15/2026,"O’Brien, Pat",United States,"1,250.5"',
    "US-20003,13/01/2026,José Núñez,US,3",
    "US-20004,9/20/2026,François Dubois,Canada,0.5",
    "us20005,9/21/2026,  Ærø Hansen ,U.S.A.,2.25",
    "US-20006,9/22/2026,null,USA,4",
    "US-20007,9/23/2026,Bob Stone,USA,-3",
    "US-20008,9/24/2026,Li Wei,Mexico,8",
    "EU-10001,9/25/2026,Anna Schmidt,Germany,22",
    'US-20002,9/26/2026,"O’Brien, Pat",USA,abc',
    "US-20009,2/29/2026,Ann Lee,USA,5",
    "",
    "US-20010,9/30/2026,Ann Lee,usa,0.1",
]) + "\n"
WEB_MAIN = "\n".join([
    json.dumps({"id": "WB-30001", "created_at": "2026-09-30T23:30:00-05:00", "customer": "Zoë Adams", "country": "Canada", "weight": "500 g"}, ensure_ascii=False),
    json.dumps({"id": "WB-30002", "created_at": "2026-10-01T01:15:00+02:00", "customer": "Max Mustermann", "country": "DE", "weight": 2.5}),
    json.dumps({"id": "WB-30003", "created_at": "2026-10-02T10:00:00Z", "customer": "Ivy Chen", "country": "US", "weight": "3lb"}),
    "not json at all",
    json.dumps({"id": "WB-30004", "created_at": "2026-10-02 10:00:00", "customer": "Omar Haddad", "country": "FR", "weight": "1 kg"}),
    json.dumps({"id": "WB-30005", "created_at": "2026-10-03T08:00:00Z", "customer": "  ", "country": "FR", "weight": "1kg"}),
    json.dumps({"id": "WB-30006", "created_at": "2026-10-03T09:00:00Z", "customer": "Noah Kim", "country": "France", "weight": "2.5"}),
    json.dumps(["WB-30007"]),
    json.dumps({"id": "eu-10015", "created_at": "2026-10-04T12:00:00+01:00", "customer": "Ruth Klein", "country": "Austria", "weight": "2.1 KG"}),
    "   ",
    json.dumps({"id": "WB-30008", "created_at": "2026-10-05T00:30:00+03:00", "customer": "Emma\tStone", "country": "GB", "weight": 1.0005}),
    json.dumps({"id": 30009, "created_at": "2026-10-05T10:00:00Z", "customer": "Ben Ali", "country": "FR", "weight": "1 kg"}),
    json.dumps({"id": "WB-30010", "created_at": "2026-10-06T10:00:00Z", "customer": "Liam O'Neil", "country": "uk", "weight": "0 kg"}),
    json.dumps({"id": "WB-30011", "created_at": "2026-10-06T11:00:00Z", "customer": "Mia Wong", "country": None, "weight": "750g"}),
]) + "\n"

# next month's exports (only used by the hidden re-run check)
EU_V2 = "\n".join([
    "Shipment ID;Date;Customer;Country;Weight (kg)",
    "EU-40001;1.10.2026;Hanna Vogel;Germany;1.500,75",
    f"EU-40002;2.10.2026;Felix{NBSP}{NBSP}Wolf;France;0,0005",
    "EU-40003;29.2.2028;Greta Lang;AT;3",
    "EU-40004;30.02.2026;Paul Roth;AT;3",
    "EU-40005;4.10.2026;none;Germany;1",
    'EU-40006;5.10.2026;"Bauer; Kinder";great britain;2,25',
    "eu-4 0007;6.10.2026;Mila Horn;NL;7,000",
    "EU-40008;7.10.2026;Nina Kraft;Belgium;1",
    "EU-40009;8.10.2026;Otto Fink;Germany;",
    "EU-40010;9.10.2026;Pia Graf;Germany;12,5;",
    "   ",
    "EU-40011;10.10.2026;Rosa Brand;FRA;9,9995",
    "EU-40012;11.10.2026;Ben Ott;Germany;1",
]) + "\n"
US_V2 = "\n".join([
    "shipment_id,ship_date,customer_name,country,weight_lb",
    "US-50001,10/1/2026,Chloé Martin,USA,1",
    'US-50002,10/02/2026,"Smith – Jones, Sam",United States,"2,000"',
    "US-50003,10/3/2026,Dana Scully,Canada,0",
    "EU-40012,10/4/2026,Ben Ott,France,3.5",
    "US-50004,10/32/2026,Fox Mulder,USA,2",
    "US-50005,10/5/2026,N/A,USA,2",
    "US-50006,10/6/2026,Walter Skinner,US,12.25.1",
    "US-50001,10/7/2026,Chloé  Martin,usa,1.5",
    "US-5007,10/8/2026,Monica Reyes,USA,4",
]) + "\n"
WEB_V2 = "\n".join([
    json.dumps({"id": "WB-60001", "created_at": "2026-10-09T20:00:00-04:00", "customer": "Ama Owusu", "country": "Canada", "weight": "1,5 kg"}),
    json.dumps({"id": "WB-60002", "created_at": "2026-10-10T03:00:00+05:30", "customer": "Ravi Shah", "country": "GB", "weight": "1500 G"}),
    json.dumps({"id": "WB-60003", "created_at": "2026-10-11T12:00:00Z", "customer": "Café Olé", "country": "FR", "weight": 0.25}),
    "{\"id\": \"WB-60004\", \"created_at\": ",
    json.dumps({"id": "US-50003", "created_at": "2026-10-12T09:00:00Z", "customer": "Dana Scully", "country": "CA", "weight": "2 lb"}),
    json.dumps({"id": "WB-60005", "created_at": "2026-10-12T25:00:00Z", "customer": "Late Night", "country": "US", "weight": "1 kg"}),
    json.dumps({"id": "WB-60006", "created_at": "2026-10-13T08:00:00Z", "customer": None, "country": "US", "weight": "1 kg"}),
    json.dumps({"id": "WB-60007", "created_at": "2026-10-13T09:00:00Z", "customer": "Yuki Sato", "country": "Japan", "weight": "1 kg"}),
    json.dumps({"id": "WB-60008", "created_at": "2026-10-14T23:59:59-00:30", "customer": "Edge Case", "country": "NL", "weight": True}),
    json.dumps({"id": "WB-60009", "created_at": "2026-10-14T23:59:59-00:30", "customer": "Edge Case", "country": "NL", "weight": 10}),
    json.dumps({}),
]) + "\n"


def ship_bytes(eu: str, us: str, web: str) -> dict[str, bytes]:
    """The raw files exactly as stored on disk."""
    return {"eu_shipments.csv": b"\xef\xbb\xbf" + eu.encode("utf-8"),
            "us_shipments.csv": us.replace("\n", "\r\n").encode("cp1252"),
            "web_shipments.jsonl": web.encode("utf-8"),
            "countries.csv": COUNTRIES.encode("utf-8")}


def run_clean(eu: str, us: str, web: str) -> dict[str, str]:
    from hard_refs import CLEAN

    with tempfile.TemporaryDirectory() as d:
        raw = Path(d) / "raw"
        raw.mkdir()
        for name, data in ship_bytes(eu, us, web).items():
            (raw / name).write_bytes(data)
        (Path(d) / "clean.py").write_text(CLEAN, encoding="utf-8")
        subprocess.run([sys.executable, "clean.py"], cwd=d, check=True, timeout=60)
        return {n: (Path(d) / "out" / n).read_text(encoding="utf-8") for n in ("shipments.csv", "rejects.csv", "summary.json")}


SHIP_MAIN = run_clean(EU_MAIN, US_MAIN, WEB_MAIN)
SHIP_V2 = run_clean(EU_V2, US_V2, WEB_V2)


# =========================================================================== 06 HITL: commission payout
DEALS = lit('''
    deal_id,rep_id,rep_name,closed_on,amount_eur,status
    D-7001,E1007,Zoë Laurent,2026-07-02,18250.00,won
    D-7002,E1003,Marcus Bell,2026-07-03,42000.00,won
    D-7003,E1021,Jürgen Weiß,2026-06-30,55000.00,won
    D-7004,E1007,Zoë Laurent,2026-07-11,61400.50,won
    D-7005,E1015,Priya Nair,2026-07-15,9800.00,lost
    D-7006,E1003,Marcus Bell,2026-07-21,38500.00,won
    D-7007,E1012,Sven Olsen,2026-07-28,23999.99,won
    D-7008,E1007,Zoë Laurent,2026-08-04,27300.00,refunded
    D-7009,E1021,Jürgen Weiß,2026-08-09,31250.00,won
    D-7010,E1003,Marcus Bell,2026-08-12,19500.00,won
    D-7011,E1030,Ana Souza,2026-08-15,12000.00,disputed
    D-7012,E1012,Sven Olsen,2026-08-19,47000.00,won
    D-7013,E1007,Zoë Laurent,2026-08-27,35675.25,won
    D-7014,E1015,Priya Nair,2026-09-01,15000.00,lost
    D-7015,E1003,Marcus Bell,2026-09-08,22040.40,won
    D-7016,E1012,Sven Olsen,2026-09-12,29000.01,won
    D-7017,E1021,Jürgen Weiß,2026-09-18,8999.50,won
    D-7018,E1030,Ana Souza,2026-09-22,40000.00,won
    D-7019,E1007,Zoë Laurent,2026-09-29,4120.00,won
    D-7020,E1003,Marcus Bell,2026-09-30,1999.99,won
    D-7021,E1012,Sven Olsen,2026-10-01,15000.00,won
    D-7022,E1030,Ana Souza,2026-09-30,6250.00,refunded
    D-7023,E1015,Priya Nair,2026-10-02,72000.00,won
''')
PLAN_2025 = lit('''
    # Sales commission plan 2025

    > **SUPERSEDED.** This plan applied to deals closed in 2025 only. The 2026 plan has a different base rate and a
    > different accelerator; Finance (whoever requests the payout run) has the current numbers.

    - Base: 4% of every won deal.
    - Accelerator: 6% instead of 4% on the part of a rep's quarterly won total above 150,000 EUR.
    - Payroll file (2025 importer, retired): `rep_id,amount` — comma-separated, decimal point.
''')
PAYOUT_PLAN_REPLY = ("The 2026 plan: a rep earns 5% on the first 100,000.00 EUR of their quarterly won total and 8% on "
                     "the part above 100,000.00 EUR. Only deals with status `won` and a `closed_on` date inside the "
                     "quarter (Q3 = 2026-07-01 to 2026-09-30, both inclusive) count; lost, refunded and disputed deals "
                     "earn nothing. Compute per rep on the quarter's won total and round half up to cents once, at the "
                     "end.")
PAYOUT_FORMAT_REPLY = ("The payroll importer wants a UTF-8 text file, semicolon-separated, with exactly this header: "
                       "`employee_id;name;commission_eur`. One row per rep whose commission is above zero, sorted by "
                       "employee_id ascending; `employee_id` is the rep_id and `name` the rep_name exactly as in the deals "
                       "file. Amounts have exactly two decimals and a comma as decimal separator, no thousands separator "
                       "(e.g. `5234,50`). No quoting, `\\n` line endings. After the reps one last line "
                       "`TOTAL;;<sum of all rows>` in the same number format.")
_FMT_WORDS = r"format|layout|columns?|headers?|delimit\w*|separator|decimal (separator|comma|point|mark)|importer|look like"
_PLAN_WORDS = r"plan\b|rates?\b|percent|%|tiers?\b|threshold|accelerat\w*|polic(y|ies)|bonus|scheme|commission (model|rules?|structure)"
# The simulated user answers one topic per question. Rules look at the question text up to the first "?" (the
# `context` the agent adds after it often mentions the other topic); a request mixing both topics gets the plan
# plus the instruction to ask about the format on its own.
PAYOUT_HITL = {
    "replies": [
        {"match": rf"(?i)^(?=[^?]*\b({_FMT_WORDS}))(?![^?]*({_PLAN_WORDS}))", "reply": PAYOUT_FORMAT_REPLY},
        {"match": rf"(?i)^(?=[^?]*({_PLAN_WORDS}))(?![^?]*\b({_FMT_WORDS}))", "reply": PAYOUT_PLAN_REPLY},
        {"match": rf"(?is)^(?=.*({_PLAN_WORDS}))",
         "reply": PAYOUT_PLAN_REPLY + " (I answer one topic per question — if you also need the payroll file format, "
                                      "ask me that in a separate question about the format alone.)"},
        {"match": rf"(?i)\b({_FMT_WORDS})", "reply": PAYOUT_FORMAT_REPLY},
    ],
    "default_reply": "I'm not sure what you need from me — please ask one specific question at a time.",
    "approvals": "approve",
}


def payout_rows(deals_csv: str, base: str = "0.05", top: str = "0.08", threshold: str = "100000",
                start: str = "2026-07-01", end: str = "2026-09-30") -> list[tuple[str, str, Decimal]]:
    won: dict[str, Decimal] = {}
    names: dict[str, str] = {}
    for r in csv.DictReader(io.StringIO(deals_csv)):
        names[r["rep_id"]] = r["rep_name"]
        if r["status"] == "won" and start <= r["closed_on"] <= end:
            won[r["rep_id"]] = won.get(r["rep_id"], Decimal(0)) + Decimal(r["amount_eur"])
    out = []
    for rep, w in sorted(won.items()):
        t = Decimal(threshold)
        c = (Decimal(base) * min(w, t) + Decimal(top) * max(w - t, Decimal(0))).quantize(Decimal("0.01"), ROUND_HALF_UP)
        if c > 0:
            out.append((rep, names[rep], c))
    return out


def payout_file(rows) -> str:
    fmt = lambda d: f"{d:.2f}".replace(".", ",")
    lines = ["employee_id;name;commission_eur"] + [f"{r};{n};{fmt(c)}" for r, n, c in rows]
    lines.append(f"TOTAL;;{fmt(sum(c for _, _, c in rows))}")
    return "\n".join(lines) + "\n"


PAYOUT_ROWS = payout_rows(DEALS)
PAYOUT_EXPECTED = payout_file(PAYOUT_ROWS)
# what an agent that used the superseded 2025 plan would produce
PAYOUT_2025 = payout_file(payout_rows(DEALS, base="0.04", top="0.06", threshold="150000"))
assert PAYOUT_EXPECTED != PAYOUT_2025


# =========================================================================== 07 cross-agent knowledge: quotes
def _price_list(rows) -> str:
    return "sku,name,unit_price_eur,status,replaced_by\n" + "".join(
        f"{s},{n},{p},{st},{rb}\n" for s, n, p, st, rb in rows)


_CATALOG = [
    ("CAM-X200", "Action camera X200", "249.00", "discontinued", "CAM-X210"),
    ("CAM-X210", "Action camera X210", "279.90", "active", ""),
    ("CAM-P50", "Pocket camera P50", "159.00", "active", ""),
    ("LEN-W18", "Wide lens 18mm", "189.50", "active", ""),
    ("LEN-T85", "Tele lens 85mm", "349.00", "active", ""),
    ("LEN-M60", "Macro lens 60mm", "299.00", "discontinued", "LEN-M65"),
    ("LEN-M65", "Macro lens 65mm", "319.00", "active", ""),
    ("BAT-AA8", "AA battery 8-pack", "6.49", "active", ""),
    ("BAT-LI2", "Li-ion battery pack", "39.90", "active", ""),
    ("CHG-DUO", "Dual charger", "29.95", "active", ""),
    ("CAB-USB3", "USB-C cable 1m", "7.80", "active", ""),
    ("CAB-HDM2", "HDMI cable 2m", "12.40", "active", ""),
    ("MEM-128", "SD card 128GB", "24.99", "active", ""),
    ("MEM-256", "SD card 256GB", "41.50", "active", ""),
    ("MEM-064", "SD card 64GB", "14.00", "discontinued", "MEM-128"),
    ("TRI-CF1", "Carbon tripod", "129.00", "active", ""),
    ("TRI-MINI", "Mini tripod", "19.90", "active", ""),
    ("BAG-S", "Camera bag S", "34.00", "active", ""),
    ("BAG-L", "Camera bag L", "59.00", "active", ""),
    ("FLT-UV58", "UV filter 58mm", "17.25", "active", ""),
    ("FLT-ND58", "ND filter 58mm", "36.75", "active", ""),
    ("MIC-SHO", "Shotgun microphone", "89.00", "active", ""),
    ("MIC-LAV", "Lavalier microphone", "24.50", "active", ""),
    ("LGT-P60", "LED panel 60", "74.90", "active", ""),
    ("LGT-RING", "Ring light", "49.00", "active", ""),
    ("GMB-3X", "3-axis gimbal", "219.00", "active", ""),
    ("STR-NECK", "Neck strap", "11.90", "active", ""),
    ("CLN-KIT", "Cleaning kit", "9.95", "active", ""),
    ("HUB-4P", "USB hub 4-port", "22.00", "active", ""),
    ("RMT-BT", "Bluetooth remote", "15.60", "active", ""),
    ("CAS-HARD", "Hard case", "99.00", "active", ""),
    ("SCR-GLS", "Screen protector", "8.40", "active", ""),
    ("ADP-M43", "Lens adapter M43", "64.00", "active", ""),
    ("HDL-GRIP", "Handle grip", "27.30", "active", ""),
    ("WLT-SD", "SD card wallet", "12.95", "active", ""),
    ("DRY-BOX", "Dry box", "45.00", "active", ""),
]
PRICE_Q4 = _price_list(_CATALOG)
# last quarter's list: different prices, no replacements yet (a stale distractor in the owner's workspace)
PRICE_Q3 = _price_list([(s, n, f"{(Decimal(p) * Decimal('0.93')).quantize(Decimal('0.01'), ROUND_HALF_UP)}", "active", "")
                        for s, n, p, st, rb in _CATALOG])
PRICING_RULES = lit('''
    # Pricing rules — Q4 2026 (valid 2026-10-01 to 2026-12-31)

    Use only `price_list_2026Q4.csv` for Q4 quotes (the Q3 list is kept for reference).

    1. Discontinued SKUs (`status` = discontinued) are quoted as their `replaced_by` SKU, same quantity, at the
       replacement's price.
    2. Line amount = quantity × unit price. Volume discount per line, by the line's quantity:
       10–19 → 3%, 20–49 → 6%, 50 or more → 10%. The discounted line amount is rounded half up to cents.
    3. Merchandise value = sum of the discounted lines. Customer tier discount on the merchandise value:
       bronze 0%, silver 2%, gold 4%, platinum 7%; the tier discount amount is rounded half up to cents.
    4. Net merchandise value = merchandise value − tier discount.
    5. Shipping by destination country: DE 5.90; AT, BE, FR, LU, NL 12.50; CH, GB, NO 24.00; everywhere else 39.00.
       Shipping is free when the net merchandise value is 750.00 or more.
    6. On a quote: subtotal = sum of the undiscounted line amounts (after rule 1); discount = subtotal − net
       merchandise value; total = net merchandise value + shipping. All amounts in EUR with two decimals.
''')
ORDERS = [
    {"order_id": "ORD-3001", "customer": "Nordlicht GmbH", "customer_tier": "gold", "ship_to": "DE",
     "lines": [{"sku": "CAB-USB3", "qty": 12}, {"sku": "CAM-X200", "qty": 1}, {"sku": "BAT-AA8", "qty": 25},
               {"sku": "FLT-UV58", "qty": 3}]},
    {"order_id": "ORD-3002", "customer": "Café Lumière SARL", "customer_tier": "silver", "ship_to": "FR",
     "lines": [{"sku": "MIC-LAV", "qty": 2}, {"sku": "LEN-M60", "qty": 1}, {"sku": "MEM-064", "qty": 10},
               {"sku": "CLN-KIT", "qty": 1}]},
    {"order_id": "ORD-3003", "customer": "Polar Outfitters AS", "customer_tier": "platinum", "ship_to": "NO",
     "lines": [{"sku": "STR-NECK", "qty": 60}, {"sku": "DRY-BOX", "qty": 4}, {"sku": "SCR-GLS", "qty": 18},
               {"sku": "GMB-3X", "qty": 1}]},
]


def quote(order, price_csv=PRICE_Q4, *, replacements=True, volume=True, tier=True) -> dict:
    cents = Decimal("0.01")
    plist = {r["sku"]: r for r in csv.DictReader(io.StringIO(price_csv))}
    subtotal = merch = Decimal(0)
    for line in order["lines"]:
        item = plist[line["sku"]]
        if replacements and item["status"] == "discontinued":
            item = plist[item["replaced_by"]]
        gross = Decimal(item["unit_price_eur"]) * line["qty"]
        q = line["qty"]
        pct = Decimal("0.10") if q >= 50 else Decimal("0.06") if q >= 20 else Decimal("0.03") if q >= 10 else Decimal(0)
        if not volume:
            pct = Decimal(0)
        subtotal += gross
        merch += (gross * (1 - pct)).quantize(cents, ROUND_HALF_UP)
    rate = {"bronze": "0", "silver": "0.02", "gold": "0.04", "platinum": "0.07"}[order["customer_tier"]] if tier else "0"
    tier_disc = (merch * Decimal(rate)).quantize(cents, ROUND_HALF_UP)
    net = merch - tier_disc
    zone = order["ship_to"]
    ship = (Decimal("5.90") if zone == "DE" else Decimal("12.50") if zone in {"AT", "BE", "FR", "LU", "NL"}
            else Decimal("24.00") if zone in {"CH", "GB", "NO"} else Decimal("39.00"))
    if net >= Decimal("750.00"):
        ship = Decimal(0)
    return {"order_id": order["order_id"], "customer": order["customer"], "subtotal": f"{subtotal:.2f}",
            "discount": f"{subtotal - net:.2f}", "shipping": f"{ship:.2f}", "total": f"{net + ship:.2f}"}


QUOTES = [quote(o) for o in ORDERS]
QUOTES_STALE = [quote(o, PRICE_Q3, replacements=False) for o in ORDERS]
QUOTES_NO_RULES = [quote(o, replacements=False, volume=False) for o in ORDERS]
assert QUOTES != QUOTES_STALE and QUOTES != QUOTES_NO_RULES
# both free-shipping branches and every volume tier are exercised
assert {q["shipping"] for q in QUOTES} >= {"0.00"} and len({q["shipping"] for q in QUOTES}) >= 2


def quotes_csv(quotes) -> str:
    keys = ["order_id", "customer", "subtotal", "discount", "shipping", "total"]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(keys)
    for q in sorted(quotes, key=lambda q: q["order_id"]):
        w.writerow([q[k] for k in keys])
    return buf.getvalue()


# =========================================================================== 08 git merge conflict
GIT_BASE = {
    "store/.gitignore": "__pycache__/\n.pytest_cache/\n",
    "store/conftest.py": "# makes the project root importable for pytest\n",
    "store/shop/__init__.py": '"""Tiny shop library."""\n',
    "store/shop/pricing.py": lit('''
        """Price calculations."""
        from decimal import ROUND_HALF_UP, Decimal

        VAT = {"DE": Decimal("0.19"), "FR": Decimal("0.20"), "NL": Decimal("0.21")}


        def calc_total(items, country="DE"):
            """Gross total of `items` — (unit_price, qty) pairs, prices as strings — including the VAT of `country`,
            rounded half up to cents."""
            net = sum((Decimal(price) * qty for price, qty in items), Decimal(0))
            gross = net * (1 + VAT[country])
            return gross.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    '''),
    "store/tests/test_pricing.py": lit('''
        from decimal import Decimal

        from shop.pricing import calc_total


        def test_total_de():
            assert calc_total([("10.00", 2), ("5.00", 1)]) == Decimal("29.75")


        def test_total_fr():
            assert calc_total([("10.00", 1)], "FR") == Decimal("12.00")
    '''),
    "store/CHANGELOG.md": lit('''
        # Changelog

        ## Unreleased

        ## 1.2.0

        - Pricing module with VAT for DE, FR and NL.
    '''),
    "store/config.json": lit('''
        {
          "name": "shop",
          "version": "1.2.0",
          "default_country": "DE",
          "rounding": "half-up"
        }
    '''),
}
# each step: files (relative to store/) written on top of the previous state, then committed
GIT_MAIN_STEPS = [
    ("refactor: rename calc_total to compute_total, add currency", {
        "shop/pricing.py": lit('''
            """Price calculations."""
            from decimal import ROUND_HALF_UP, Decimal

            VAT = {"DE": Decimal("0.19"), "FR": Decimal("0.20"), "NL": Decimal("0.21")}
            FX = {"EUR": Decimal("1"), "USD": Decimal("1.08"), "GBP": Decimal("0.86")}


            def compute_total(items, country="DE", *, currency="EUR"):
                """Gross total of `items` — (unit_price, qty) pairs, prices in EUR as strings — including the VAT of
                `country`, converted to `currency` (FX = units per EUR) and rounded half up to cents once, at the end."""
                net = sum((Decimal(price) * qty for price, qty in items), Decimal(0))
                gross = net * (1 + VAT[country]) * FX[currency]
                return gross.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        '''),
        "tests/test_pricing.py": lit('''
            from decimal import Decimal

            from shop.pricing import compute_total


            def test_total_de():
                assert compute_total([("10.00", 2), ("5.00", 1)]) == Decimal("29.75")


            def test_total_fr():
                assert compute_total([("10.00", 1)], "FR") == Decimal("12.00")


            def test_currency():
                assert compute_total([("10.00", 1)], "DE", currency="USD") == Decimal("12.85")
        '''),
        "CHANGELOG.md": lit('''
            # Changelog

            ## Unreleased

            - Renamed `calc_total` to `compute_total`.
            - New keyword-only `currency` argument (EUR, USD, GBP).

            ## 1.2.0

            - Pricing module with VAT for DE, FR and NL.
        '''),
        "config.json": lit('''
            {
              "name": "shop",
              "version": "1.2.1",
              "default_country": "DE",
              "rounding": "half-up",
              "currencies": ["EUR", "USD", "GBP"]
            }
        '''),
    }),
    ("feat: VAT for Austria", {
        "shop/pricing.py": None,  # patched below: AT added to VAT
        "tests/test_pricing.py": None,
        "CHANGELOG.md": lit('''
            # Changelog

            ## Unreleased

            - Renamed `calc_total` to `compute_total`.
            - New keyword-only `currency` argument (EUR, USD, GBP).
            - VAT for Austria (AT).

            ## 1.2.0

            - Pricing module with VAT for DE, FR and NL.
        '''),
        "config.json": lit('''
            {
              "name": "shop",
              "version": "1.2.1",
              "default_country": "DE",
              "rounding": "half-up",
              "currencies": ["EUR", "USD", "GBP"],
              "countries": ["DE", "FR", "NL", "AT"]
            }
        '''),
    }),
]
_m1 = GIT_MAIN_STEPS[0][1]
GIT_MAIN_STEPS[1][1]["shop/pricing.py"] = _m1["shop/pricing.py"].replace(
    '"NL": Decimal("0.21")}', '"NL": Decimal("0.21"), "AT": Decimal("0.20")}')
GIT_MAIN_STEPS[1][1]["tests/test_pricing.py"] = _m1["tests/test_pricing.py"] + lit('''


    def test_total_at():
        assert compute_total([("10.00", 3)], "AT") == Decimal("36.00")
''')
GIT_FEATURE_STEPS = [
    ("feat: customer tiers with a discount before VAT", {
        "shop/pricing.py": lit('''
            """Price calculations."""
            from decimal import ROUND_HALF_UP, Decimal

            VAT = {"DE": Decimal("0.19"), "FR": Decimal("0.20"), "NL": Decimal("0.21")}
            TIERS = {"silver": Decimal("0.03"), "gold": Decimal("0.05"), "platinum": Decimal("0.08")}


            def calc_total(items, country="DE", tier=None):
                """Gross total of `items` — (unit_price, qty) pairs, prices as strings — including the VAT of `country`,
                rounded half up to cents. A customer `tier` ("silver", "gold", "platinum") gets its discount on the net
                amount, before VAT."""
                net = sum((Decimal(price) * qty for price, qty in items), Decimal(0))
                if tier is not None:
                    net = net * (1 - TIERS[tier])
                gross = net * (1 + VAT[country])
                return gross.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        '''),
        "tests/test_pricing.py": lit('''
            from decimal import Decimal

            import pytest
            from shop.pricing import calc_total


            def test_total_de():
                assert calc_total([("10.00", 2), ("5.00", 1)]) == Decimal("29.75")


            def test_total_fr():
                assert calc_total([("10.00", 1)], "FR") == Decimal("12.00")


            def test_gold_tier():
                assert calc_total([("100.00", 1)], "DE", tier="gold") == Decimal("113.05")


            def test_unknown_tier():
                with pytest.raises(KeyError):
                    calc_total([("1.00", 1)], tier="diamond")
        '''),
        "CHANGELOG.md": lit('''
            # Changelog

            ## Unreleased

            - Customer tiers (silver, gold, platinum) with a discount before VAT.

            ## 1.2.0

            - Pricing module with VAT for DE, FR and NL.
        '''),
        "config.json": lit('''
            {
              "name": "shop",
              "version": "1.3.0-dev",
              "default_country": "DE",
              "rounding": "half-up",
              "tiers": {"silver": 3, "gold": 5, "platinum": 8}
            }
        '''),
    }),
    ("feat: Cart helper", {
        "shop/cart.py": lit('''
            """Shopping cart."""
            from .pricing import calc_total


            class Cart:
                def __init__(self, country="DE", tier=None):
                    self.country = country
                    self.tier = tier
                    self.items = []

                def add(self, price, qty=1):
                    if qty <= 0:
                        raise ValueError("qty must be positive")
                    self.items.append((price, qty))
                    return self

                def total(self):
                    return calc_total(self.items, self.country, tier=self.tier)
        '''),
        "tests/test_cart.py": lit('''
            from decimal import Decimal

            from shop.cart import Cart


            def test_cart_total():
                assert Cart("FR", tier="silver").add("20.00", 3).total() == Decimal("69.84")
        '''),
        "CHANGELOG.md": lit('''
            # Changelog

            ## Unreleased

            - Customer tiers (silver, gold, platinum) with a discount before VAT.
            - `Cart` helper (`shop.cart`).

            ## 1.2.0

            - Pricing module with VAT for DE, FR and NL.
        '''),
    }),
]


def _tip(steps) -> dict[str, str]:
    files = {k[len("store/"):]: v for k, v in GIT_BASE.items()}
    for _, changes in steps:
        files.update(changes)
    return files


GIT_MAIN_TIP = _tip(GIT_MAIN_STEPS)
GIT_FEATURE_TIP = _tip(GIT_FEATURE_STEPS)
GIT_SETUP_FILES = dict(GIT_BASE)
for _i, (_msg, _changes) in enumerate(GIT_MAIN_STEPS, 1):
    GIT_SETUP_FILES.update({f"_stage/main{_i}/{k}": v for k, v in _changes.items()})
for _i, (_msg, _changes) in enumerate(GIT_FEATURE_STEPS, 1):
    GIT_SETUP_FILES.update({f"_stage/feature{_i}/{k}": v for k, v in _changes.items()})


def _commit_cmd(stage: str, msg: str) -> str:
    return f"cp -R ../_stage/{stage}/. . && git add -A && git commit -qm '{msg}'"


GIT_SETUP_COMMANDS = [
    "cd store && git init -q -b main && git add -A && git commit -qm 'chore: pricing module 1.2.0'",
    "cd store && git checkout -q -b feature/tiered-discounts && "
    + " && ".join(_commit_cmd(f"feature{i}", m) for i, (m, _) in enumerate(GIT_FEATURE_STEPS, 1)),
    "cd store && git checkout -q main && "
    + " && ".join(_commit_cmd(f"main{i}", m) for i, (m, _) in enumerate(GIT_MAIN_STEPS, 1)),
    "rm -rf _stage",
]

# the correctly resolved files (what the merge commit must contain)
GIT_RESOLVED = {
    "shop/pricing.py": lit('''
        """Price calculations."""
        from decimal import ROUND_HALF_UP, Decimal

        VAT = {"DE": Decimal("0.19"), "FR": Decimal("0.20"), "NL": Decimal("0.21"), "AT": Decimal("0.20")}
        FX = {"EUR": Decimal("1"), "USD": Decimal("1.08"), "GBP": Decimal("0.86")}
        TIERS = {"silver": Decimal("0.03"), "gold": Decimal("0.05"), "platinum": Decimal("0.08")}


        def compute_total(items, country="DE", *, tier=None, currency="EUR"):
            """Gross total of `items` — (unit_price, qty) pairs, prices in EUR as strings: net amount, minus the
            discount of the customer `tier` ("silver", "gold", "platinum"), plus the VAT of `country`, converted to
            `currency` (FX = units per EUR) and rounded half up to cents once, at the end."""
            net = sum((Decimal(price) * qty for price, qty in items), Decimal(0))
            if tier is not None:
                net = net * (1 - TIERS[tier])
            gross = net * (1 + VAT[country]) * FX[currency]
            return gross.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    '''),
    "shop/cart.py": GIT_FEATURE_TIP["shop/cart.py"].replace("calc_total", "compute_total"),
    "tests/test_pricing.py": lit('''
        from decimal import Decimal

        import pytest
        from shop.pricing import compute_total


        def test_total_de():
            assert compute_total([("10.00", 2), ("5.00", 1)]) == Decimal("29.75")


        def test_total_fr():
            assert compute_total([("10.00", 1)], "FR") == Decimal("12.00")


        def test_currency():
            assert compute_total([("10.00", 1)], "DE", currency="USD") == Decimal("12.85")


        def test_total_at():
            assert compute_total([("10.00", 3)], "AT") == Decimal("36.00")


        def test_gold_tier():
            assert compute_total([("100.00", 1)], "DE", tier="gold") == Decimal("113.05")


        def test_unknown_tier():
            with pytest.raises(KeyError):
                compute_total([("1.00", 1)], tier="diamond")
    '''),
    "CHANGELOG.md": lit('''
        # Changelog

        ## Unreleased

        - Renamed `calc_total` to `compute_total`.
        - New keyword-only `currency` argument (EUR, USD, GBP).
        - VAT for Austria (AT).
        - Customer tiers (silver, gold, platinum) with a discount before VAT.
        - `Cart` helper (`shop.cart`).

        ## 1.2.0

        - Pricing module with VAT for DE, FR and NL.
    '''),
    "config.json": json.dumps({"name": "shop", "version": "1.3.0", "default_country": "DE", "rounding": "half-up",
                               "currencies": ["EUR", "USD", "GBP"], "countries": ["DE", "FR", "NL", "AT"],
                               "tiers": {"silver": 3, "gold": 5, "platinum": 8}}, indent=2) + "\n",
}
GIT_CONFIG_EXPECTED = json.loads(GIT_RESOLVED["config.json"])
GIT_CHANGELOG_LINES = [l for l in GIT_RESOLVED["CHANGELOG.md"].splitlines() if l.strip()]


def _exec_pricing():
    ns: dict = {}
    exec(GIT_RESOLVED["shop/pricing.py"], ns)
    return ns["compute_total"]


_ct = _exec_pricing()
GIT_PRICING_CASES = [
    (([("19.99", 3), ("5.00", 2)], "AT"), {"tier": "platinum", "currency": "GBP"}),
    (([("100.00", 1)], "DE"), {"tier": "gold"}),
    (([("0.99", 7)], "NL"), {"currency": "USD"}),
    (([("12.34", 5), ("0.01", 1)], "FR"), {"tier": "silver", "currency": "USD"}),
    (([("250.00", 2)],), {}),
    (([("3.33", 3)], "DE"), {"tier": None, "currency": "EUR"}),
]
GIT_PRICING_EXPECTED = [str(_ct(*a, **k)) for a, k in GIT_PRICING_CASES]
