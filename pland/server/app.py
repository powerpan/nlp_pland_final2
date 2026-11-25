"""HTTP + WebSocket API and the browser UI for PlanD ("Bot Mode").

The web UI is where Bot Mode lives: the roster of
bots (= profiles), one canonical "Bot Chat" per bot, group rooms with a task board, HITL cards and
memory inspection. The everyday single-agent chat with the default profile is here too.

Design rules:

* One `Runtime` per process. Every run started from the API uses `runtime.broker` as its HITL
  channel, so clarifications and approvals become cards in the UI (`GET /api/hitl`,
  `POST /api/hitl/{id}`) and the blocked run continues in place once answered.
* HTTP handlers never block on a model run: agent runs and room drives execute on background
  threads (`runtime.spawn`); the client follows progress over `WS /api/events`.
* Handlers are plain `def` functions (FastAPI runs them in a threadpool) because the core is
  synchronous SQLite code.
* The server answers only its own page (`SameOriginGuard`): when bound to a loopback address the Host
  header must be local (no DNS rebinding), state-changing requests and WebSocket handshakes that carry an
  Origin must be same-origin, and `Sec-Fetch-Site: cross-site` is refused. Requests without those headers
  (curl, scripts, tests) and plain reads are untouched.

Endpoints (all JSON):

    GET    /api/status                          provider/model, key present?, docker, seatbelt, version
    GET    /api/activity                        active runs and room drives (live state)
    GET    /api/usage                           model-call totals from the ledger (+ per bot, per day)
    GET    /api/settings | PATCH                global defaults every bot inherits (PLAND_HOME/settings.yaml)
    PUT    /api/settings/keys/{provider}        set an API key (tested first; write-only) | DELETE removes it
    PATCH  /api/settings/provider               provider in use; HKGAI endpoint and model
    GET    /api/profiles                        roster (bots + default) with preview/busy flags
    POST   /api/profiles                        create a bot/profile
    GET    /api/profiles/{name}                 detail incl. SOUL and settings
    PATCH  /api/profiles/{name}                 update identity/settings
    DELETE /api/profiles/{name}
    GET    /api/profiles/{name}/memory          notes, skills, experiences, memory events
    GET    /api/profiles/{name}/files?path=     list a folder of the bot's workspace (read-only)
    GET    /api/profiles/{name}/files/content?path=   text of one workspace file (≤200 KB, no binaries)
    GET    /api/profiles/{name}/sessions        sessions (?kinds=chat,bot_chat)
    POST   /api/profiles/{name}/sessions        new session
    GET    /api/profiles/{name}/bot-chat        canonical Bot Chat session
    GET    /api/profiles/{name}/sessions/{sid}  session detail (incl. `todos`, the agent's plan)
    PATCH  /api/profiles/{name}/sessions/{sid}  rename
    DELETE /api/profiles/{name}/sessions/{sid}
    GET    /api/profiles/{name}/sessions/{sid}/messages?after=&events_after=   items, activity, todos
    POST   /api/profiles/{name}/sessions/{sid}/messages   {text} -> run in background (409 if busy)
    POST   /api/profiles/{name}/sessions/{sid}/stop
    POST   /api/profiles/{name}/sessions/{sid}/resume     continue an interrupted run (Agent.resume)
    GET    /api/interrupted                     sessions that can be resumed
    GET    /api/rooms | POST /api/rooms
    GET    /api/rooms/{id} | PATCH | DELETE
    GET    /api/rooms/{id}/messages?after=
    POST   /api/rooms/{id}/messages             {text} -> room drive in background
    POST   /api/rooms/{id}/stop
    GET    /api/rooms/{id}/tasks                team board of the room
    GET    /api/rooms/{id}/files?path=          list a folder of the room's shared/ folder (read-only)
    GET    /api/rooms/{id}/files/content?path=  text of one shared file
    GET    /api/board/{scope}                   any board scope (e.g. dm:<profile>)
    GET    /api/hitl                            pending requests (?room_id=&profile=&session_id=)
    POST   /api/hitl/{id}                       {text?, choice?}
    WS     /api/events                          every bus event as JSON
    GET    /                                    static UI (pland/server/static)
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import anyio
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__
from ..config import AgentSettings, ModelConfig, default_provider, load_dotenv
from ..hitl import APPROVAL_CHOICES
from .. import workspace as workspaces
from .. import keys
from ..llm import reasoning
from ..profiles import NAME_RE, Profile, slugify
from ..runtime import Runtime
from ..sandbox.backends import SANDBOX_EXEC
from ..sessions import SessionStore
from ..llm.pricing import cost
from . import files, views
from .live import EventBridge, LiveState
from .settings import patch as global_patch, view as global_view

STATIC_DIR = Path(__file__).resolve().parent / "static"
CHAT_KINDS = ("chat", "bot_chat")
SESSION_KINDS = ("chat", "bot_chat", "room_member", "delegation", "subagent", "eval")
KNOWN_TOOLSETS = tuple(AgentSettings().toolsets)
BACKENDS = ("local", "docker")
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
# Effective execution backends (`Backend.name`) and how the UI names them.
BACKEND_LABELS = {"local+seatbelt": "local (sandboxed)", "local": "local", "docker": "docker"}
APPROVAL_MODES = ("manual", "off")
MODEL_CHOICES = ("deepseek-flash", "deepseek-v4-pro")


# --------------------------------------------------------------------------- request bodies

class ProfileIn(BaseModel):
    name: str | None = None
    title: str | None = None
    description: str = ""
    soul: str | None = None
    bot: bool = True
    model: str | None = None
    thinking: bool | None = None
    reasoning: str | None = None  # thinking intensity: off|default|minimal|low|medium|high|xhigh|max
    backend: str | None = None
    toolsets: list[str] | None = None
    clone_from: str | None = None
    avatar: str | None = None


class ProfilePatch(BaseModel):
    title: str | None = None
    description: str | None = None
    soul: str | None = None
    bot: bool | None = None
    avatar: str | None = None
    model: str | None = None
    thinking: bool | None = None
    reasoning: str | None = None
    backend: str | None = None
    toolsets: list[str] | None = None
    approvals: str | None = None
    max_iterations: int | None = None


class SessionIn(BaseModel):
    title: str = ""
    kind: str = "chat"


class SessionPatch(BaseModel):
    title: str | None = None
    # this chat's thinking intensity (off|default|minimal…max); "" or "reset" = use the bot's setting
    reasoning: str | None = None
    model: str | None = None  # this chat's model id; "" or "reset" = use the bot's setting
    workspace: str | None = None  # absolute folder this chat works in; "" or "default" = the bot's own workspace


class TextIn(BaseModel):
    text: str = ""
    attachments: list[str] = []  # paths returned by the upload endpoint (uploads/…)


class RoomIn(BaseModel):
    name: str
    members: list[str]
    lead: str | None = None


class RoomPatch(BaseModel):
    name: str | None = None
    members: list[str] | None = None
    lead: str | None = None
    needs_you: bool | None = None
    max_rounds: int | None = None
    max_messages: int | None = None
    workspace: str | None = None  # absolute folder used as the group's shared folder; "" = the default one


class KeyIn(BaseModel):
    key: str
    test: bool = True  # one tiny real call with the key before saving it


class EndpointIn(BaseModel):
    provider: str
    base_url: str | None = None  # "" clears it
    model: str | None = None


class ProviderIn(BaseModel):
    provider: str | None = None  # the provider every agent uses (PLAND_PROVIDER)
    endpoint: EndpointIn | None = None


class AnswerIn(BaseModel):
    text: str = ""
    choice: str | None = None


# --------------------------------------------------------------------------- helpers

def _workspace_fields(default: Path, meta: dict[str, Any] | None) -> dict[str, Any]:
    folder, error = workspaces.resolve(default, meta)
    return {"workspace": str(folder), "workspace_custom": bool(workspaces.chosen(meta)), "workspace_error": error}


def _chat_model(prof: Profile, value: str) -> str | None:
    """Validate a per-chat model id ("" / "reset" clears it). DeepSeek chats only take deepseek-* ids."""
    word = value.strip()
    if word.lower() in {"", "reset", "default"}:
        return None
    if not MODEL_ID_RE.match(word):
        raise HTTPException(400, "invalid model id")
    if prof.settings().model.provider == "deepseek" and not word.startswith("deepseek-"):
        raise HTTPException(400, "this bot uses DeepSeek; choose a deepseek-* model")
    return word


def _with_attachments(body: TextIn, attached: list[str], prefix: str) -> str:
    """The message text plus a note telling the agent where the uploaded files are."""
    text = body.text.strip()
    if not attached:
        return text
    where = "the group's shared folder" if prefix else "your workspace"
    note = f"[Attached files, saved in {where}: " + ", ".join(f"`{prefix}{p}`" for p in attached) + "]"
    return f"{text}\n\n{note}" if text else f"Please look at the attached files.\n\n{note}"


async def _upload_body(request: Request) -> bytes:
    size = int(request.headers.get("content-length") or 0)
    if size > files.MAX_UPLOAD:
        raise HTTPException(413, f"file is larger than {files.MAX_UPLOAD // (1024 * 1024)} MB")
    return await request.body()


def _settings_patch(body: ProfileIn | ProfilePatch) -> dict[str, Any]:
    """Translate flat UI fields into the nested `settings` structure stored in profile.yaml."""
    settings: dict[str, Any] = {}
    model: dict[str, Any] = {}
    if body.model:
        model["model"] = body.model.strip()
    if body.thinking is not None:
        model["thinking"] = bool(body.thinking)
    if body.reasoning is not None:
        try:
            model.update(reasoning.to_settings(body.reasoning))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    if model:
        settings["model"] = model
    if body.backend:
        if body.backend not in BACKENDS:
            raise HTTPException(400, f"backend must be one of {', '.join(BACKENDS)}")
        settings["sandbox"] = {"backend": body.backend}
    if body.toolsets is not None:
        unknown = [t for t in body.toolsets if t not in KNOWN_TOOLSETS]
        if unknown:
            raise HTTPException(400, f"unknown toolsets: {', '.join(unknown)}")
        settings["toolsets"] = [t for t in KNOWN_TOOLSETS if t in body.toolsets]
    if isinstance(body, ProfilePatch):
        if body.approvals is not None:
            if body.approvals not in APPROVAL_MODES:
                raise HTTPException(400, f"approvals must be one of {', '.join(APPROVAL_MODES)}")
            settings["approvals"] = {"mode": body.approvals}
        if body.max_iterations is not None:
            if not 1 <= body.max_iterations <= 200:
                raise HTTPException(400, "max_iterations must be between 1 and 200")
            settings["max_iterations"] = body.max_iterations
    return settings


_LOOPBACK = {"127.0.0.1", "::1", "localhost", "testserver"}
# Host names a loopback-bound server answers to ("testserver" is Starlette's TestClient; 0.0.0.0 reaches
# localhost in some browsers and cannot be the target of DNS rebinding).
_LOCAL_HOSTS = _LOOPBACK | {"0.0.0.0"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _local_only(request: Request) -> None:
    """Changing an API key is allowed only from this computer, from this page: a loopback client, a loopback Host
    header (no DNS rebinding), no foreign Origin (no other web page posting here) and a JSON body."""
    client = request.client.host if request.client else ""
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]").lower()
    if client not in {"127.0.0.1", "::1", "testclient"} or host not in _LOOPBACK:
        raise HTTPException(403, "API keys can only be changed from this computer (http://127.0.0.1)")
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "refused: the request came from another web page")
    if request.method != "DELETE" and "application/json" not in (request.headers.get("content-type") or ""):
        raise HTTPException(415, "expected a JSON body")


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


def seatbelt_available() -> bool:
    """macOS Seatbelt (`sandbox-exec`), which confines the local backend when `os_sandbox` is auto."""
    return sys.platform == "darwin" and os.path.exists(SANDBOX_EXEC)


def effective_backend(settings: AgentSettings) -> str:
    """The backend name a run of these settings gets (mirrors `LocalBackend`/`make_backend`, without
    instantiating one): docker | local+seatbelt | local."""
    sb = settings.sandbox
    if sb.backend == "docker":
        return "docker"
    return "local+seatbelt" if sb.os_sandbox == "auto" and seatbelt_available() else "local"


def _bot_chat_id(profile: Profile) -> str | None:
    """Read-only lookup of the Bot Chat used last (does not create one)."""
    return profile.latest_bot_chat_id()


class Server:
    """Holds the runtime and the server-side bookkeeping shared by all routes."""

    def __init__(self, runtime: Runtime, *, owns_runtime: bool):
        self.rt = runtime
        self.owns_runtime = owns_runtime
        self.live = LiveState(runtime)
        self._guard = threading.Lock()
        self._active: set[tuple[str, str]] = set()  # runs started by this server, until their thread ends
        self._stopping_rooms: set[str] = set()
        self._docker: bool | None = None
        self._docker_checking = False
        self._token = runtime.bus.subscribe(self._on_event)
        self.started = time.time()
        # Recovery after a crash/restart: sessions a dead process left 'running' are marked
        # 'interrupted' (resumable in place via Agent.resume()), and HITL requests whose waiting
        # thread died are cancelled — resuming re-asks them.
        try:
            self.recovered: list[dict[str, Any]] = runtime.recover_interrupted()
        except Exception:
            self.recovered = []
        try:
            runtime.broker.cancel_orphans()
        except Exception:
            pass

    def close(self) -> None:
        self.rt.bus.unsubscribe(self._token)
        self.live.close()

    # ------------------------------------------------------------------ lookups
    def profile(self, name: str) -> Profile:
        try:
            return self.rt.profiles.get(name)
        except KeyError:
            raise HTTPException(404, f"no profile named {name!r}") from None

    def session(self, prof: Profile, sid: str):
        try:
            return SessionStore(prof).get(sid)
        except KeyError:
            raise HTTPException(404, f"no session {sid} in profile {prof.name}") from None

    def folder(self, prof: Profile, sid: str | None = None) -> Path:
        """Where a conversation's files live (pland/workspace.py); the bot's workspace without a session."""
        if not sid:
            return prof.workspace
        folder, error = workspaces.resolve(prof.workspace, self.session(prof, sid).meta)
        if error:
            raise HTTPException(409, error)
        return folder

    def check_folder(self, value: str) -> str | None:
        word = (value or "").strip()
        if word.lower() in {"", "default", "reset"}:
            return None
        try:
            return str(workspaces.check_workspace(word, pland_root=self.rt.root))
        except workspaces.WorkspaceError as exc:
            raise HTTPException(400, str(exc)) from None

    def room(self, rid: str) -> dict[str, Any]:
        room = self.rt.rooms.get(rid)
        if room is None:
            raise HTTPException(404, f"no room {rid}")
        return room

    def busy(self, profile: str, sid: str) -> bool:
        with self._guard:
            if (profile, sid) in self._active:
                return True
        return self.rt.is_busy(profile, sid) or self.live.is_running(profile, sid)

    def profile_busy(self, profile: str) -> bool:
        with self._guard:
            if any(p == profile for p, _ in self._active):
                return True
        return self.live.is_running(profile)

    # ------------------------------------------------------------------ docker probe
    def docker_status(self) -> bool | None:
        """`docker info` can take seconds, so it is probed once in the background."""
        if self._docker is None and not self._docker_checking:
            self._docker_checking = True

            def probe() -> None:
                try:
                    from ..sandbox import DockerBackend

                    self._docker = bool(DockerBackend.available())
                except Exception:
                    self._docker = False

            threading.Thread(target=probe, name="pland-docker-probe", daemon=True).start()
        return self._docker

    # ------------------------------------------------------------------ runs
    def start_run(self, prof: Profile, sid: str, text: str | None) -> None:
        """Start `Agent.run(text)` (or `resume()` when text is None) on a background thread."""
        key = (prof.name, sid)
        with self._guard:
            if key in self._active or self.rt.is_busy(*key):
                raise HTTPException(409, "this conversation is already running")
            self._active.add(key)
        rt = self.rt

        def work() -> None:
            try:
                agent = rt.agent(prof, sid, hitl=rt.broker)
                if text is None:
                    agent.resume()
                else:
                    agent.run(text)
            except Exception as exc:  # Agent.run records its own failures; this is a last resort
                rt.bus.publish("run.failed", profile=prof.name, session_id=sid, error=f"{type(exc).__name__}: {exc}")
            finally:
                with self._guard:
                    self._active.discard(key)

        try:
            rt.spawn(work, name=f"run-{prof.name}-{sid}")
        except Exception:
            with self._guard:
                self._active.discard(key)
            raise

    def release_hitl(self, *, profile: str | None = None, session_id: str | None = None,
                     room_id: str | None = None) -> int:
        """Answer pending requests so a run blocked on a human can observe a stop request."""
        n = 0
        for req in self.rt.broker.pending(room_id=room_id, profile=profile):
            if session_id and req["session_id"] != session_id and \
                    self.live.origin(req["profile"], req["session_id"]).get("session_id") != session_id:
                continue
            try:
                if req["kind"] == "approval":
                    self.rt.broker.answer(req["id"], text="The user stopped the run.", choice="deny")
                else:
                    self.rt.broker.answer(req["id"], text="The user stopped the run; do not continue.")
                n += 1
            except (KeyError, ValueError):
                pass
        return n

    def stop_session(self, prof: Profile, sid: str) -> dict[str, Any]:
        self.rt.cancel(prof.name, sid)
        # Delegates working for this conversation run in their own sessions: cancel them too.
        cancelled = [{"profile": prof.name, "session_id": sid}]
        for run in self.live.snapshot()["runs"]:
            origin = run.get("origin") or {}
            if (origin.get("profile"), origin.get("session_id")) == (prof.name, sid) and \
                    (run["profile"], run["session_id"]) != (prof.name, sid):
                self.rt.cancel(run["profile"], run["session_id"])
                cancelled.append({"profile": run["profile"], "session_id": run["session_id"]})
        released = self.release_hitl(session_id=sid)
        return {"cancelled": cancelled, "released_hitl": released}

    def stop_room(self, rid: str) -> dict[str, Any]:
        """Stop a room drive: cancel every run in the room now, and every run that starts in it
        until the drive settles (Agent.run clears cancel flags at start, so we re-cancel on
        `run.started`)."""
        with self._guard:
            if self.rt.rooms.drive_lock(rid).locked():
                self._stopping_rooms.add(rid)
        cancelled = []
        for run in self.live.snapshot()["runs"]:
            if run.get("room_id") == rid:
                self.rt.cancel(run["profile"], run["session_id"])
                cancelled.append({"profile": run["profile"], "session_id": run["session_id"]})
        released = self.release_hitl(room_id=rid)
        return {"cancelled": cancelled, "released_hitl": released}

    def _on_event(self, ev: dict[str, Any]) -> None:
        t = ev.get("type")
        rid = ev.get("room_id")
        if not rid:
            return
        with self._guard:
            stopping = rid in self._stopping_rooms
            if t == "room.drive" and ev.get("state") == "settled":
                self._stopping_rooms.discard(rid)
        if stopping and t == "run.started" and ev.get("profile") and ev.get("session_id"):
            self.rt.cancel(ev["profile"], ev["session_id"])

    # ------------------------------------------------------------------ views
    def profile_row(self, prof: Profile) -> dict[str, Any]:
        row = prof.summary()
        backend = effective_backend(prof.settings())
        row.update(backend_effective=backend, backend_label=BACKEND_LABELS.get(backend, backend))
        m = prof.settings().model
        row["reasoning"] = reasoning.current(m.thinking, m.reasoning_effort) if m.provider in reasoning.PROVIDER_LEVELS else "off"
        chat_id = _bot_chat_id(prof)
        chat_status = None
        if chat_id:
            sess = SessionStore(prof).get(chat_id)
            chat_status = "interrupted" if self.interrupted(prof, sess) else sess.status
        row.update(
            bot_chat_id=chat_id,
            bot_chat_status=chat_status,
            preview=views.last_message_preview(prof, chat_id) if chat_id else None,
            busy=self.profile_busy(prof.name),
            pending_hitl=len(self.rt.broker.pending(profile=prof.name)),
        )
        return row

    def profile_detail(self, prof: Profile) -> dict[str, Any]:
        s = prof.settings()
        row = self.profile_row(prof)
        row.update(
            soul=prof.soul,
            settings={
                "model": s.model.model or row.get("model"),
                "thinking": bool(s.model.thinking),
                "reasoning": row["reasoning"],
                "backend": s.sandbox.backend,
                "os_sandbox": s.sandbox.os_sandbox,
                "backend_effective": row["backend_effective"],
                "backend_label": row["backend_label"],
                "toolsets": list(s.toolsets),
                "approvals": s.approvals.mode,
                "max_iterations": s.max_iterations,
                "reflection": s.reflection,
            },
            workspace=str(prof.workspace),
            session_count=(prof.db.one("SELECT COUNT(*) n FROM sessions") or {}).get("n", 0),
            experience_count=(prof.db.one("SELECT COUNT(*) n FROM experiences") or {}).get("n", 0),
        )
        return row

    def interrupted(self, prof: Profile, sess, *, busy: bool | None = None) -> bool:
        """A session can be resumed when it is not running and either the startup recovery marked
        it 'interrupted' or its transcript ends in tool calls that never got results."""
        if busy is None:
            busy = self.busy(prof.name, sess.id)
        if busy:
            return False
        return sess.status == "interrupted" or views.dangling_tool_calls(views.tail_records(prof, sess.id)) > 0

    def session_row(self, prof: Profile, sess) -> dict[str, Any]:
        d = sess.to_dict()
        d["profile"] = prof.name
        d["busy"] = self.busy(prof.name, sess.id)
        d["interrupted"] = self.interrupted(prof, sess, busy=d["busy"])
        d["preview"] = views.last_message_preview(prof, sess.id)
        d["todos"] = views.session_todos(sess)
        d["reasoning"] = (sess.meta or {}).get("reasoning")  # this chat's own intensity, None = the bot's setting
        d["model"] = (sess.meta or {}).get("model")  # this chat's own model, None = the bot's setting
        d.update(_workspace_fields(prof.workspace, sess.meta))
        return d

    def room_row(self, room: dict[str, Any], *, preview: bool = True) -> dict[str, Any]:
        rid = room["id"]
        members = []
        for name in room["members"]:
            try:
                p = self.rt.profiles.get(name)
                members.append({"name": name, "title": p.title, "avatar": p.avatar, "description": p.description,
                                "busy": self.profile_busy(name)})
            except KeyError:
                members.append({"name": name, "title": name, "avatar": "#9ca3af", "description": "(deleted)",
                                "busy": False, "missing": True})
        out = dict(room)
        out["lead"] = (room.get("settings") or {}).get("lead")
        out["member_info"] = members
        out["workspace"] = str(self.rt.rooms.shared_dir(rid))
        out["workspace_custom"] = bool(workspaces.chosen(room.get("settings")))
        out["driving"] = self.rt.rooms.drive_lock(rid).locked()
        out["pending_hitl"] = len(self.rt.broker.pending(room_id=rid))
        if preview:
            row = self.rt.shared.one("SELECT speaker, content, created FROM room_messages WHERE room_id=? AND kind='message' "
                                     "ORDER BY id DESC LIMIT 1", (rid,))
            if row:
                out["preview"] = {"speaker": row["speaker"], "text": " ".join(row["content"].split())[:views.PREVIEW_CHARS],
                                  "created": row["created"]}
            else:
                out["preview"] = None
        return out

    def hitl_row(self, req: dict[str, Any]) -> dict[str, Any]:
        row = dict(req)
        try:
            p = self.rt.profiles.get(req["profile"])
            row["profile_title"], row["avatar"] = p.title, p.avatar
        except KeyError:
            row["profile_title"], row["avatar"] = req["profile"], "#9ca3af"
        row["origin"] = self.live.origin(req["profile"], req["session_id"])
        return row


# --------------------------------------------------------------------------- app factory

def create_app(runtime: Runtime | None = None, *, bind_host: str | None = None,
               allowed_hosts: list[str] | None = None) -> FastAPI:
    """Build the FastAPI app around one `Runtime` (created from PLAND_HOME when not given).

    `bind_host` is the address the server listens on (default: a loopback address): the Host header is checked
    only for loopback binds, so `--host 0.0.0.0` keeps answering any Host. `allowed_hosts` adds host names
    (e.g. a reverse proxy's domain) accepted as Host and as the Origin of state-changing requests."""
    load_dotenv()
    owns = runtime is None
    rt = runtime or Runtime()
    srv = Server(rt, owns_runtime=owns)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        srv.close()
        if srv.owns_runtime:
            rt.shutdown()

    app = FastAPI(title="PlanD", version=__version__, lifespan=lifespan)
    app.add_middleware(SameOriginGuard, enforce_host=bind_host is None or is_loopback_host(bind_host),
                       allowed_hosts={*(allowed_hosts or []), *([bind_host] if bind_host else [])})
    app.state.runtime = rt
    app.state.server = srv

    @app.exception_handler(KeyError)
    async def _key_error(request: Request, exc: KeyError):  # missing objects deep in the core
        return JSONResponse({"detail": str(exc.args[0]) if exc.args else "not found"}, status_code=404)

    @app.exception_handler(ValueError)
    async def _value_error(request: Request, exc: ValueError):  # validation errors raised by the core
        return JSONResponse({"detail": str(exc)}, status_code=400)

    # ------------------------------------------------------------------ status
    @app.get("/api/status")
    def status() -> dict[str, Any]:
        provider = default_provider()
        try:
            cfg = ModelConfig(provider=provider).resolved()
            model, base_url, key_set = cfg.model, cfg.base_url, bool(cfg.api_key)
        except ValueError:
            model, base_url, key_set = None, None, False
        return {
            "app": "pland",
            "version": __version__,
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "api_key_set": key_set,  # never the key itself
            "docker": srv.docker_status(),
            "seatbelt": seatbelt_available(),  # local runs are Seatbelt-confined unless os_sandbox=off
            "home": str(rt.root),
            "models": list(MODEL_CHOICES),
            "toolsets": list(KNOWN_TOOLSETS),
            "backends": list(BACKENDS),
            "backend_labels": BACKEND_LABELS,
            "pending_hitl": len(rt.broker.pending()),
            "recovered": srv.recovered,  # sessions marked interrupted at startup
            "uptime": round(time.time() - srv.started, 1),
        }

    @app.get("/api/activity")
    def activity() -> dict[str, Any]:
        return srv.live.snapshot()

    @app.get("/api/usage")
    def usage(since: float | None = None) -> dict[str, Any]:
        totals = rt.ledger.totals(since=since)
        where, params = (" WHERE ts>=?", [since]) if since else ("", [])
        sums = ("COUNT(*) calls, COALESCE(SUM(prompt_tokens),0) prompt_tokens, COALESCE(SUM(cached_tokens),0) cached_tokens, "
                "COALESCE(SUM(completion_tokens),0) completion_tokens")

        def costed(group: str) -> list[dict[str, Any]]:
            # priced per model (flash and pro differ several-fold), then summed per group
            out: dict[str, dict[str, Any]] = {}
            for r in rt.shared.query(f"SELECT {group} grp, model, {sums} FROM llm_calls{where} GROUP BY grp, model", params):
                row = out.setdefault(r["grp"], {"calls": 0, "prompt_tokens": 0, "cached_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0})
                for key in ("calls", "prompt_tokens", "cached_tokens", "completion_tokens"):
                    row[key] += int(r[key] or 0)
                row["cost_usd"] += cost(int(r["prompt_tokens"] or 0), int(r["cached_tokens"] or 0), int(r["completion_tokens"] or 0), r["model"])
            return [{"key": k, **v, "cost_usd": round(v["cost_usd"], 5)} for k, v in out.items()]

        totals["by_profile"] = sorted(({"profile": r.pop("key"), **r} for r in costed("profile")), key=lambda r: -r["calls"])
        days = costed("date(ts, 'unixepoch', 'localtime')")
        totals["by_day"] = sorted(({"day": r.pop("key"), **r} for r in days), key=lambda r: r["day"])[-30:]
        return totals

    # ------------------------------------------------------------------ global settings (Settings page)
    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return global_view(rt)

    @app.patch("/api/settings")
    def patch_settings(body: dict[str, Any]) -> dict[str, Any]:
        result = global_patch(rt, body)
        rt.bus.publish("settings.updated", fields=sorted(body))
        return result

    # API keys and the provider (pland/keys.py): write-only, from this computer and this page only.
    def key_ledger(provider, cfg, usage, seconds, ok, error):
        rt.ledger.record(root_run="key_test", run_id="key_test", profile="default", session_id="settings",
                         purpose="key_test", model=cfg.resolved().model or "?", usage=usage, duration=seconds, ok=ok,
                         error=error)

    def keys_done(notices: list[str], fields: list[str]) -> dict[str, Any]:
        rt.bus.publish("settings.updated", fields=fields)
        return {**global_view(rt), "notice": " ".join(n for n in notices if n) or None}

    @app.put("/api/settings/keys/{provider}")
    def put_key(provider: str, body: KeyIn, request: Request) -> dict[str, Any]:
        _local_only(request)
        try:
            key = keys.check_key(body.key)
            tested = keys.test_key(provider, key, ledger=key_ledger) if body.test else None
            warning = keys.set_key(provider, key, rt.root)
        except keys.KeySetupError as exc:
            raise HTTPException(400, str(exc)) from None
        label = keys.LABELS.get(provider, provider)
        done = (f"Saved and tested: {label} answered in {tested['seconds']} s." if tested else "Saved (not tested).")
        return keys_done([done, (tested or {}).get("warning"), warning], ["api_key"])

    @app.delete("/api/settings/keys/{provider}")
    def delete_key(provider: str, request: Request) -> dict[str, Any]:
        _local_only(request)
        try:
            warning = keys.remove_key(provider, rt.root)
        except keys.KeySetupError as exc:
            raise HTTPException(400, str(exc)) from None
        return keys_done(["Key removed.", warning], ["api_key"])

    @app.patch("/api/settings/provider")
    def patch_provider(body: ProviderIn, request: Request) -> dict[str, Any]:
        _local_only(request)
        try:
            warnings = keys.configure(body.provider, endpoint=body.endpoint.model_dump(exclude_unset=True) if body.endpoint else None,
                                      root=rt.root)
        except keys.KeySetupError as exc:
            raise HTTPException(400, str(exc)) from None
        return keys_done(["Saved.", *warnings], ["provider"])

    # ------------------------------------------------------------------ profiles
    @app.get("/api/profiles")
    def list_profiles(bots_only: bool = False) -> list[dict[str, Any]]:
        return [srv.profile_row(p) for p in rt.profiles.list(bots_only=bots_only)]

    @app.post("/api/profiles", status_code=201)
    def create_profile(body: ProfileIn) -> dict[str, Any]:
        if not (body.name or "").strip() and not (body.title or "").strip():
            raise HTTPException(400, "a bot needs a name or a title")
        name = (body.name or "").strip().lstrip("@").lower() or slugify(body.title or "")
        if not NAME_RE.match(name):
            raise HTTPException(400, "name must match [a-z0-9][a-z0-9_-]{0,31}")
        if rt.profiles.exists(name):
            raise HTTPException(409, f"a profile named {name!r} already exists")
        if body.clone_from and not rt.profiles.exists(body.clone_from):
            raise HTTPException(404, f"no profile named {body.clone_from!r} to clone")
        prof = rt.profiles.create(
            name, title=(body.title or "").strip() or None, description=body.description.strip(),
            soul=body.soul if body.soul and body.soul.strip() else None, bot=body.bot,
            settings=_settings_patch(body), clone_from=body.clone_from, avatar=body.avatar or None,
        )
        rt.bus.publish("profile.created", profile=prof.name)
        return srv.profile_detail(prof)

    @app.get("/api/profiles/{name}")
    def get_profile(name: str) -> dict[str, Any]:
        return srv.profile_detail(srv.profile(name))

    @app.patch("/api/profiles/{name}")
    def patch_profile(name: str, body: ProfilePatch) -> dict[str, Any]:
        srv.profile(name)
        changes: dict[str, Any] = {k: getattr(body, k) for k in ("title", "description", "bot", "avatar")}
        if name == "default":
            changes["bot"] = None  # the default profile stays the single-agent assistant
        prof = rt.profiles.update(name, soul=body.soul, settings=_settings_patch(body) or None, **changes)
        rt.bus.publish("profile.updated", profile=name)
        return srv.profile_detail(prof)

    @app.delete("/api/profiles/{name}")
    def delete_profile(name: str) -> dict[str, Any]:
        srv.profile(name)
        if name == "default":
            raise HTTPException(400, "the default profile cannot be deleted")
        if srv.profile_busy(name):
            raise HTTPException(409, f"@{name} is working right now; stop it first")
        rt.profiles.delete(name)
        # Keep rooms consistent: drop the deleted bot from memberships (and from the lead seat).
        for room in rt.rooms.list():
            if name in room["members"]:
                settings = None
                if (room.get("settings") or {}).get("lead") == name:
                    settings = {"lead": None}
                rt.rooms.update(room["id"], members=[m for m in room["members"] if m != name], settings=settings)
        rt.bus.publish("profile.deleted", profile=name)
        return {"deleted": name}

    @app.get("/api/team-templates")
    def team_templates() -> list[dict[str, Any]]:
        from ..team.templates import list_templates

        return list_templates()

    @app.post("/api/team-templates/{tid}/apply", status_code=201)
    def apply_team_template(tid: str, update: bool = False) -> dict[str, Any]:
        from ..team.templates import apply_template

        try:
            report = apply_template(rt, tid, update=update)
        except KeyError as exc:
            raise HTTPException(404, str(exc).strip("'")) from None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        for kind in ("created", "updated"):
            for name in report[kind]:
                rt.bus.publish(f"profile.{kind}", profile=name)
        return report

    @app.get("/api/profiles/{name}/memory")
    def profile_memory(name: str) -> dict[str, Any]:
        return views.memory_view(srv.profile(name))

    @app.get("/api/profiles/{name}/files")
    def profile_files(name: str, path: str = "", session: str | None = None) -> dict[str, Any]:
        prof = srv.profile(name)
        return files.list_dir(srv.folder(prof, session), path)

    @app.get("/api/profiles/{name}/files/content")
    def profile_file(name: str, path: str, session: str | None = None) -> dict[str, Any]:
        prof = srv.profile(name)
        return files.read_text(srv.folder(prof, session), path)

    @app.post("/api/profiles/{name}/uploads", status_code=201)
    async def upload_profile_file(name: str, request: Request, filename: str = Query(..., min_length=1, max_length=255),
                                  session: str | None = None) -> dict[str, Any]:
        """The composer's + button: the raw file body goes to `uploads/` in the conversation's folder."""
        prof = srv.profile(name)
        return files.save_upload(srv.folder(prof, session), filename, await _upload_body(request))

    @app.get("/api/fs/dirs")
    def fs_dirs(path: str = "") -> dict[str, Any]:
        """Sub-folders of a folder, for the conversation folder picker (names only, no files)."""
        return files.list_dirs(path or os.path.expanduser("~"), pland_root=rt.root)

    @app.get("/api/workspaces/recent")
    def recent_workspaces() -> list[str]:
        return workspaces.recent(rt)

    # ------------------------------------------------------------------ sessions
    @app.get("/api/profiles/{name}/sessions")
    def list_sessions(name: str, kinds: str | None = None, limit: int = Query(100, ge=1, le=500)) -> list[dict[str, Any]]:
        prof = srv.profile(name)
        kind_list = tuple(k for k in (kinds or "").split(",") if k.strip()) or None
        return [srv.session_row(prof, s) for s in SessionStore(prof).list(kinds=kind_list, limit=limit)]

    @app.post("/api/profiles/{name}/sessions", status_code=201)
    def create_session(name: str, body: SessionIn | None = None) -> dict[str, Any]:
        prof = srv.profile(name)
        body = body or SessionIn()
        if body.kind not in CHAT_KINDS:
            raise HTTPException(400, f"kind must be one of {', '.join(CHAT_KINDS)}")
        if body.kind == "bot_chat":
            sess = SessionStore(prof).get(prof.canonical_chat_id())
        else:
            sess = SessionStore(prof).create(title=body.title.strip()[:120], kind="chat")
        rt.bus.publish("session.created", profile=name, session_id=sess.id, kind=sess.kind)
        return srv.session_row(prof, sess)

    @app.get("/api/profiles/{name}/bot-chat")
    def bot_chat(name: str, folder: str | None = None, session: str | None = None) -> dict[str, Any]:
        """A bot's Bot Chat: one per working folder. `session` opens a given one, `folder` the one for that folder
        ("" / "default": the private workspace; created on first use); neither: the one used last."""
        prof = srv.profile(name)
        if session:
            sess = srv.session(prof, session)
            if sess.kind != "bot_chat":
                raise HTTPException(400, "not a Bot Chat")
            sid = sess.id
        elif folder is not None:
            sid = prof.bot_chat_id(srv.check_folder(folder))
        else:
            sid = prof.latest_bot_chat_id() or prof.canonical_chat_id()
        threads = [{**c, "preview": views.last_message_preview(prof, c["id"])} for c in prof.bot_chats()]
        return {"session_id": sid, "session": srv.session_row(prof, SessionStore(prof).get(sid)), "threads": threads}

    @app.get("/api/profiles/{name}/sessions/{sid}")
    def get_session(name: str, sid: str) -> dict[str, Any]:
        prof = srv.profile(name)
        return srv.session_row(prof, srv.session(prof, sid))

    @app.patch("/api/profiles/{name}/sessions/{sid}")
    def rename_session(name: str, sid: str, body: SessionPatch) -> dict[str, Any]:
        prof = srv.profile(name)
        srv.session(prof, sid)
        if body.title is not None:
            SessionStore(prof).update(sid, title=body.title.strip()[:120])
        if body.reasoning is not None:
            word = body.reasoning.strip().lower()
            try:
                level = None if word in {"", "reset"} else ("default" if word == "default" else reasoning.parse(word))
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from None
            SessionStore(prof).patch_meta(sid, {"reasoning": level})  # read at the start of the next run
        if body.model is not None:
            SessionStore(prof).patch_meta(sid, {"model": _chat_model(prof, body.model)})
        if body.workspace is not None:
            if srv.busy(name, sid):
                raise HTTPException(409, "this conversation is running; change its folder when it is idle")
            folder = srv.check_folder(body.workspace)
            if srv.session(prof, sid).kind == "bot_chat":  # one Bot Chat per folder: moving onto another one is refused
                other = prof.bot_chat_id(folder, create=False)
                if other and other != sid:
                    raise HTTPException(409, f"@{name} already has a Bot Chat for that folder; switch to it instead")
            SessionStore(prof).patch_meta(sid, {"workspace": folder})  # used from the next run
        rt.bus.publish("session.updated", profile=name, session_id=sid)
        return srv.session_row(prof, srv.session(prof, sid))

    @app.delete("/api/profiles/{name}/sessions/{sid}")
    def delete_session(name: str, sid: str) -> dict[str, Any]:
        prof = srv.profile(name)
        srv.session(prof, sid)
        if srv.busy(name, sid):
            raise HTTPException(409, "this conversation is running; stop it first")
        SessionStore(prof).delete(sid)
        rt.bus.publish("session.deleted", profile=name, session_id=sid)
        return {"deleted": sid}

    @app.get("/api/profiles/{name}/sessions/{sid}/messages")
    def session_messages(name: str, sid: str, after: int = 0, events_after: int = 0) -> dict[str, Any]:
        """Transcript items after message id `after`, plus the session's activity events (memory
        search, compaction, auto-approvals, …) after event id `events_after` for the UI to merge in."""
        prof = srv.profile(name)
        sess = srv.session(prof, sid)
        store = SessionStore(prof)
        records = store.records(sid, after_id=after)
        events, last_event = views.session_activity(rt.shared, name, sid, after=events_after)
        busy = srv.busy(name, sid)
        pending = [srv.hitl_row(r) for r in rt.broker.pending(profile=name) if r["session_id"] == sid]
        return {
            "session": {**sess.to_dict(), "profile": name, "reasoning": (sess.meta or {}).get("reasoning"),
                        "model": (sess.meta or {}).get("model"), **_workspace_fields(prof.workspace, sess.meta)},
            "items": views.display_items(records),
            "last_id": max([after] + [r["id"] for r in records]),
            "activity": events,
            "last_event_id": last_event,
            "todos": views.session_todos(sess),
            "busy": busy,
            "interrupted": srv.interrupted(prof, sess, busy=busy),
            "pending_hitl": pending,
        }

    @app.post("/api/profiles/{name}/sessions/{sid}/messages", status_code=202)
    def post_message(name: str, sid: str, body: TextIn) -> dict[str, Any]:
        prof = srv.profile(name)
        sess = srv.session(prof, sid)
        text = _with_attachments(body, files.check_attachments(srv.folder(prof, sid), body.attachments), "")
        if not text:
            raise HTTPException(400, "message text is empty")
        if sess.kind not in CHAT_KINDS:
            raise HTTPException(400, f"{sess.kind} sessions are read-only work logs; message the bot or its room instead")
        if not srv.busy(name, sid) and views.dangling_tool_calls(views.tail_records(prof, sid)):
            # The transcript ends in tool calls without results; a new message on top of that is
            # not a valid conversation for the model. Resuming completes them first.
            raise HTTPException(409, "this conversation was interrupted in the middle of a tool call; resume it first")
        srv.start_run(prof, sid, text)
        if not sess.title:
            SessionStore(prof).update(sid, title=" ".join(text.split())[:60])
            rt.bus.publish("session.updated", profile=name, session_id=sid)
        return {"accepted": True, "profile": name, "session_id": sid}

    @app.post("/api/profiles/{name}/sessions/{sid}/stop")
    def stop_session(name: str, sid: str) -> dict[str, Any]:
        prof = srv.profile(name)
        srv.session(prof, sid)
        return srv.stop_session(prof, sid)

    @app.post("/api/profiles/{name}/sessions/{sid}/resume", status_code=202)
    def resume_session(name: str, sid: str) -> dict[str, Any]:
        """Continue an interrupted session from its stored transcript (`Agent.resume()`)."""
        prof = srv.profile(name)
        sess = srv.session(prof, sid)
        if sess.kind == "room_member":
            raise HTTPException(400, "group turns are driven by the room; send a new message in the group instead")
        srv.start_run(prof, sid, None)
        return {"accepted": True, "profile": name, "session_id": sid}

    @app.get("/api/interrupted")
    def interrupted_sessions() -> list[dict[str, Any]]:
        """Sessions that can be resumed (marked at startup, or ending in unanswered tool calls)."""
        out = []
        for prof in rt.profiles.list():
            for sess in SessionStore(prof).list(limit=500):
                if sess.status in ("interrupted", "running") and srv.interrupted(prof, sess):
                    out.append({"profile": prof.name, "session_id": sess.id, "title": sess.title, "kind": sess.kind,
                                "updated": sess.updated})
        return out

    # ------------------------------------------------------------------ rooms
    @app.get("/api/rooms")
    def list_rooms() -> list[dict[str, Any]]:
        return [srv.room_row(r) for r in rt.rooms.list()]

    @app.post("/api/rooms", status_code=201)
    def create_room(body: RoomIn) -> dict[str, Any]:
        name = body.name.strip()
        if not name:
            raise HTTPException(400, "a group needs a name")
        members = [m.strip().lstrip("@") for m in body.members if m.strip()]
        lead = (body.lead or "").strip().lstrip("@") or None
        if lead and lead not in members:
            raise HTTPException(400, f"the lead @{lead} must be a member")
        if rt.rooms.by_name(name):
            raise HTTPException(409, f"a group named {name!r} already exists")
        return srv.room_row(rt.rooms.create(name, members, lead=lead))

    @app.get("/api/rooms/{rid}")
    def get_room(rid: str) -> dict[str, Any]:
        return srv.room_row(srv.room(rid))

    @app.patch("/api/rooms/{rid}")
    def patch_room(rid: str, body: RoomPatch) -> dict[str, Any]:
        room = srv.room(rid)
        members = None
        if body.members is not None:
            members = [m.strip().lstrip("@") for m in body.members if m.strip()]
            if not 1 <= len(members) <= 8:
                raise HTTPException(400, "a group needs 1-8 bots")
        settings: dict[str, Any] = {}
        if "lead" in body.model_fields_set:
            lead = (body.lead or "").strip().lstrip("@") or None
            if lead and lead not in (members if members is not None else room["members"]):
                raise HTTPException(400, f"the lead @{lead} must be a member")
            settings["lead"] = lead
        elif members is not None and (room.get("settings") or {}).get("lead") not in members:
            settings["lead"] = None
        for key in ("max_rounds", "max_messages"):
            val = getattr(body, key)
            if val is not None:
                if not 1 <= val <= 50:
                    raise HTTPException(400, f"{key} must be between 1 and 50")
                settings[key] = val
        folder_change = None
        if body.workspace is not None:
            if rt.rooms.drive_lock(rid).locked():
                raise HTTPException(409, "the group is working; change its shared folder when it is idle")
            folder_change = srv.check_folder(body.workspace)
        name = body.name.strip() if body.name else None
        if name and name != room["name"] and rt.rooms.by_name(name):
            raise HTTPException(409, f"a group named {name!r} already exists")
        updated = rt.rooms.update(rid, name=name, members=members, settings=settings or None, needs_you=body.needs_you)
        if body.workspace is not None:
            updated = rt.rooms.set_workspace(rid, folder_change)
        return srv.room_row(updated)

    @app.delete("/api/rooms/{rid}")
    def delete_room(rid: str) -> dict[str, Any]:
        srv.room(rid)
        if rt.rooms.drive_lock(rid).locked():
            raise HTTPException(409, "the team is working in this group; stop it first")
        rt.rooms.delete(rid)
        return {"deleted": rid}

    @app.get("/api/rooms/{rid}/messages")
    def room_messages(rid: str, after: int = 0, limit: int = Query(500, ge=1, le=2000)) -> dict[str, Any]:
        room = srv.room(rid)
        msgs = rt.rooms.messages(rid, after_id=after, limit=limit)
        return {
            "room": srv.room_row(room, preview=False),
            "messages": msgs,
            "last_id": max([after] + [m["id"] for m in msgs]),
            "pending_hitl": [srv.hitl_row(r) for r in rt.broker.pending(room_id=rid)],
        }

    @app.post("/api/rooms/{rid}/messages", status_code=202)
    def post_room_message(rid: str, body: TextIn) -> dict[str, Any]:
        room = srv.room(rid)
        text = _with_attachments(body, files.check_attachments(rt.rooms.shared_dir(rid), body.attachments), "shared/")
        if not text:
            raise HTTPException(400, "message text is empty")
        if not room["members"]:
            raise HTTPException(400, "this group has no members; add a bot first")
        queued = rt.rooms.drive_lock(rid).locked()
        result = rt.rooms.send(rid, text, hitl=rt.broker, background=True)
        return {"accepted": True, "message": result["message"], "queued": queued}

    @app.post("/api/rooms/{rid}/stop")
    def stop_room(rid: str) -> dict[str, Any]:
        srv.room(rid)
        return srv.stop_room(rid)

    @app.get("/api/rooms/{rid}/tasks")
    def room_tasks(rid: str) -> list[dict[str, Any]]:
        srv.room(rid)
        return rt.board.list(rid)

    @app.get("/api/rooms/{rid}/files")
    def room_files(rid: str, path: str = "") -> dict[str, Any]:
        srv.room(rid)
        return files.list_dir(rt.rooms.shared_dir(rid), path)

    @app.get("/api/rooms/{rid}/files/content")
    def room_file(rid: str, path: str) -> dict[str, Any]:
        srv.room(rid)
        return files.read_text(rt.rooms.shared_dir(rid), path)

    @app.post("/api/rooms/{rid}/uploads", status_code=201)
    async def upload_room_file(rid: str, request: Request,
                               filename: str = Query(..., min_length=1, max_length=255)) -> dict[str, Any]:
        """Uploads in a group go to its shared folder, where every member can read them."""
        srv.room(rid)
        return files.save_upload(rt.rooms.shared_dir(rid), filename, await _upload_body(request))

    @app.get("/api/board/{scope:path}")
    def board(scope: str, status: str | None = None) -> list[dict[str, Any]]:
        return rt.board.list(scope, status=status)

    # ------------------------------------------------------------------ HITL
    @app.get("/api/hitl")
    def list_hitl(room_id: str | None = None, profile: str | None = None, session_id: str | None = None) -> list[dict[str, Any]]:
        rows = [srv.hitl_row(r) for r in rt.broker.pending(room_id=room_id, profile=profile)]
        if session_id:
            rows = [r for r in rows if r["session_id"] == session_id or r["origin"].get("session_id") == session_id]
        return rows

    @app.post("/api/hitl/{request_id}")
    def answer_hitl(request_id: str, body: AnswerIn) -> dict[str, Any]:
        row = rt.shared.one("SELECT kind, status FROM hitl_requests WHERE id=?", (request_id,))
        if row is None:
            raise HTTPException(404, f"no HITL request {request_id}")
        if row["status"] != "pending":
            raise HTTPException(409, f"request {request_id} is already {row['status']}")
        text, choice = body.text.strip(), (body.choice or None)
        if row["kind"] == "approval":
            if choice not in APPROVAL_CHOICES:
                raise HTTPException(400, f"choice must be one of {', '.join(APPROVAL_CHOICES)}")
        else:
            if not text and choice:
                text = choice  # an option button of a clarification
            choice = None
            if not text:
                raise HTTPException(400, "an answer is required")
        try:
            return rt.broker.answer(request_id, text=text, choice=choice)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    # ------------------------------------------------------------------ events
    @app.websocket("/api/events")
    async def events(ws: WebSocket) -> None:
        await ws.accept()
        bridge = EventBridge(rt, srv.live, asyncio.get_running_loop())
        bridge.start()
        try:
            await ws.send_text(json.dumps({"type": "hello", "ts": time.time(), "version": __version__}))
            async with anyio.create_task_group() as tg:

                async def sender() -> None:
                    while True:
                        await ws.send_text(await bridge.queue.get())

                async def receiver() -> None:
                    try:
                        while True:
                            await ws.receive_text()  # client messages are ignored (keep-alive pings)
                    except WebSocketDisconnect:
                        pass
                    tg.cancel_scope.cancel()  # client went away: stop the sender too

                tg.start_soon(sender)
                tg.start_soon(receiver)
        except (WebSocketDisconnect, RuntimeError):
            pass  # the socket closed while sending
        finally:
            bridge.stop()

    # ------------------------------------------------------------------ static UI
    if STATIC_DIR.is_dir():
        app.mount("/", _RevalidatedStatic(directory=str(STATIC_DIR), html=True), name="ui")
    return app


class _RevalidatedStatic(StaticFiles):
    """The UI's files with `Cache-Control: no-cache`: browsers revalidate (a cheap 304 via ETag) instead of
    heuristically reusing a stale app.js after an update."""

    def file_response(self, *args: Any, **kwargs: Any):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response
