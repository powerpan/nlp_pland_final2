"""The web UI's interface translations (pland/server/static/i18n/*.json) stay complete and consistent with app.js.

Pure Python, no network or Node: the English source strings are collected from the `t('…')` and
`plural(n, '…', '…')` calls in app.js and from the `data-i18n` elements of index.html.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "pland" / "server" / "static"
APP_JS = STATIC / "app.js"
INDEX = STATIC / "index.html"
ZH = STATIC / "i18n" / "zh-Hant.json"

# Strings that are the same in Traditional Chinese on purpose (product names, terms kept in English by the docs).
SAME_IN_ZH = {"Agent", "Bridge", "macOS Seatbelt"}

# The t() calls that pass a key along instead of naming one: plural() (its two literals are collected) and the
# translation of index.html's data-i18n elements (collected from index.html).
DYNAMIC_CALLS = ("t(n === 1 ? one : many", "t(el.textContent)", "t(el.getAttribute(what))")

# Characters that exist only in Simplified Chinese (their Traditional forms are used instead).
SIMPLIFIED_ONLY = set("设认软这们为时间说请输选择显开关闭发现对话应运务删项条览页编辑码储获计执个网络连历记忆经验组队长区级")

_LIT = r"""'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"|`(?:[^`\\$]|\\.)*`"""
_T_CALL = re.compile(r"(?<![\w$.])t\(\s*(" + _LIT + r")")
_T_ANY = re.compile(r"(?<![\w$.])t\(")
_PLURAL = re.compile(r"(?<![\w$.])plural\([^'\"`;]*?,\s*(" + _LIT + r")\s*,\s*(" + _LIT + r")")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _unescape(lit: str) -> str:
    """The runtime value of a JS string literal (the escapes app.js uses)."""
    body, out, i = lit[1:-1], [], 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            n = body[i + 1]
            if n == "u" and body[i + 2] == "{":
                j = body.index("}", i)
                out.append(chr(int(body[i + 3:j], 16)))
                i = j + 1
            elif n == "u":
                out.append(chr(int(body[i + 2:i + 6], 16)))
                i += 6
            else:
                out.append({"n": "\n", "t": "\t", "r": "\r"}.get(n, n))
                i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _strip_comments(src: str) -> str:
    """Drop comments (they mention t() in prose). Only comments that start after whitespace count, so URLs ('https://')
    and regular expressions in the code are left alone."""
    src = re.sub(r"(^|\s)/\*[\s\S]*?\*/", r"\1", src)
    return re.sub(r"(^|\s)//[^\n]*", r"\1", src)


def app_keys() -> set[str]:
    src = _strip_comments(APP_JS.read_text(encoding="utf-8"))
    keys = {_unescape(m.group(1)) for m in _T_CALL.finditer(src)}
    for m in _PLURAL.finditer(src):
        keys.update((_unescape(m.group(1)), _unescape(m.group(2))))
    return keys


class _StaticText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.keys: set[str] = set()
        self._open: list[tuple[str, bool]] = []  # (tag, collecting text)
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "data-i18n" not in a:
            return
        what = (a["data-i18n"] or "text").split()
        for name in what:
            if name != "text" and a.get(name):
                self.keys.add(a[name])
        if "text" in what:
            self._open.append((tag, True))
            self._text = []

    def handle_data(self, data):
        if self._open:
            self._text.append(data)

    def handle_endtag(self, tag):
        if self._open and self._open[-1][0] == tag:
            self._open.pop()
            self.keys.add("".join(self._text))


def html_keys() -> set[str]:
    p = _StaticText()
    p.feed(INDEX.read_text(encoding="utf-8"))
    return p.keys


@pytest.fixture(scope="module")
def zh() -> dict[str, str]:
    return json.loads(ZH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def keys() -> set[str]:
    return app_keys() | html_keys()


def test_t_calls_use_literal_keys():
    """Every t(...) call in app.js has a literal first argument, so the keys above are all of them."""
    src = _strip_comments(APP_JS.read_text(encoding="utf-8"))
    calls = [m.start() for m in _T_ANY.finditer(src) if not src[max(0, m.start() - 9):m.start()].endswith("function ")
             and not src.startswith(DYNAMIC_CALLS, m.start())]
    literal = {m.start() for m in _T_CALL.finditer(src)}
    assert [src[i:i + 60] for i in calls if i not in literal] == []
    assert len(app_keys()) > 500 and len(html_keys()) > 20


def test_every_key_is_translated(keys, zh):
    assert sorted(k for k in keys if k not in zh) == []


def test_no_unused_entries(keys, zh):
    assert sorted(k for k in zh if k not in keys) == []


def test_placeholders_match(zh):
    bad = {k: v for k, v in zh.items() if sorted(_PLACEHOLDER.findall(k)) != sorted(_PLACEHOLDER.findall(v))}
    assert bad == {}


def test_translations_are_real(zh):
    assert [k for k, v in zh.items() if not v.strip()] == []
    assert sorted(k for k, v in zh.items() if v == k and k not in SAME_IN_ZH) == []
    assert {k: v for k, v in zh.items() if SIMPLIFIED_ONLY & set(v)} == {}


def test_dictionary_is_shipped_and_served(rt):
    from fastapi.testclient import TestClient

    from pland.server.app import create_app

    with TestClient(create_app(rt)) as client:
        served = client.get("/i18n/zh-Hant.json").json()
    assert served == json.loads(ZH.read_text(encoding="utf-8"))
    data = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert "server/static/i18n/*.json" in data
