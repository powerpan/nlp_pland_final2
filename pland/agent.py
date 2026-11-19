"""Single-agent tool loop with planning, per-run budgets, and experience retrieval."""

from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .approvals import ApprovalGate
from .budget import Budget, BudgetExceeded
from .config import AgentSettings
from .hitl import HITLChannel
from .llm import LLMClient, LLMError, make_client
from .llm.base import Usage
from .memory import ExperienceStore
from .prompts import build_system_prompt
from .sandbox import PathPolicy
from .sessions import SessionStore
from .store import new_id
from .tools.registry import ToolContext, execute, select_tools

if TYPE_CHECKING:
    from .profiles import Profile
    from .runtime import Runtime

CONTEXT_CHAR_BUDGET = 400_000  # ~100k tokens; older context is compacted beyond this
MAX_TOOL_RESULT = 24_000
REPEAT_WARN, REPEAT_STOP = 3, 5  # identical tool call (same name + args) within one run
# No-progress guard: consecutive tool results identical to earlier results of the same tool.
STALE_NUDGE, STALE_STOP = 3, 6


@dataclass
class RunResult:
    run_id: str
    session_id: str
    profile: str
    status: str  # completed | max_iterations | budget_exceeded | loop_detected | cancelled | error
    text: str
    iterations: int = 0
    tool_calls: int = 0
    duration: float = 0.0
    usage: Usage = field(default_factory=Usage)
    error: str | None = None
    experience_ids: list[str] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "completed"

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["usage"] = dict(self.usage.__dict__)
        return d


class Cancelled(Exception):
    pass


class LoopDetected(Exception):
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
        reflect: bool | None = None,
    ):
        self.runtime = runtime
        self.profile = profile
        self.session_id = session_id
        self.hitl = hitl or runtime.default_hitl
        self.settings = settings or profile.settings()
        self.sessions = SessionStore(profile)
        self.system_extra = system_extra
        self.reflect_enabled = self.settings.reflection if reflect is None else reflect
        self._llm = llm
        self.tools = {t.name: t for t in select_tools(self.settings.toolsets, exclude_tools)}
        self.backend = runtime.backend_for(profile, self.settings)
        self.paths = PathPolicy({"": profile.workspace})
        self.used_experience_ids: set[str] = set()
        self.run_id = ""
        self.is_root = True
        self.budget = Budget(self.settings.max_run_calls, self.settings.max_run_tokens)
        self._call_sigs: dict[str, int] = {}
        self._result_sigs: dict[int, int] = {}
        self._stale_streak = 0

    # ------------------------------------------------------------------ helpers
    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = make_client(self.settings.model)
        return self._llm

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, *,
             purpose: str = "turn", **kw: Any):
        """Every model call goes through here: budget check, call, ledger entry."""
        self.budget.check(root=self.is_root)
        started = time.time()
        try:
            resp = self.llm.chat(messages, tools, **kw)
        except LLMError as exc:
            self.runtime.ledger.record(root_run=self.budget.root_run, run_id=self.run_id, profile=self.profile.name,
                                       session_id=self.session_id, purpose=purpose, model=getattr(self.llm, "model", "?"),
                                       usage=Usage(), duration=time.time() - started, ok=False, error=str(exc))
            raise
        self.budget.charge(resp.usage)
        self.runtime.ledger.record(root_run=self.budget.root_run, run_id=self.run_id, profile=self.profile.name,
                                   session_id=self.session_id, purpose=purpose, model=resp.model or getattr(self.llm, "model", "?"),
                                   usage=resp.usage, duration=time.time() - started, ok=True)
        return resp

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

    # ------------------------------------------------------------------ context
    def _llm_messages(self) -> list[dict[str, Any]]:
        sess = self.sessions.get(self.session_id)
        upto = int(sess.meta.get("compacted_upto") or 0)
        records = self.sessions.records(self.session_id)
        msgs = [r["message"] for r in records if r["id"] > upto or r["message"].get("role") == "system"]
        if upto and sess.meta.get("summary"):
            sys_msgs = [m for m in msgs if m.get("role") == "system"][:1]
            rest = [m for m in msgs if m.get("role") != "system"]
            summary = "[Summary of the earlier part of this conversation]\n" + sess.meta["summary"]
            if sess.meta.get("todos"):  # the working plan survives compaction (as in Hermes)
                from .tools.plan import render

                summary += "\n\n[Your task list, preserved across compaction]\n" + render(sess.meta["todos"])
            msgs = sys_msgs + [{"role": "user", "content": summary},
                               {"role": "assistant", "content": "Understood. Continuing from that summary."}] + rest
        return close_tool_calls(msgs)

    def _maybe_compact(self) -> None:
        msgs = self._llm_messages()
        size = sum(len(json.dumps(m, ensure_ascii=False)) for m in msgs)
        if size <= CONTEXT_CHAR_BUDGET:
            return
        records = self.sessions.records(self.session_id)
        sess = self.sessions.get(self.session_id)
        upto = int(sess.meta.get("compacted_upto") or 0)
        live = [r for r in records if r["id"] > upto and r["message"].get("role") != "system"]
        # cut at a user-message boundary roughly in the middle so tool-call pairs stay intact
        half = len(live) // 2
        cut_idx = next((i for i in range(half, len(live)) if live[i]["message"].get("role") == "user"), None)
        if not cut_idx:
            return
        old = live[:cut_idx]
        digest = "\n".join(_digest_line(r["message"]) for r in old)[-120_000:]
        prev = sess.meta.get("summary") or ""
        prompt = [
            {"role": "system", "content": "You compress agent transcripts. Keep goals, decisions, facts learned, files touched, "
                                          "open problems and the user's preferences. Be dense; max 600 words."},
            {"role": "user", "content": (f"Earlier summary:\n{prev}\n\n" if prev else "") + f"Transcript to fold in:\n{digest}"},
        ]
        try:
            summary = self.chat(prompt, purpose="compaction", max_tokens=1500).content.strip()
        except (LLMError, BudgetExceeded):
            summary = (prev + "\n" + digest[-4000:]).strip()
        meta = dict(sess.meta)
        meta["compacted_upto"] = old[-1]["id"]
        meta["summary"] = summary
        self.sessions.update(self.session_id, meta=meta)
        self.emit("context.compacted", folded=len(old))

    # ------------------------------------------------------------------ experience
    def _with_experience(self, text: str, query: str | None = None) -> tuple[str, list[str]]:
        if "memory" not in self.settings.toolsets or self.settings.experience_top_k <= 0:
            return text, []
        store = ExperienceStore(self.profile)
        hits = store.search(query or text, self.settings.experience_top_k)
        if not hits:
            return text, []
        ids = [e.id for e, _ in hits]
        store.mark_used(ids, self.session_id)
        self.used_experience_ids.update(ids)
        block = "\n\n".join(e.render() for e, _ in hits)
        self.emit("experience.retrieved", ids=ids, scores=[s for _, s in hits])
        return (f"{text}\n\n<relevant_past_experience note=\"from your own earlier tasks; apply lessons if relevant, ignore otherwise\">\n"
                f"{block}\n</relevant_past_experience>"), ids

    # ------------------------------------------------------------------ main loop
    def run(self, text: str, *, meta: dict[str, Any] | None = None,
            max_iterations: int | None = None) -> RunResult:
        self.run_id = new_id("r_")
        start = time.time()
        usage = Usage()
        iterations = tool_calls = 0
        lock = self.runtime.session_lock(self.profile.name, self.session_id)
        if not lock.acquire(timeout=1800):
            return RunResult(self.run_id, self.session_id, self.profile.name, "error", "", error="session is busy")
        self.runtime.clear_cancel(self.profile.name, self.session_id)
        self.budget = Budget(self.settings.max_run_calls, self.settings.max_run_tokens)
        self._call_sigs.clear()
        self._result_sigs.clear()
        self._stale_streak = 0
        self.used_experience_ids.clear()
        final_text = ""
        status = "completed"
        error = None
        try:
            self.sessions.update(self.session_id, status="running")
            self._ensure_system()
            self.emit("run.started", text=text[:2000])
            content, _ = self._with_experience(text)
            self.sessions.append(self.session_id, {"role": "user", "content": content},
                                 meta={"display": text, **(meta or {})})
            iterations, tool_calls, final_text, status = self._loop(usage, max_iterations or self.settings.max_iterations)
        except Cancelled:
            status, final_text = "cancelled", "(stopped by user)"
            self.sessions.append(self.session_id, {"role": "assistant", "content": final_text}, meta={"cancelled": True})
        except BudgetExceeded as exc:
            status, error = "budget_exceeded", str(exc)
            final_text = f"Stopped: {exc}. Partial work may exist in the workspace."
            self.sessions.append(self.session_id, {"role": "assistant", "content": final_text}, meta={"error": True})
        except LoopDetected as exc:
            status, error = "loop_detected", str(exc)
            self.emit("loop.detected", reason=str(exc))
            try:  # still give the user a report of what was done
                final_text = self._wrap_up(usage, f"Loop guard: {exc}.")
            except Exception:
                final_text = f"Stopped: {exc}"
                self.sessions.append(self.session_id, {"role": "assistant", "content": final_text}, meta={"error": True})
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
                           time.time() - start, usage, error, budget=self.budget.snapshot())
        trivial = final_text.strip().lower().strip(" .") in {"[pass]", "pass", "[silent]"}
        if self.reflect_enabled and status != "cancelled" and text.strip() and not trivial:
            try:
                from .reflection import reflect

                result.experience_ids = reflect(self, text, result)
            except Exception as exc:  # reflection must never break the task result
                self.emit("reflection.failed", error=str(exc))
        self.emit("run.finished", status=status, text=final_text[:4000], iterations=iterations, tool_calls=tool_calls,
                  duration=round(result.duration, 2), error=error)
        return result

    def _run_tool_calls(self, calls: list[dict[str, Any]]) -> int:
        n = 0
        for i, tc in enumerate(calls):
            try:
                self._check_cancel()
            except Cancelled:
                for rest in calls[i:]:  # every call gets a result, so the transcript stays valid for the API
                    self.sessions.append(self.session_id, {"role": "tool", "tool_call_id": rest["id"],
                                                           "content": "(cancelled by the user before this call ran)"},
                                         meta={"tool": rest["function"]["name"], "cancelled": True})
                raise
            name = tc["function"]["name"]
            raw = tc["function"].get("arguments") or "{}"
            t = self.tools.get(name)
            self.emit("tool.started", tool=name, call_id=tc["id"], args=_preview_args(raw))
            started = time.time()
            sig = name + "\x00" + " ".join(raw.split())
            self._call_sigs[sig] = self._call_sigs.get(sig, 0) + 1
            repeats = self._call_sigs[sig]
            if repeats >= REPEAT_STOP:
                raise LoopDetected(f"the same {name} call was repeated {repeats} times with identical arguments")
            if repeats >= REPEAT_WARN:
                out = (f"ERROR: you already made this exact {name} call {repeats - 1} times with identical arguments and "
                       f"got the same result. Do not repeat it; change your approach or finish with what you have.")
            elif t is None:
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
            out = self._progress_guard(name, out)
            self.sessions.append(self.session_id, {"role": "tool", "tool_call_id": tc["id"], "content": out},
                                 meta={"tool": name, "duration": round(time.time() - started, 3)})
            self.emit("tool.finished", tool=name, call_id=tc["id"], ok=not out.startswith("ERROR"),
                      preview=out[:600], duration=round(time.time() - started, 2))
            n += 1
        return n

    def _progress_guard(self, name: str, out: str) -> str:
        """Detect a run that keeps getting the same results (near-identical calls, cosmetic variations)."""
        key = hash((name, out))
        seen = self._result_sigs.get(key, 0)
        self._result_sigs[key] = seen + 1
        self._stale_streak = self._stale_streak + 1 if seen >= 1 else 0
        if self._stale_streak >= STALE_STOP:
            raise LoopDetected(f"the last {self._stale_streak} tool results repeated earlier results (no progress)")
        if self._stale_streak >= STALE_NUDGE:
            out += (f"\n\n[progress guard] The last {self._stale_streak} tool results were identical to earlier ones — you are "
                    "not making progress. Stop repeating checks; either change approach or write your final answer now.")
        return out

    def _loop(self, usage: Usage, max_iter: int) -> tuple[int, int, str, str]:
        iterations = tool_calls = 0
        schemas = [t.schema() for t in self.tools.values()]
        while iterations < max_iter:
            self._check_cancel()
            if self.is_root and self.budget.near_limit:
                # The last 10% of the run budget is reserved for the root agent's own summary.
                return iterations, tool_calls, self._wrap_up(usage, "The run budget is nearly exhausted."), "budget_exceeded"
            self._maybe_compact()
            iterations += 1
            if max_iter >= 8 and iterations == int(max_iter * 0.8):
                # Budget checkpoint (after Hermes' kanban workers): a chance to verify and wrap up before the hard cap.
                left = max_iter - iterations + 1
                self.sessions.append(self.session_id, {"role": "user", "content": (
                    f"[system] Step budget checkpoint: {left} of {max_iter} steps left. Prioritise finishing and verifying "
                    "the core deliverable; drop nice-to-have extras; then give your final answer.")}, meta={"checkpoint": True})
                self.emit("budget.checkpoint", steps_left=left)
            self.emit("llm.request", iteration=iterations)
            # Greedy decoding (temperature 0) can lock into repetition; loosen it while the guard sees no progress.
            temp = 0.7 if self._stale_streak >= 2 else None
            resp = self.chat(self._llm_messages(), schemas or None, temperature=temp)
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
        return iterations, tool_calls, self._wrap_up(usage, "The iteration limit was reached."), "max_iterations"

    def _wrap_up(self, usage: Usage, why: str) -> str:
        """Ask for a final report without tools so the user still gets a summary."""
        self.sessions.append(self.session_id, {"role": "user", "content": f"[system] {why} Stop using tools and report what "
                                               "you completed, what is unfinished, and why."})
        resp = self.chat(self._llm_messages(), None, purpose="wrapup")
        usage.add(resp.usage)
        self.sessions.append(self.session_id, resp.to_message())
        return resp.content


def close_tool_calls(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chat APIs reject an assistant tool call that is not followed by its result. A transcript can
    contain such calls after a crash or cancellation mid-batch; give them a synthetic result in the
    model's view (the stored transcript is left as it happened)."""
    out: list[dict[str, Any]] = []
    open_ids: list[tuple[str, str]] = []

    def flush() -> None:
        for cid, name in open_ids:
            out.append({"role": "tool", "tool_call_id": cid, "content": f"(no result: the {name} call was interrupted)"})
        open_ids.clear()

    for m in msgs:
        role = m.get("role")
        if role == "tool":
            open_ids[:] = [(cid, n) for cid, n in open_ids if cid != m.get("tool_call_id")]
            out.append(m)
            continue
        flush()
        out.append(m)
        if role == "assistant" and m.get("tool_calls"):
            open_ids.extend((tc["id"], tc["function"]["name"]) for tc in m["tool_calls"])
    flush()
    return out


def _preview_args(raw: str, limit: int = 400) -> str:
    raw = raw or ""
    return raw if len(raw) <= limit else raw[:limit] + "…"


def _digest_line(m: dict[str, Any]) -> str:
    role = m.get("role")
    if role == "tool":
        return f"[tool result] {str(m.get('content', ''))[:600]}"
    if role == "assistant" and m.get("tool_calls"):
        calls = ", ".join(f"{tc['function']['name']}({_preview_args(tc['function'].get('arguments', ''), 200)})" for tc in m["tool_calls"])
        return f"[assistant] {str(m.get('content') or '')[:400]} -> {calls}"
    return f"[{role}] {str(m.get('content', ''))[:1500]}"

