"""Single-agent model, tool and transcript loop."""

from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .approvals import ApprovalGate
from .config import AgentSettings
from .hitl import HITLChannel
from .llm import LLMClient, LLMError, make_client
from .llm.base import Usage
from .prompts import build_system_prompt
from .sandbox import PathPolicy
from .sessions import SessionStore
from .store import new_id
from .tools.registry import ToolContext, execute, select_tools

if TYPE_CHECKING:
    from .profiles import Profile
    from .runtime import Runtime

MAX_TOOL_RESULT = 24_000


@dataclass
class RunResult:
    run_id: str
    session_id: str
    profile: str
    status: str  # completed | max_iterations | cancelled | error
    text: str
    iterations: int = 0
    tool_calls: int = 0
    duration: float = 0.0
    usage: Usage = field(default_factory=Usage)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "completed"

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["usage"] = dict(self.usage.__dict__)
        return d


class Cancelled(Exception):
    pass


class Agent:
    def __init__(
        self,
        runtime: "Runtime",
        profile: "Profile",
        session_id: str,
        *,
        hitl: HITLChannel | None = None,
        exclude_tools: set[str] | None = None,
        llm: LLMClient | None = None,
        settings: AgentSettings | None = None,
        system_extra: str | None = None,
    ):
        self.runtime = runtime
        self.profile = profile
        self.session_id = session_id
        self.hitl = hitl or runtime.default_hitl
        self.settings = settings or profile.settings()
        self.sessions = SessionStore(profile)
        self.system_extra = system_extra
        self._llm = llm
        self.tools = {t.name: t for t in select_tools(self.settings.toolsets, exclude_tools)}
        self.backend = runtime.backend_for(profile, self.settings)
        self.paths = PathPolicy({"": profile.workspace})
        self.run_id = ""

    # ------------------------------------------------------------------ helpers
    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = make_client(self.settings.model)
        return self._llm

    def emit(self, type: str, **data: Any) -> None:
        self.runtime.bus.publish(type, profile=self.profile.name, session_id=self.session_id,
                                 run_id=self.run_id, **data)

    def _context(self, tool_call_id: str | None = None) -> ToolContext:
        gate = ApprovalGate(self.profile, self.settings.approvals, self.hitl, self.session_id,
                            run_id=self.run_id, publish=self.runtime.bus.publish)
        return ToolContext(
            runtime=self.runtime, agent=self, profile=self.profile, settings=self.settings, session_id=self.session_id,
            run_id=self.run_id, backend=self.backend, paths=self.paths, hitl=self.hitl, approvals=gate,
            tool_call_id=tool_call_id,
        )

    def _system_prompt(self) -> str:
        return build_system_prompt(
            self.profile, backend_name=self.backend.name,
            extra=self.system_extra, tool_names=set(self.tools),
        )

    def _ensure_system(self) -> None:
        if not self.sessions.messages(self.session_id):
            self.sessions.append(self.session_id, {"role": "system", "content": self._system_prompt()})

    def _check_cancel(self) -> None:
        if self.runtime.is_cancelled(self.profile.name, self.session_id):
            raise Cancelled()

    # ------------------------------------------------------------------ main loop
    def run(self, text: str, *, meta: dict[str, Any] | None = None, max_iterations: int | None = None) -> RunResult:
        self.run_id = new_id("r_")
        start = time.time()
        usage = Usage()
        iterations = tool_calls = 0
        lock = self.runtime.session_lock(self.profile.name, self.session_id)
        if not lock.acquire(timeout=1800):
            return RunResult(self.run_id, self.session_id, self.profile.name, "error", "", error="session is busy")
        self.runtime.clear_cancel(self.profile.name, self.session_id)
        final_text = ""
        status = "completed"
        error = None
        try:
            self.sessions.update(self.session_id, status="running")
            self._ensure_system()
            self.emit("run.started", text=text[:2000])
            self.sessions.append(self.session_id, {"role": "user", "content": text},
                                 meta={"display": text, **(meta or {})})
            iterations, tool_calls, final_text, status = self._loop(usage, max_iterations or self.settings.max_iterations)
        except Cancelled:
            status, final_text = "cancelled", "(stopped by user)"
            self.sessions.append(self.session_id, {"role": "assistant", "content": final_text}, meta={"cancelled": True})
        except LLMError as exc:
            status, error = "error", str(exc)
            final_text = f"Model error: {exc}"
            self.sessions.append(self.session_id, {"role": "assistant", "content": final_text}, meta={"error": True})
        except Exception as exc:  # crash: record it, keep the process alive
            status, error = "error", f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=6)}"
            final_text = f"Internal error: {type(exc).__name__}: {exc}"
            self.sessions.append(self.session_id, {"role": "assistant", "content": final_text}, meta={"error": True})
        finally:
            self.sessions.update(self.session_id, status="error" if status == "error" else "idle")
            lock.release()
        result = RunResult(self.run_id, self.session_id, self.profile.name, status, final_text, iterations, tool_calls,
                           time.time() - start, usage, error)
        self.emit("run.finished", status=status, text=final_text[:4000], iterations=iterations, tool_calls=tool_calls,
                  duration=round(result.duration, 2), error=error)
        return result

    def _run_tool_calls(self, calls: list[dict[str, Any]]) -> int:
        n = 0
        for tc in calls:
            self._check_cancel()
            name = tc["function"]["name"]
            raw = tc["function"].get("arguments") or "{}"
            t = self.tools.get(name)
            self.emit("tool.started", tool=name, call_id=tc["id"], args=_preview_args(raw))
            started = time.time()
            if t is None:
                out = f"ERROR: unknown tool '{name}'. Available: {', '.join(sorted(self.tools))}"
            else:
                try:
                    args = json.loads(raw) if raw.strip() else {}
                    if not isinstance(args, dict):
                        raise ValueError("arguments must be a JSON object")
                except (json.JSONDecodeError, ValueError) as exc:
                    out = f"ERROR: invalid JSON arguments for {name}: {exc}"
                else:
                    out = execute(t, self._context(tc["id"]), args)
            if len(out) > MAX_TOOL_RESULT:
                out = out[: MAX_TOOL_RESULT // 2] + f"\n... [{len(out) - MAX_TOOL_RESULT} chars truncated] ...\n" + out[-MAX_TOOL_RESULT // 2 :]
            self.sessions.append(self.session_id, {"role": "tool", "tool_call_id": tc["id"], "content": out},
                                 meta={"tool": name, "duration": round(time.time() - started, 3)})
            self.emit("tool.finished", tool=name, call_id=tc["id"], ok=not out.startswith("ERROR"),
                      preview=out[:600], duration=round(time.time() - started, 2))
            n += 1
        return n

    def _loop(self, usage: Usage, max_iter: int) -> tuple[int, int, str, str]:
        iterations = tool_calls = 0
        schemas = [t.schema() for t in self.tools.values()]
        while iterations < max_iter:
            self._check_cancel()
            iterations += 1
            self.emit("llm.request", iteration=iterations)
            resp = self.llm.chat(self.sessions.messages(self.session_id), schemas or None)
            usage.add(resp.usage)
            msg = resp.to_message()
            self.sessions.append(self.session_id, msg, meta={"usage": resp.usage.__dict__, "finish": resp.finish_reason})
            self.emit("assistant.message", content=resp.content[:4000], tool_calls=[
                {"name": tc.name, "args": _preview_args(tc.arguments)} for tc in resp.tool_calls])
            if not resp.tool_calls:
                if not resp.content.strip() and resp.finish_reason == "length":
                    continue
                return iterations, tool_calls, resp.content, "completed"
            tool_calls += self._run_tool_calls(msg["tool_calls"])
        # Out of iterations: ask for a wrap-up without tools so the user still gets a summary.
        self.sessions.append(self.session_id, {"role": "user", "content": "[system] Iteration limit reached. Stop using tools and "
                                               "report what you completed, what is unfinished, and why."})
        resp = self.llm.chat(self.sessions.messages(self.session_id), None)
        usage.add(resp.usage)
        self.sessions.append(self.session_id, resp.to_message())
        return iterations, tool_calls, resp.content, "max_iterations"


def _preview_args(raw: str, limit: int = 400) -> str:
    raw = raw or ""
    return raw if len(raw) <= limit else raw[:limit] + "…"
