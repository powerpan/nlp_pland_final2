from __future__ import annotations

from contextlib import asynccontextmanager
import ipaddress
import json
from pathlib import Path
import threading
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__
from ..config import load_dotenv
from ..runtime import Runtime
from ..sessions import SessionStore

STATIC_DIR = Path(__file__).resolve().parent / "static"


_LOCAL_HOSTS = {'localhost', 'testserver', '127.0.0.1', '::1'}
_SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}


def _host_name(netloc: str) -> str:
    """The host of a Host header or Origin netloc without the port: "[::1]:8765" -> "::1", "a.b:80" -> "a.b"."""
    value = (netloc or "").strip().lower()
    if value.startswith("["):
        return value[1:value.index("]")] if "]" in value else value.strip("[]")
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value

def is_loopback_host(host: str | None) -> bool:
    """True for 127.0.0.1 / ::1 / localhost (and TestClient's "testserver"), with or without a port."""
    name = _host_name(host or "")
    if name in {"localhost", "testserver"}:
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False

class SameOriginGuard:
    """ASGI middleware: the local server answers only its own page.

    * Host: when the server is bound to a loopback address, the Host header must name this computer
      (a remote page cannot make a browser send `Host: 127.0.0.1`, which closes DNS rebinding).
    * Origin: browsers send it on every cross-origin request and on every WebSocket handshake. When present on a
      state-changing method or a WebSocket handshake it must match Host (or a configured allowed host).
    * `Sec-Fetch-Site: cross-site` on a state-changing method is refused even without Origin.

    Reads (GET/HEAD/OPTIONS) only get the Host rule: without CORS headers another page cannot read their
    responses anyway. Requests without these headers (curl, scripts, tests) pass unchanged, so nothing that
    worked before is affected. WebSocket handshakes are checked like writes, since CORS does not cover them.
    """

    def __init__(self, app: Any, *, enforce_host: bool = True, allowed_hosts: set[str] | None = None):
        self.app = app
        self.enforce_host = enforce_host
        self.allowed_hosts = {h.lower() for h in (allowed_hosts or set())} | _LOCAL_HOSTS

    def refusal(self, scope: dict[str, Any]) -> str | None:
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        host = headers.get("host", "")
        if self.enforce_host and _host_name(host) not in self.allowed_hosts and not is_loopback_host(host):
            return "this server only answers requests addressed to this computer (http://127.0.0.1)"
        write = scope["type"] == "websocket" or str(scope.get("method", "GET")).upper() not in _SAFE_METHODS
        if not write:
            return None
        origin = headers.get("origin")
        if origin:
            netloc = urlparse(origin).netloc.lower()
            if netloc != host.lower() and _host_name(netloc) not in self.allowed_hosts - _LOCAL_HOSTS:
                return "refused: the request came from another web page"
        if headers.get("sec-fetch-site", "").lower() == "cross-site":
            return "refused: cross-site request"
        return None

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        why = self.refusal(scope)
        if why is None:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":  # closing before accept answers the handshake with HTTP 403
            await send({"type": "websocket.close", "code": 1008, "reason": why[:120]})
            return
        body = json.dumps({"detail": why}).encode("utf-8")
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class TextIn(BaseModel):
    text: str

class SessionIn(BaseModel):
    title: str = ""
    kind: str = "chat"


TOOL_RESULT_CLIP = 8000


def clip(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + f"\n… [{len(text) - limit} more chars]"

def display_items(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn `SessionStore.records()` into UI items.

    Item roles: `user` (kind: message | note | room_turn | agent_message), `assistant` (with
    `tool_calls`, each carrying its `result`/`ok`/`duration` once the tool returned) and `tool` (only
    for results whose call is not part of this batch, e.g. an incremental fetch)."""
    items: list[dict[str, Any]] = []
    calls: dict[str, dict[str, Any]] = {}
    for rec in records:
        msg, meta = rec["message"], rec["meta"] or {}
        role = msg.get("role")
        if role == "system":
            continue
        base = {"id": rec["id"], "created": rec["created"]}
        if role == "user":
            raw = msg.get("content") or ""
            if not isinstance(raw, str):
                raw = str(raw)
            if "display" in meta:
                content, kind = meta["display"] or "", "message"
                if meta.get("room_turn"):
                    kind = "room_turn"
                elif meta.get("from_agent"):
                    kind = "agent_message"
            else:
                content = raw
                kind = "note" if raw.startswith("[system]") or raw.startswith("[Summary of") else "message"
            items.append({**base, "role": "user", "kind": kind, "content": content,
                          "from_agent": meta.get("from_agent"), "turn_role": meta.get("role") if meta.get("room_turn") else None})
        elif role == "assistant":
            tcs = []
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                call = {"id": tc.get("id"), "name": fn.get("name") or "?", "args": fn.get("arguments") or "",
                        "result": None, "ok": None, "duration": None}
                if call["id"]:
                    calls[call["id"]] = call
                tcs.append(call)
            items.append({**base, "role": "assistant", "content": msg.get("content") or "",
                          "reasoning": msg.get("reasoning_content") or None, "tool_calls": tcs,
                          "error": bool(meta.get("error")), "cancelled": bool(meta.get("cancelled")),
                          "usage": meta.get("usage")})
        elif role == "tool":
            content = msg.get("content") or ""
            if not isinstance(content, str):
                content = str(content)
            result = {"result": clip(content, TOOL_RESULT_CLIP), "ok": not content.startswith("ERROR"),
                      "duration": meta.get("duration")}
            cid = msg.get("tool_call_id")
            if cid in calls:
                calls[cid].update(result)
            else:
                items.append({**base, "role": "tool", "tool_call_id": cid, "name": meta.get("tool") or "tool", **result})
    return items


def create_app(runtime: Runtime | None = None) -> FastAPI:
    load_dotenv()
    rt = runtime or Runtime()
    guard = threading.Lock()
    active = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        if runtime is None:
            rt.shutdown()

    app = FastAPI(title="PlanD", version=__version__, lifespan=lifespan)
    app.add_middleware(SameOriginGuard)
    app.state.runtime = rt

    @app.exception_handler(KeyError)
    async def key_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    def profile(name):
        if name != "default":
            raise HTTPException(404, "unknown profile")
        return rt.profiles.get("default")

    @app.get("/api/profiles/{name}/sessions")
    def list_sessions(name: str):
        return [session.to_dict() for session in SessionStore(profile(name)).list(kinds=("chat",))]

    @app.post("/api/profiles/{name}/sessions", status_code=201)
    def create_session(name: str, body: SessionIn):
        return SessionStore(profile(name)).create(title=body.title.strip()[:120], kind="chat").to_dict()

    @app.get("/api/profiles/{name}/sessions/{sid}/messages")
    def session_messages(name: str, sid: str):
        store = SessionStore(profile(name))
        session = store.get(sid)
        with guard:
            busy = (name, sid) in active
        return {"session": session.to_dict(), "items": display_items(store.records(sid)), "busy": busy}

    @app.post("/api/profiles/{name}/sessions/{sid}/messages", status_code=202)
    def post_message(name: str, sid: str, body: TextIn):
        prof = profile(name)
        store = SessionStore(prof)
        session = store.get(sid)
        text = body.text.strip()
        if not text:
            raise HTTPException(400, "message text is empty")
        key = (name, sid)
        with guard:
            if key in active or rt.is_busy(name, sid):
                raise HTTPException(409, "this conversation is already running")
            active.add(key)

        def work():
            try:
                rt.agent(prof, sid).run(text)
            except Exception as exc:
                rt.bus.publish("run.failed", profile=name, session_id=sid, error=type(exc).__name__)
            finally:
                with guard:
                    active.discard(key)

        try:
            rt.spawn(work)
        except Exception:
            with guard:
                active.discard(key)
            raise
        if not session.title:
            store.update(sid, title=" ".join(text.split())[:60])
        return {"accepted": True, "profile": name, "session_id": sid}

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
    return app
