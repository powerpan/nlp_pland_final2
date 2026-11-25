"""LocalBackend applies rlimits without subprocess's preexec_fn (unsafe in the threaded server), and web_fetch pins every
connection to the addresses its SSRF check approved (no DNS rebinding between check and connect).

No network: names resolve through a monkeypatched getaddrinfo and TCP connections go to fake sockets that answer
canned HTTP/1.1 responses, so the real httpx/httpcore stack (and the pinned network backend) runs end to end.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpcore
import pytest

from pland.config import SandboxConfig
from pland.sandbox import backends
from pland.sandbox.backends import LocalBackend
from pland.tools import web
from pland.tools.registry import ToolError

posix_only = pytest.mark.skipif(os.name != "posix", reason="rlimits and process groups are POSIX")

# --------------------------------------------------------------------------- LocalBackend


@pytest.fixture()
def backend(tmp_path: Path) -> LocalBackend:
    cfg = SandboxConfig()
    cfg.command_timeout = 2  # CPU limit = 2 * 2 + 5 = 9 s
    return LocalBackend(cfg, workspace=tmp_path)


@posix_only
def test_no_preexec_fn_and_limits_come_from_the_launcher(backend, tmp_path, monkeypatch):
    calls = []
    real_popen = subprocess.Popen

    def spy(argv, **kwargs):
        calls.append((list(argv), kwargs))
        return real_popen(argv, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", spy)
    r = backend.run("ulimit -t; ulimit -f; ulimit -c", tmp_path)
    assert r.exit_code == 0, r.render()
    assert r.stdout.split() == ["9", str(512 * 1024 * 1024 // 1024), "0"]  # bash reports -f in 1 KiB blocks
    r = backend.run_python("import resource as r; print(r.getrlimit(r.RLIMIT_CPU), r.getrlimit(r.RLIMIT_FSIZE))", tmp_path)
    assert r.stdout.strip() == f"(9, 9) ({512 * 1024 * 1024}, {512 * 1024 * 1024})", r.render()
    assert len(calls) == 2
    for argv, kwargs in calls:
        assert kwargs.get("preexec_fn") is None
        assert kwargs["start_new_session"] is True
        assert argv[:4] == [sys.executable, "-I", "-S", "-c"] and argv[4] == backends._RLIMIT_LAUNCHER
    if backend.seatbelt:  # the Seatbelt wrapper still comes right after the launcher
        assert calls[0][0][7:9] == [backends.SANDBOX_EXEC, "-p"]


@posix_only
def test_file_size_limit_stops_a_large_write(backend, tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "_limit_values", lambda: (30, 1024 * 1024))
    r = backend.run("head -c 3000000 /dev/zero > big.bin; echo rc=$?", tmp_path)
    assert "rc=1" in r.stdout and "File too large" in r.stderr, r.render()
    assert (tmp_path / "big.bin").stat().st_size == 1024 * 1024


@posix_only
def test_cpu_limit_kills_a_busy_loop(backend, tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "_limit_values", lambda: (1, 512 * 1024 * 1024))
    r = backend.run_python("while True:\n    pass\n", tmp_path, timeout=30)
    assert not r.timed_out and r.exit_code != 0 and r.duration < 15, r.render()


@posix_only
def test_launcher_reports_a_missing_program(backend, tmp_path):
    r = backend._exec(["/nonexistent/program"], tmp_path, 10, backends.scrub_env(sandbox=True))
    assert r.exit_code == 127 and "cannot run /nonexistent/program" in r.stderr


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()[:1] not in ("", "Z")


@posix_only
def test_timeout_kills_the_whole_process_group(backend, tmp_path):
    r = backend.run("(sleep 300 & echo $! > bg.pid); sleep 100", tmp_path, timeout=2)
    assert r.timed_out and r.exit_code == -9 and r.duration < 10
    pid = int((tmp_path / "bg.pid").read_text())
    deadline = time.time() + 5
    while _alive(pid) and time.time() < deadline:
        time.sleep(0.1)
    assert not _alive(pid), "the background sleep survived the timeout"


@posix_only
def test_cancel_kills_the_process_group(backend, tmp_path):
    polls = []
    r = backend.run("sleep 100 & echo $! > bg.pid; wait", tmp_path, timeout=60, cancel=lambda: polls.append(1) or len(polls) > 1)
    assert r.timed_out and "run cancelled" in r.stderr and r.duration < 10
    pid = int((tmp_path / "bg.pid").read_text())
    deadline = time.time() + 5
    while _alive(pid) and time.time() < deadline:
        time.sleep(0.1)
    assert not _alive(pid)


# --------------------------------------------------------------------------- web_fetch pinning


class _FakeSock:
    """Answers one HTTP/1.1 request from `routes[(host header, path)]` once the request has been sent."""

    def __init__(self, address, routes):
        self.address = address
        self.routes = routes
        self.sent = b""
        self._out: bytes | None = None

    def setsockopt(self, *args):
        pass

    def settimeout(self, timeout):
        pass

    def send(self, data):
        self.sent += bytes(data)
        return len(data)

    def recv(self, n):
        if self._out is None:
            head = self.sent.split(b"\r\n\r\n", 1)[0].decode()
            lines = head.split("\r\n")
            path = lines[0].split(" ")[1]
            host = next(v.strip() for k, _, v in (h.partition(":") for h in lines[1:]) if k.lower() == "host")
            status, headers, body = self.routes.get((host, path), (404, {}, b"missing"))
            hdrs = "".join(f"{k}: {v}\r\n" for k, v in {**headers, "Content-Length": len(body), "Connection": "close"}.items())
            self._out = f"HTTP/1.1 {status} X\r\n{hdrs}\r\n".encode() + body
        chunk, self._out = self._out[:n], self._out[n:]
        return chunk

    def fileno(self):
        return -1

    def close(self):
        pass

    @property
    def host_header(self) -> str:
        head = self.sent.split(b"\r\n\r\n", 1)[0].decode().split("\r\n")
        return next(h.split(":", 1)[1].strip() for h in head[1:] if h.lower().startswith("host:"))


@pytest.fixture()
def net(monkeypatch):
    """`answers[host]` is the list of answers getaddrinfo gives on successive lookups (the last one repeats);
    IP literals resolve to themselves. Every TCP connection is recorded in `socks`."""
    answers: dict[str, list[list[str]]] = {}
    lookups: list[str] = []
    socks: list[_FakeSock] = []
    routes: dict = {}

    def getaddrinfo(host, port, *args, **kwargs):
        lookups.append(host)
        try:
            ips = [str(web.ipaddress.ip_address(host))]
        except ValueError:
            queue = answers.get(host)
            if not queue:
                raise socket.gaierror(socket.EAI_NONAME, "unknown")
            ips = queue.pop(0) if len(queue) > 1 else queue[0]
        out = []
        for ip in ips:
            fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
            out.append((fam, socket.SOCK_STREAM, 6, "", (ip, port or 0) if fam == socket.AF_INET else (ip, port or 0, 0, 0)))
        return out

    def create_connection(address, timeout=None, source_address=None, **kwargs):
        sock = _FakeSock(address, routes)
        socks.append(sock)
        return sock

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(web, "_uses_proxy", lambda url: False)
    monkeypatch.setattr(web, "_deepseek", lambda: None)
    monkeypatch.setattr(web, "_fetch_client", web.httpx.Client(transport=web._pinned_transport()))  # fresh pool
    return answers, lookups, socks, routes


def test_fetch_client_uses_the_pinned_backend():
    assert isinstance(web._fetch_client._transport._pool._network_backend, web._PinnedBackend)


def test_rebinding_name_is_fetched_from_the_checked_public_ip(net):
    answers, lookups, socks, routes = net
    answers["rebind.example"] = [["93.184.215.14"], ["127.0.0.1"]]  # public for the check, loopback afterwards
    routes[("rebind.example", "/page")] = (200, {"Content-Type": "text/plain"}, b"public page")
    r = web._get_guarded("http://rebind.example/page")
    assert r.text == "public page" and str(r.url) == "http://rebind.example/page"
    assert [s.address for s in socks] == [("93.184.215.14", 80)]
    assert socks[0].host_header == "rebind.example"
    assert lookups.count("rebind.example") == 1  # the second (loopback) answer was never asked for


def test_every_redirect_hop_is_resolved_once_and_pinned(net):
    answers, lookups, socks, routes = net
    answers["rebind.example"] = [["93.184.215.14"], ["127.0.0.1"]]
    answers["next.example"] = [["93.184.215.20"], ["93.184.215.20"], ["127.0.0.1"]]  # two hops, then rebinding
    routes[("rebind.example", "/old")] = (302, {"Location": "http://next.example:8080/new"}, b"")
    routes[("next.example:8080", "/new")] = (302, {"Location": "/final"}, b"")
    routes[("next.example:8080", "/final")] = (200, {"Content-Type": "text/plain"}, b"done")
    r = web._get_guarded("http://rebind.example/old")
    assert r.text == "done" and str(r.url) == "http://next.example:8080/final"  # reported in hostname form
    assert [s.address for s in socks] == [("93.184.215.14", 80), ("93.184.215.20", 8080), ("93.184.215.20", 8080)]
    assert [s.host_header for s in socks] == ["rebind.example", "next.example:8080", "next.example:8080"]
    assert lookups.count("next.example") == 2  # one lookup per hop; the connect never asked again


def test_redirect_to_a_rebinding_internal_name_is_refused(net):
    answers, _, socks, routes = net
    answers["rebind.example"] = [["93.184.215.14"]]
    answers["evil.example"] = [["10.0.0.5"]]
    routes[("rebind.example", "/")] = (302, {"Location": "http://evil.example/admin"}, b"")
    with pytest.raises(ToolError, match="internal address 10.0.0.5"):
        web._get_guarded("http://rebind.example/")
    assert [s.address for s in socks] == [("93.184.215.14", 80)]


@pytest.mark.parametrize("ips", [["93.184.215.14", "127.0.0.1"], ["::ffff:127.0.0.1"], ["0.0.0.0"], ["fe80::1"], ["::1"]])
def test_any_internal_answer_refuses_the_name(net, ips):
    answers, _, socks, _ = net
    answers["mixed.example"] = [ips]
    with pytest.raises(ToolError, match="internal address"):
        web._get_guarded("http://mixed.example/")
    assert socks == []


def test_ipv6_names_and_literals_with_ports(net):
    answers, _, socks, routes = net
    answers["v6.example"] = [["2606:2800:220:1:248:1893:25c8:1946"], ["::1"]]
    routes[("v6.example", "/a")] = (302, {"Location": "http://[2606:4700::1111]:8443/b"}, b"")
    routes[("[2606:4700::1111]:8443", "/b")] = (200, {}, b"v6 ok")
    r = web._get_guarded("http://v6.example/a")
    assert r.text == "v6 ok" and str(r.url) == "http://[2606:4700::1111]:8443/b"
    assert [s.address for s in socks] == [("2606:2800:220:1:248:1893:25c8:1946", 80), ("2606:4700::1111", 8443)]
    with pytest.raises(ToolError, match="internal address ::1"):
        web._get_guarded("http://[::1]:8765/api/settings")


def test_connections_outside_get_guarded_are_checked_at_connect(net):
    answers, _, socks, _ = net
    answers["loop.example"] = [["127.0.0.1"]]
    with pytest.raises(ToolError, match="internal address 127.0.0.1"):
        web._fetch_client.get("http://loop.example/")  # no pin: the backend resolves and checks itself
    assert socks == []


def test_web_fetch_never_connects_to_a_rebound_address(net):
    answers, _, socks, routes = net
    # web_fetch checks the URL up front, then the hop resolves again: whichever answer the hop gets is the one used
    answers["rebind.example"] = [["93.184.215.14"], ["127.0.0.1"]]
    with pytest.raises(ToolError, match="internal address 127.0.0.1"):
        web.web_fetch(type("C", (), {"emit": lambda *a, **k: None})(), {"url": "http://rebind.example/data.json"})
    assert socks == []


def test_https_keeps_sni_and_certificate_hostname(net, monkeypatch):
    answers, _, socks, routes = net
    answers["secure.example"] = [["93.184.215.14"], ["127.0.0.1"]]
    routes[("secure.example", "/")] = (200, {}, b"tls ok")
    seen = []

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        seen.append((server_hostname, ssl_context.check_hostname, ssl_context.verify_mode))
        return self  # plaintext from here on: the fake socket speaks HTTP directly

    monkeypatch.setattr(httpcore._backends.sync.SyncStream, "start_tls", start_tls)
    r = web._get_guarded("https://secure.example/")
    assert r.text == "tls ok" and str(r.url) == "https://secure.example/"
    assert [s.address for s in socks] == [("93.184.215.14", 443)]
    import ssl
    assert seen == [("secure.example", True, ssl.CERT_REQUIRED)]  # verified against the name, not the pinned IP


def test_pinning_is_active_with_the_locked_httpx():
    """If httpx changes its transport layout, web_fetch falls back to check-then-connect: make that visible here."""
    from pland.tools import web

    assert web._PINNED_TRANSPORT is not None and web._fetch_client is not web._client
