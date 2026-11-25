"""Server hardening: which errors become 404/400/500, the security headers, a page without inline script, and
transcript paging. No model calls (nothing here starts a run)."""

from __future__ import annotations

import re
import warnings
from html.parser import HTMLParser
from pathlib import Path

import pytest

with warnings.catch_warnings():  # starlette's TestClient warns about its httpx backend at import time
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from pland.errors import NotFound
from pland.server import views
from pland.server.app import create_app
from pland.sessions import SessionStore

STATIC = Path(__file__).resolve().parents[1] / "pland" / "server" / "static"


@pytest.fixture()
def client(rt):
    with TestClient(create_app(rt)) as c:
        yield c


# --------------------------------------------------------------------------- errors

def test_store_lookups_raise_not_found_which_is_still_a_key_error(rt):
    with pytest.raises(NotFound):
        rt.profiles.get("nobody")
    with pytest.raises(KeyError):  # callers that catch KeyError keep working
        SessionStore(rt.profiles.get("default")).get("nope")
    with pytest.raises(NotFound):
        rt.rooms.update("no-room", name="x")
    with pytest.raises(NotFound):
        rt.broker.answer("no-request", text="hi")
    with pytest.raises(NotFound):
        rt.board.get("no-task")


def test_not_found_is_404_with_the_same_message(client):
    assert client.get("/api/profiles/nobody").json() == {"detail": "no profile named 'nobody'"}
    r = client.get("/api/profiles/default/sessions/nope")
    assert r.status_code == 404 and r.json()["detail"] == "no session nope in profile default"
    assert client.get("/api/rooms/nope").status_code == 404


def test_not_found_from_deep_in_the_core_is_404(client, monkeypatch):
    def missing(prof):
        raise NotFound("no task t-1")

    monkeypatch.setattr(views, "memory_view", missing)
    r = client.get("/api/profiles/default/memory")
    assert r.status_code == 404 and r.json() == {"detail": "no task t-1"}


def test_other_key_errors_are_500_and_logged(client, monkeypatch, caplog):
    def bug(prof):
        return {}["missing-field"]  # a programming error, not a missing object

    monkeypatch.setattr(views, "memory_view", bug)
    with caplog.at_level("ERROR", logger="pland.server"):
        r = client.get("/api/profiles/default/memory")
    assert r.status_code == 500
    assert r.json() == {"detail": "internal server error (KeyError)"}
    assert any("KeyError" in rec.getMessage() and rec.exc_info for rec in caplog.records)


def test_value_errors_are_400_but_decoding_errors_are_500(client, monkeypatch):
    monkeypatch.setattr(views, "memory_view", lambda prof: (_ for _ in ()).throw(ValueError("bad value")))
    r = client.get("/api/profiles/default/memory")
    assert r.status_code == 400 and r.json() == {"detail": "bad value"}

    monkeypatch.setattr(views, "memory_view", lambda prof: b"\xff".decode("utf-8"))
    assert client.get("/api/profiles/default/memory").status_code == 500


# --------------------------------------------------------------------------- security headers

def test_page_and_api_carry_csp_and_security_headers(client):
    for path in ("/", "/api/status", "/app.js", "/api/profiles/nobody"):
        r = client.get(path)
        csp = r.headers["content-security-policy"]
        assert "script-src 'self';" in csp and "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp
        for directive in ("default-src 'self'", "object-src 'none'", "base-uri 'none'", "frame-ancestors 'none'",
                          "form-action 'self'", "img-src 'self' data: blob:"):
            assert directive in csp, (path, directive)
        assert re.search(r"connect-src 'self' ws://testserver wss://testserver", csp)
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "no-referrer"


def test_refusals_of_the_origin_guard_get_the_headers_too(client):
    r = client.post("/api/rooms", json={"name": "x", "members": []}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and "content-security-policy" in r.headers


def test_a_strange_host_header_is_not_copied_into_the_policy():
    from pland.server.app import content_security_policy

    assert "ws://" not in content_security_policy("evil; script-src *")
    assert "ws://[::1]:8765" in content_security_policy("[::1]:8765")


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[dict[str, str | None]] = []
        self.inline: list[str] = []
        self.handlers: list[str] = []
        self.styles: list[str] = []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script":
            self.scripts.append(a)
            self._in_script = True
        if tag == "style":
            self.styles.append("<style>")
        self.handlers += [f"{tag}[{k}]" for k in a if k.startswith("on")]
        self.styles += [f"{tag}[style]" for k in a if k == "style"]

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._in_script and data.strip():
            self.inline.append(data.strip()[:60])


def test_index_html_has_no_inline_script_handlers_or_styles():
    page = _Page()
    page.feed((STATIC / "index.html").read_text(encoding="utf-8"))
    assert page.inline == [] and page.handlers == [] and page.styles == []
    assert [s.get("src") for s in page.scripts] == ["boot.js", "start.js"]  # same places as the inline scripts were
    for src in ("boot.js", "start.js"):
        assert (STATIC / src).is_file()


def test_app_js_builds_no_inline_style_attributes():
    """Markup strings fed to innerHTML must not carry style="…" (refused by style-src 'self'); element.style is fine."""
    src = (STATIC / "app.js").read_text(encoding="utf-8")
    assert not re.search(r"""style=\\?["']""", src)


# --------------------------------------------------------------------------- paging

def _turns(store: SessionStore, sid: str, n: int, tools: int = 2) -> None:
    """n turns: user, assistant with `tools` tool calls, their results, a final answer."""
    for i in range(n):
        store.append(sid, {"role": "user", "content": f"question {i}"}, {"display": f"question {i}"})
        calls = [{"id": f"c{i}-{k}", "type": "function", "function": {"name": "read_file", "arguments": "{}"}} for k in range(tools)]
        store.append(sid, {"role": "assistant", "content": "", "tool_calls": calls})
        for c in calls:
            store.append(sid, {"role": "tool", "tool_call_id": c["id"], "content": "ok"})
        store.append(sid, {"role": "assistant", "content": f"answer {i}"})


def test_session_paging_returns_whole_turns_newest_first(client, rt):
    prof = rt.profiles.get("default")
    store = SessionStore(prof)
    sid = store.create(title="long").id
    _turns(store, sid, 10)  # 5 records per turn
    url = f"/api/profiles/default/sessions/{sid}/messages"

    full = client.get(url).json()
    assert full["more"] is False and len(full["items"]) == 30

    first = client.get(url, params={"latest": 7}).json()  # 7 records reach into turn 8: widened to its start
    users = [it["content"] for it in first["items"] if it["role"] == "user"]
    assert users == ["question 8", "question 9"] and first["more"] is True
    assert first["last_id"] == full["last_id"]
    assert all(it["role"] != "tool" for it in first["items"])  # every result is paired with its call
    assert all(c["result"] == "ok" for it in first["items"] if it["role"] == "assistant" for c in it["tool_calls"])

    older = client.get(url, params={"before": first["first_id"], "latest": 7}).json()
    assert [it["content"] for it in older["items"] if it["role"] == "user"] == ["question 6", "question 7"]
    assert older["activity"] == [] and older["last_id"] == 0

    rest = client.get(url, params={"before": older["first_id"], "latest": 1000}).json()
    assert rest["more"] is False and len([it for it in rest["items"] if it["role"] == "user"]) == 6

    later = client.get(url, params={"after": full["last_id"], "latest": 7}).json()  # incremental fetches are not paged
    assert later["items"] == [] and later["more"] is False


def test_room_paging(client, rt):
    rt.profiles.create("ann", title="Ann", bot=True)
    room = rt.rooms.create("Team", ["ann"])
    for i in range(12):
        rt.rooms.post(room["id"], "user", f"m{i}")
    url = f"/api/rooms/{room['id']}/messages"
    newest = client.get(url, params={"latest": 5}).json()
    assert [m["content"] for m in newest["messages"]][-5:] == ["m7", "m8", "m9", "m10", "m11"]
    assert newest["more"] is True and newest["last_id"] == newest["messages"][-1]["id"]
    older = client.get(url, params={"before": newest["first_id"], "latest": 5}).json()
    assert [m["content"] for m in older["messages"]][-5:] == ["m2", "m3", "m4", "m5", "m6"]
    assert client.get(url).json()["more"] is False  # the old behaviour without paging parameters
