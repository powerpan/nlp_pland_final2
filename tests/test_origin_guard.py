"""The server answers only its own page (pland.server.app.SameOriginGuard): a loopback-bound server refuses foreign
Host headers, cross-site writes and cross-site WebSocket handshakes. Reads, same-origin requests and requests without
browser headers (curl, scripts) behave exactly as before."""

from __future__ import annotations

import json
import warnings

import pytest

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from starlette.websockets import WebSocketDisconnect

from pland.server.app import create_app, is_loopback_host

EVIL = {"Origin": "http://evil.example"}


@pytest.fixture()
def client(rt):
    with TestClient(create_app(rt)) as c:
        yield c


def test_reads_and_header_less_requests_are_unaffected(client):
    assert client.get("/api/status").status_code == 200
    assert client.get("/api/status", headers=EVIL).status_code == 200  # a cross-origin read is opaque to the page anyway
    assert client.post("/api/profiles/default/sessions").status_code == 201  # no Origin / Sec-Fetch-Site: a script


def test_same_origin_writes_pass(client):
    h = {"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"}
    assert client.post("/api/profiles/default/sessions", headers=h).status_code == 201
    r = client.post("/api/profiles/default/uploads?filename=ok.txt", content=b"x",
                    headers={**h, "Content-Type": "application/octet-stream"})
    assert r.status_code == 201


@pytest.mark.parametrize("path,kw", [
    ("/api/profiles/default/sessions", {}),
    ("/api/profiles/default/uploads?filename=planted.txt", {"content": b"x", "headers": {"Content-Type": "text/plain"}}),
    ("/api/team-templates/requirements-team/apply", {}),
    ("/api/profiles/default/sessions/x/messages", {"json": {"text": "hi"}}),
])
def test_cross_site_writes_are_refused(client, rt, path, kw):
    kw = dict(kw)
    headers = {**kw.pop("headers", {}), **EVIL}
    r = client.post(path, headers=headers, **kw)
    assert r.status_code == 403, r.text
    assert not (rt.profiles.get("default").workspace / "uploads" / "planted.txt").exists()
    assert not rt.profiles.exists("lead")


def test_sec_fetch_site_cross_site_is_refused_without_origin(client):
    assert client.post("/api/profiles/default/sessions", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/api/status", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


def test_websocket_handshake_must_be_same_origin(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/events", headers=EVIL):
            pass
    with client.websocket_connect("/api/events", headers={"Origin": "http://testserver"}) as ws:
        assert json.loads(ws.receive_text())["type"] == "hello"
    with client.websocket_connect("/api/events") as ws:  # no Origin: not a browser
        assert json.loads(ws.receive_text())["type"] == "hello"


def test_foreign_host_is_refused_when_bound_to_loopback(client):
    assert client.get("/api/status", headers={"Host": "attacker.example.com"}).status_code == 403
    assert client.get("/", headers={"Host": "attacker.example.com:8765"}).status_code == 403
    for host in ("127.0.0.1:8765", "localhost:8765", "[::1]:8765", "0.0.0.0:8765"):
        assert client.get("/api/status", headers={"Host": host}).status_code == 200, host


def test_host_rule_follows_the_bind_address_and_allowed_hosts(rt):
    with TestClient(create_app(rt, bind_host="0.0.0.0")) as c:  # exposed on purpose: any Host, writes still same-origin
        assert c.get("/api/status", headers={"Host": "192.168.1.20:8765"}).status_code == 200
        assert c.post("/api/profiles/default/sessions", headers=EVIL).status_code == 403
    with TestClient(create_app(rt, bind_host="127.0.0.1", allowed_hosts=["pland.example.com"])) as c:  # behind a proxy
        assert c.get("/api/status", headers={"Host": "pland.example.com"}).status_code == 200
        assert c.get("/api/status", headers={"Host": "other.example.com"}).status_code == 403
        assert c.post("/api/profiles/default/sessions", headers={"Origin": "https://pland.example.com"}).status_code == 201


def test_is_loopback_host():
    assert all(is_loopback_host(h) for h in ("127.0.0.1", "127.0.0.1:8765", "localhost", "::1", "[::1]:8765"))
    assert not any(is_loopback_host(h) for h in ("0.0.0.0", "example.com", "192.168.1.2", "", None))
