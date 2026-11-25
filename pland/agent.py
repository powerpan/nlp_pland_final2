"""The agent execution loop.

One `Agent` drives one session of one profile:

    user task ──► [retrieve relevant experiences] ──► LLM ──► tool calls ──► results ──► LLM ──► … ──► answer
                                                                                         └─► reflection → experience store

Tool calls that need a human (ask_user, approvals) block inside the tool; the run therefore resumes
in place once answered. Because every message is persisted as it happens, a run interrupted by a
crash or restart can be continued with `Agent.resume()`, which completes dangling tool calls first.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import traceback
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from .approvals import ApprovalGate
from .budget import Budget, BudgetExceeded
from .config import AgentSettings
from .hitl import HITLChannel
from .llm import LLMClient, LLMError, make_client
from . import workspace as workspaces
from .llm import reasoning
from .llm.base import Usage
from .memory import ExperienceStore
from .prompts import build_system_prompt, current_output_rules
from .sandbox import PathPolicy
from .sessions import SessionStore
from .store import loads, new_id
from .tools.registry import ToolContext, execute, select_tools

if TYPE_CHECKING:
    from .team.review import ReviewTurn
    from .profiles import Profile
    from .runtime import Runtime

# Tools a temporary subagent never gets (it has no human channel and no long-term identity).
SUBAGENT_EXCLUDE = {"ask_user", "memory", "skill_save", "message_agent", "team_tasks"}
# Tools that change state; refused during discussion-only room turns. (Refused at call time rather than removed
# from the schema, so the session's prompt prefix — and DeepSeek's cache — stays stable across turns.)
MUTATING_TOOLS = {"write_file", "edit_file", "delete_file", "run_shell", "run_python", "run_checks", "git_status", "git_commit",
                  "git_push", "delegate_task", "message_agent", "share_file", "memory", "skill_save",
                  # also no web research in a discussion turn: doing the work there is shallow (a real run posted a
                  # misread version number); research goes through delegation, where it is done and verified properly
                  "web_search", "web_fetch"}
MAX_TOOL_RESULT = 24_000
PRUNED_TOOL_OUTPUT = "[Old tool output cleared to save context space — re-run the tool if you need it again]"
SUMMARY_PROMPT = """You compress the earlier part of an AI agent's working conversation so it can continue the task.
Write a dense Markdown summary with exactly these sections (omit nothing important, invent nothing):
## Goal
## Constraints & Preferences
## Progress
### Done
### In Progress
### Blocked
## Key Decisions
## Relevant Files
## Next Steps
## Critical Context
(specific values, commands, error messages, IDs and results the agent will need verbatim)
If a previous summary is given, update it: move finished items to Done, add new progress, drop what became irrelevant.
Max ~900 words."""
REPEAT_WARN, REPEAT_STOP = 3, 5  # identical tool call (same name + args) within one run
# No-progress guard: consecutive tool results identical to earlier results of the same tool.
STALE_NUDGE, STALE_STOP = 3, 6
# A plan (todo) with open items that has not been touched for this many steps gets one reminder: a researcher once
# wrote 7 items at step 1 and worked 55 steps without ticking any, so the UI showed 0/7 throughout.
PLAN_STALE_STEPS = 8
# Share of the run budget after which the root agent is told what is left (once), so it plans the rest to fit.
BUDGET_NOTE_AT = 0.7


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
    # Set when the run never got the session lock: "cancelled" (stopped while waiting), "timeout" (the wait ran past
    # its deadline) or "deadlock" (the session is held by a run that is itself waiting on this run's caller). Nothing
    # was written to the session in these cases.
    not_started: str | None = None

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


# A run waits for its session lock in slices of this many seconds, re-checking stop requests and wait cycles in between.
LOCK_WAIT_SLICE = 0.25
LOCK_WAIT_MAX = 1800.0  # overall cap on the wait when the caller gives no deadline


class _LockRegistry:
    """Who holds and who waits for each session lock (one registry per Runtime).

    The delegation chain only catches A→B→A within one chain. Two independent chains (A messages B while B messages
    A) would otherwise wait on each other's session lock. The wait-for graph has two kinds of edges: a run waiting for a
    session points at the run holding it, and a caller blocked in delegate_task/message_agent points at its child
    run. A new wait that would close a cycle is refused at once."""

    def __init__(self) -> None:
        self.guard = threading.Lock()
        self.holder: dict[tuple[str, str], str] = {}  # (profile, session) -> run id holding its lock
        self.waiting: dict[str, tuple[str, str]] = {}  # run id -> (profile, session) it is waiting for
        self.parent: dict[str, str] = {}  # run id -> run id of the caller blocked on it

    def would_deadlock(self, run_id: str, key: tuple[str, str]) -> list[str] | None:
        """The run ids on the cycle if `run_id` waited for `key` (call with `guard` held), else None."""
        start = self.holder.get(key)
        if start is None:
            return None
        children: dict[str, list[str]] = {}
        for child, parent in self.parent.items():
            children.setdefault(parent, []).append(child)
        stack, seen = [(start, [start])], {start}
        while stack:
            node, path = stack.pop()
            if node == run_id:
                return path
            nxt = list(children.get(node, []))
            waits = self.waiting.get(node)
            if waits is not None and waits in self.holder:
                nxt.append(self.holder[waits])
            for n in nxt:
                if n not in seen:
                    seen.add(n)
                    stack.append((n, path + [n]))
        return None


_REGISTRY_GUARD = threading.Lock()


def lock_registry(runtime: Any) -> _LockRegistry:
    with _REGISTRY_GUARD:
        reg = getattr(runtime, "_session_lock_registry", None)
        if reg is None:
            reg = _LockRegistry()
            runtime._session_lock_registry = reg
        return reg


# DeepSeek's own tool-call markup, which the model sometimes writes as plain text instead of a real tool call
# (seen in a wrap-up report: "<｜｜DSML｜｜ calls> <｜｜DSML｜｜ invoke name=...>").
# A first reply that only announces work ("I'll start by setting up the plan…") and stops without a tool call.
# Seen in a real hard-suite run: the loop took the announcement as the final answer and nothing was built.
ANNOUNCE_ONLY = re.compile(
    r"^\s*(i'll|i will|i'm going to|i am going to|let me|let's|first,? i|now,? i|next,? i|i'm starting|i'll start|"
    r"我(先|會|将|將|來|来|現在|这就|這就)|讓我|让我|首先)", re.IGNORECASE)
TOOL_MARKUP = re.compile(r"<[|｜]{1,2}\s*DSML\s*[|｜]{1,2}|<[|｜]tool[▁_ ]calls?[▁_ ]begin[|｜]>|<[|｜]tool[▁_ ]call[▁_ ]begin[|｜]>")


WRITE_TOOLS = ("write_file", "edit_file")


def strip_tool_markup(text: str) -> str:
    """Remove leaked tool-call markup (from the first marker on: it is never prose)."""
    m = TOOL_MARKUP.search(text or "")
    return (text[:m.start()] if m else text or "").rstrip()


class WorkspaceUnavailable(Exception):
    """The folder chosen for this conversation is gone; the run stops instead of working elsewhere."""


class Agent:
    def __init__(
        self,
        runtime: "Runtime",
        profile: "Profile",
        session_id: str,
        *,
        hitl: HITLChannel | None = None,
        room_id: str | None = None,
        role: str = "main",  # main | delegate | subagent
        depth: int = 0,
        chain: list[str] | None = None,
        exclude_tools: set[str] | None = None,
        llm: LLMClient | None = None,
        settings: AgentSettings | None = None,
        system_extra: str | None = None,
        reflect: bool | None = None,
        budget: Budget | None = None,
        budget_root: bool | None = None,
        discussion_only: bool = False,
        caller: "Agent | None" = None,
        review_turn: "ReviewTurn | None" = None,
    ):
        self.runtime = runtime
        self.review_turn = review_turn
        self.review_spec: dict[str, Any] | None = None
        # The agent whose tool call (delegate_task, message_agent) started this one and is blocked until it returns:
        # a stop on the caller also stops this run, and lock waits are checked for cycles through it.
        self.caller = caller
        self.deadline: float | None = None  # absolute time after which the current run stops (message_agent timeout)
        self.timed_out = False
        self._deadline_cancelled = False  # the deadline timer set this session's stop flag
        self.profile = profile
        self.session_id = session_id
        self.hitl = hitl or runtime.default_hitl
        self.room_id = room_id
        self.role = role
        self.depth = depth
        self.chain = list(chain or [])
        self.settings = settings or profile.settings()
        self.sessions = SessionStore(profile)
        self.system_extra = system_extra
        self.reflect_enabled = self.settings.reflection if reflect is None else reflect
        self._llm = llm
        self._llm_injected = llm is not None
        exclude = set(exclude_tools or set())
        if role == "subagent":
            exclude |= SUBAGENT_EXCLUDE
        if depth >= self.settings.max_delegation_depth:
            exclude |= {"delegate_task", "message_agent"}
        if not runtime.profiles.list(bots_only=True):
            exclude |= {"message_agent"}
        if getattr(budget, "fast", None) is None:
            exclude |= {"run_checks"}  # only a Fast Mode group drive has card checks to run
        self.tools = {t.name: t for t in select_tools(self.settings.toolsets, exclude)}
        # The conversation's folder (pland/workspace.py): one chosen for this session, else the private workspace.
        try:
            meta = self.sessions.get(session_id).meta
        except KeyError:
            meta = {}
        self.workspace, self.workspace_error = workspaces.resolve(profile.workspace, meta)
        self.custom_workspace = self.workspace != profile.workspace.resolve()
        self.backend = runtime.backend_for(profile, self.settings, self.workspace)
        roots = {"": self.workspace}
        self.room = runtime.rooms.get(room_id) if room_id else None
        if self.room:
            roots["shared"] = runtime.rooms.shared_dir(room_id)
        self.paths = PathPolicy(roots)
        self.used_experience_ids: set[str] = set()
        self.run_id = ""
        # Delegates/subagents share the budget of the run that spawned them; a top-level run owns one. A room lead
        # shares its drive's budget yet is that drive's root (budget_root=True): it keeps the last 10% for its summary.
        self.is_root = budget is None if budget_root is None else budget_root
        self.budget = budget or Budget(self.settings.max_run_calls, self.settings.max_run_tokens)
        self._call_sigs: dict[str, int] = {}
        self._result_sigs: dict[int, int] = {}
        self._written_content_sigs: set[int] = set()
        self._stale_streak = 0
        self._hot_turns = 0  # remaining iterations sampled at a higher temperature to break repetition
        self.discussion_only = discussion_only
        self.reasoning: str | None = None  # this chat's thinking intensity override ("off" or a level), set per run
        self.model_override: str | None = None  # this chat's model override, set per run
        self._wrote_file = False  # a file was written in this run (the step checkpoint looks at it)
        self.written_paths: list[str] = []  # files written in this run, as given to the tool (returned to a delegator)
        self._deliverables: list[str] = []  # output files a delegator asked for (session meta "deliverables")
        self._write_only_steps = 0  # steps left during which only file-writing tools are offered
        self._step = 0  # current step of the run
        self._plan_step = 0  # step of the last `todo` call (the stale-plan reminder counts from it)
        self._plan_nudged = False
        self._budget_noted = False  # the root agent was told that most of the run budget is spent

    # ------------------------------------------------------------------ helpers
    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = make_client(self.settings.model)
        return self._llm

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, *,
             purpose: str = "turn", **kw: Any):
        """Every model call goes through here: budget check, call, ledger entry. Reflection (learning after a run,
        often in the background while the run that spawned it goes on) is recorded in the ledger but not charged to
        the run's caps, so it never takes calls away from the task."""
        charged = purpose != "reflection"
        if charged:
            self.budget.check(root=self.is_root)
        started = time.time()
        try:
            resp = self.llm.chat(messages, tools, **kw)
        except LLMError as exc:
            self.runtime.ledger.record(root_run=self.budget.root_run, run_id=self.run_id, profile=self.profile.name,
                                       session_id=self.session_id, purpose=purpose, model=getattr(self.llm, "model", "?"),
                                       usage=Usage(), duration=time.time() - started, ok=False, error=str(exc))
            raise
        if charged:
            self.budget.charge(resp.usage)
        self.runtime.ledger.record(root_run=self.budget.root_run, run_id=self.run_id, profile=self.profile.name,
                                   session_id=self.session_id, purpose=purpose, model=resp.model or getattr(self.llm, "model", "?"),
                                   usage=resp.usage, duration=time.time() - started, ok=True)
        return resp

    def emit(self, type: str, **data: Any) -> None:
        self.runtime.bus.publish(type, profile=self.profile.name, session_id=self.session_id, room_id=self.room_id,
                                 run_id=self.run_id, **data)

    def _context(self, tool_call_id: str | None = None) -> ToolContext:
        gate = ApprovalGate(self.profile, self.settings.approvals, self.hitl, self.session_id, room_id=self.room_id,
                            run_id=self.run_id, publish=self.runtime.bus.publish,
                            guard=lambda msgs: self.chat(msgs, None, purpose="approval", max_tokens=8, temperature=0,
                                                         thinking=False).content)
        return ToolContext(
            runtime=self.runtime, agent=self, profile=self.profile, settings=self.settings, session_id=self.session_id,
            run_id=self.run_id, backend=self.backend, paths=self.paths, hitl=self.hitl, approvals=gate,
            room_id=self.room_id, depth=self.depth, chain=self.chain + [self.profile.name], tool_call_id=tool_call_id,
        )

    def _system_prompt(self) -> str:
        return build_system_prompt(
            self.runtime, self.profile, role=self.role, room=self.room, backend_name=self.backend.name,
            extra=self.system_extra, tool_names=set(self.tools),
            workspace=self.workspace if self.custom_workspace else None,
        )

    def _ensure_system(self) -> None:
        if not self.sessions.messages(self.session_id):
            self.sessions.append(self.session_id, {"role": "system", "content": self._system_prompt()})

    def _note_workspace(self) -> None:
        """Tell the model when this conversation's folder changed since its last turn. The stored system prompt
        names the folder it started in and is never rewritten (that would break the prompt cache)."""
        current = str(self.workspace)
        seen = self.sessions.get(self.session_id).meta.get("workspace_seen")
        if seen and seen != current:
            self.sessions.append(self.session_id, {"role": "user", "content": (
                f"[system] The working folder of this conversation is now {current} (it was {seen}). Paths are "
                "relative to the new folder; files in the previous one are no longer accessible.")},
                meta={"workspace_note": True})
            self.emit("workspace.changed", workspace=current, previous=seen)
        if seen != current:
            self.sessions.patch_meta(self.session_id, {"workspace_seen": current})

    def _cancel_requested(self) -> bool:
        """A stop for this session, or for a caller blocked on this run (its stop must reach the work it waits for)."""
        agent: Agent | None = self
        seen: set[int] = set()
        while agent is not None and id(agent) not in seen:
            seen.add(id(agent))
            if agent.runtime.is_cancelled(agent.profile.name, agent.session_id):
                return True
            agent = agent.caller
        return False

    def _check_cancel(self) -> None:
        if self.deadline is not None and time.time() >= self.deadline:
            self.timed_out = True
            raise Cancelled()
        if self._cancel_requested():
            raise Cancelled()

    def _acquire_session(self, lock: threading.Lock, deadline: float) -> tuple[str, str] | None:
        """Take the session lock. Returns None once held, else (reason, message) with reason "cancelled", "timeout"
        or "deadlock". The wait goes in short slices so a stop (of this session or of a caller) ends it promptly,
        and a wait that would close a cycle with other waiting runs is refused instead of blocking."""
        key = (self.profile.name, self.session_id)
        reg = lock_registry(self.runtime)
        if lock.acquire(blocking=False):
            # The session was idle: a stop request left over from an earlier run is stale.
            self.runtime.clear_cancel(*key)
            with reg.guard:
                reg.holder[key] = self.run_id
            return None
        # Busy: the stop flag now belongs to the run holding the session (or to this wait); it is not cleared.
        try:
            while True:
                if self._cancel_requested():
                    return "cancelled", "stopped while waiting for the session to become free"
                with reg.guard:
                    cycle = reg.would_deadlock(self.run_id, key)
                    if cycle is None:
                        reg.waiting[self.run_id] = key
                if cycle is not None:
                    return "deadlock", (
                        f"@{self.profile.name}'s session {self.session_id} is busy with a run that is itself waiting, "
                        "directly or through its own delegations and messages, for the conversation that sent this "
                        "one (a cross-chain message cycle). Waiting would deadlock, so this was refused; answer in your "
                        "own reply instead, or try again after that run has finished.")
                remaining = deadline - time.time()
                if remaining <= 0:
                    return "timeout", f"@{self.profile.name}'s session {self.session_id} stayed busy until the deadline"
                if lock.acquire(timeout=min(LOCK_WAIT_SLICE, remaining)):
                    with reg.guard:
                        reg.holder[key] = self.run_id
                    return None
        finally:
            with reg.guard:
                reg.waiting.pop(self.run_id, None)

    def _release_session(self, lock: threading.Lock) -> None:
        key = (self.profile.name, self.session_id)
        reg = lock_registry(self.runtime)
        with reg.guard:
            if reg.holder.get(key) == self.run_id:
                del reg.holder[key]
        lock.release()

    def _deadline_reached(self) -> None:
        """Timer callback for a run with a deadline: stop it through the normal cancellation path, and answer a pending
        human question of this session so a run blocked on it can observe the stop."""
        self.timed_out = True
        self._deadline_cancelled = True
        self.runtime.cancel(self.profile.name, self.session_id)
        try:
            for req in self.runtime.broker.pending(profile=self.profile.name):
                if req.get("session_id") != self.session_id:
                    continue
                if req.get("kind") == "approval":
                    self.runtime.broker.answer(req["id"], text="The run timed out.", choice="deny")
                else:
                    self.runtime.broker.answer(req["id"], text="The run timed out; do not continue.")
        except Exception:  # noqa: BLE001 - best effort; the step check still stops the run
            pass

    # ------------------------------------------------------------------ context
    def _llm_messages(self) -> list[dict[str, Any]]:
        """The model's view of the session: summary of folded turns + live turns, with old tool outputs
        pruned. The stored transcript itself is never rewritten."""
        sess = self.sessions.get(self.session_id)
        upto = int(sess.meta.get("compacted_upto") or 0)
        pruned = int(sess.meta.get("pruned_upto") or 0)
        msgs = []
        for r in self.sessions.records(self.session_id):
            m = r["message"]
            if m.get("role") == "system" or r["id"] > upto:
                if m.get("role") == "system":
                    m = {**m, "content": current_output_rules(m["content"])}
                if m.get("role") == "tool" and r["id"] <= pruned and len(str(m.get("content") or "")) > 200:
                    m = {**m, "content": PRUNED_TOOL_OUTPUT}
                msgs.append(m)
        if upto and sess.meta.get("summary"):
            sys_msgs = [m for m in msgs if m.get("role") == "system"][:1]
            rest = [m for m in msgs if m.get("role") != "system"]
            summary = "[Summary of the earlier part of this conversation]\n" + sess.meta["summary"]
            if sess.meta.get("todos"):  # the working plan survives compaction
                from .tools.plan import render

                summary += "\n\n[Your task list, preserved across compaction]\n" + render(sess.meta["todos"])
            if sess.meta.get("task_note"):  # the request itself, when it was folded with no later user turn
                summary += "\n\n[The request you are working on, verbatim]\n" + sess.meta["task_note"]
            # A fabricated assistant turn has no reasoning_content to replay to DeepSeek in tool mode.
            # Keep the summary at user priority and combine it with the first retained user turn when possible.
            if rest and rest[0].get("role") == "user" and isinstance(rest[0].get("content"), str):
                rest[0] = {**rest[0], "content": summary + "\n\n[Conversation continues]\n" + rest[0]["content"]}
                msgs = sys_msgs + rest
            else:
                msgs = sys_msgs + [{"role": "user", "content": summary}] + rest
        return close_tool_calls(msgs)

    def _view_size(self) -> int:
        return sum(len(json.dumps(m, ensure_ascii=False)) for m in self._llm_messages())

    def _tail_start(self, live: list[dict[str, Any]], tail_budget: int) -> int:
        """Index in `live` where the protected tail begins: walk back until ~tail_budget chars, then move
        forward to a user message so tool-call groups are never split. A long tool-call chain after the task has
        no user message in the tail: then cut at an assistant message instead (the start of a tool-call group), and
        always keep at least the newest group, whose results the model has not seen yet."""
        size, i = 0, len(live)
        while i > 0 and size < tail_budget:
            i -= 1
            size += len(json.dumps(live[i]["message"], ensure_ascii=False))
        start = i
        while i < len(live) and live[i]["message"].get("role") != "user":
            i += 1
        if i < len(live):
            return i
        i = start
        while i < len(live) and live[i]["message"].get("role") != "assistant":
            i += 1
        if i < len(live):
            return i
        i = len(live)  # the tail budget ends inside the newest group: keep that whole group
        while i > 0 and live[i - 1]["message"].get("role") not in ("assistant", "user"):
            i -= 1
        return max(0, i - 1)

    def _maybe_compact(self) -> None:
        """Two-phase compaction. Phase 1 (no model call): clear old tool
        outputs outside the protected tail. Phase 2, only if still over budget: fold the middle turns into
        a structured summary that updates the previous one, keeping the tail verbatim. Done rarely and in
        large steps, so DeepSeek's prefix cache stays warm between compactions."""
        budget = self.settings.context_char_budget
        if self._view_size() <= budget:
            return
        sess = self.sessions.get(self.session_id)
        upto = int(sess.meta.get("compacted_upto") or 0)
        live = [r for r in self.sessions.records(self.session_id) if r["id"] > upto and r["message"].get("role") != "system"]
        cut = self._tail_start(live, budget // 5)
        if cut <= 0:
            return
        # Phase 1: prune old tool outputs
        self.sessions.patch_meta(self.session_id, {"pruned_upto": live[cut - 1]["id"]})
        after = self._view_size()
        self.emit("context.pruned", upto=live[cut - 1]["id"], size=after)
        if after <= int(budget * 0.7):
            return
        # Phase 2: structured summary of the middle, iteratively updating the previous summary
        old = live[:cut]
        patch: dict[str, Any] = {}

        def is_task(r: dict[str, Any]) -> bool:  # a request given to run(), not a [system] note
            return r["message"].get("role") == "user" and "display" in r["meta"]

        if any(is_task(r) for r in live[cut:]):
            patch["task_note"] = None
        else:
            # The request is folded with no later one in the tail, so it would survive only inside the summary (the
            # fallback summary may not even contain it): keep the latest request verbatim next to the summary.
            task = next((r for r in reversed(old) if is_task(r)), None)
            if task is not None:
                patch["task_note"] = str(task["message"].get("content") or "")[:6000]
        digest = "\n".join(_digest_line(r["message"]) for r in old)[-160_000:]
        prev = sess.meta.get("summary") or ""
        prompt = [
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": (f"PREVIOUS SUMMARY (update it, don't start over):\n{prev}\n\n" if prev else "")
                                        + f"TURNS TO FOLD IN:\n{digest}"},
        ]
        try:
            summary = self.chat(prompt, purpose="compaction", max_tokens=3000, thinking=False).content.strip()
        except (LLMError, BudgetExceeded):
            summary = (prev + "\n" + digest[-4000:]).strip()
        self.sessions.patch_meta(self.session_id, {"compacted_upto": old[-1]["id"], "summary": summary, **patch})
        self.emit("context.compacted", folded=len(old), size=self._view_size())

    # ------------------------------------------------------------------ experience
    def _with_experience(self, text: str, query: str | None = None) -> tuple[str, list[str]]:
        if self.role == "subagent" or "memory" not in self.settings.toolsets or self.settings.experience_top_k <= 0:
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

    def _session_reasoning(self) -> str | None:
        """The chat's own thinking intensity (`/reasoning` in the CLI, the composer menu on the web), if set:
        "off", "default" (thinking on at the provider's depth) or a level. None: use the profile setting."""
        try:
            word = str(self.sessions.get(self.session_id).meta.get("reasoning") or "").strip().lower()
            return "default" if word == "default" else reasoning.parse(word)
        except (ValueError, KeyError):
            return None

    def _apply_session_model(self) -> None:
        """A chat may pin its own model (`/model` in the CLI, the model menu on the web)."""
        override = str(self.sessions.get(self.session_id).meta.get("model") or "").strip() or None
        self.model_override = override
        if override and override != self.settings.model.model and not self._llm_injected:
            self.settings.model = replace(self.settings.model, model=override)
            self._llm = None

    def _turn_thinking(self) -> dict[str, Any]:
        """Thinking switch for a main-loop call: discussion turns are a few sentences and never think; a
        per-chat override beats the profile setting."""
        if self.discussion_only or self.reasoning == "off":
            return {"thinking": False}
        if self.reasoning:
            return {"thinking": True, "effort": self.reasoning}
        return {}

    # ------------------------------------------------------------------ main loop
    def run(self, text: str | None, *, meta: dict[str, Any] | None = None, max_iterations: int | None = None,
            task_text: str | None = None, deadline: float | None = None) -> RunResult:
        """Run one turn. `task_text` is the underlying request when `text` wraps it in protocol
        boilerplate (room turns, delegations); it is what experience retrieval and reflection see.
        `deadline` (absolute time) bounds both the wait for the session and the run itself: past it the run is stopped
        through the cancellation path (`timed_out` is then set)."""
        self.run_id = new_id("r_")
        start = time.time()
        usage = Usage()
        iterations = tool_calls = 0
        self.deadline, self.timed_out, self._deadline_cancelled = None, False, False
        reg = lock_registry(self.runtime)
        if self.caller is not None and self.caller.run_id:
            with reg.guard:
                reg.parent[self.run_id] = self.caller.run_id
        lock = self.runtime.session_lock(self.profile.name, self.session_id)
        try:
            refused = self._acquire_session(lock, deadline if deadline is not None else start + LOCK_WAIT_MAX)
        except BaseException:
            with reg.guard:
                reg.parent.pop(self.run_id, None)
            raise
        if refused is not None:
            with reg.guard:
                reg.parent.pop(self.run_id, None)
            reason, message = refused
            self.emit("run.not_started", reason=reason, error=message)
            if reason == "timeout":
                self.timed_out = True
            status = "cancelled" if reason == "cancelled" else "error"
            return RunResult(self.run_id, self.session_id, self.profile.name, status,
                             "(stopped by user)" if reason == "cancelled" else "",
                             duration=time.time() - start, error=None if reason == "cancelled" else message,
                             budget=self.budget.snapshot(), not_started=reason)
        timer: threading.Timer | None = None
        if deadline is not None:
            self.deadline = deadline
            timer = threading.Timer(max(0.0, deadline - time.time()), self._deadline_reached)
            timer.daemon = True
            timer.start()
        final_text = ""
        status = "completed"
        error = None
        task_text = task_text or text or ""
        try:
            # pid lets a restarted server tell a live run from an interrupted one
            self.sessions.patch_meta(self.session_id, {"pid": os.getpid()})
            self.reasoning = self._session_reasoning()
            self._apply_session_model()
            self._deliverables = list(self.sessions.get(self.session_id).meta.get("deliverables") or [])
            if self.workspace_error:
                raise WorkspaceUnavailable(self.workspace_error)
            self.sessions.update(self.session_id, status="running")
            self._ensure_system()
            self._note_workspace()
            self.emit("run.started", text=(text or "")[:2000], role=self.role, depth=self.depth)
            if text is not None:
                content, _ = self._with_experience(text, task_text)
                self.sessions.append(self.session_id, {"role": "user", "content": content},
                                     meta={"display": text, **(meta or {})})
            else:
                task_text = self._last_user_text()
            iterations, tool_calls, final_text, status = self._loop(usage, max_iterations or self.settings.max_iterations)
        except Cancelled:
            status, final_text = "cancelled", "(stopped by user)"
            if self.timed_out:
                final_text = "(stopped: the run reached the time limit its sender set)"
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
        except WorkspaceUnavailable as exc:
            status, error = "error", str(exc)
            final_text = str(exc)
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
            if timer is not None:
                timer.cancel()
                timer.join(5)
                if self._deadline_cancelled:  # the stop flag was ours: do not leave it for the next run
                    self.runtime.clear_cancel(self.profile.name, self.session_id)
            self.deadline = None
            self.sessions.update(self.session_id, status="error" if status == "error" else "idle")
            with reg.guard:
                reg.parent.pop(self.run_id, None)
            self._release_session(lock)
        result = RunResult(self.run_id, self.session_id, self.profile.name, status, final_text, iterations, tool_calls,
                           time.time() - start, usage, error, budget=self.budget.snapshot())
        trivial = self.discussion_only or final_text.strip().lower().strip(" .") in {"[pass]", "pass", "[silent]"}
        self.emit("run.finished", status=status, text=final_text[:4000], iterations=iterations, tool_calls=tool_calls,
                  duration=round(result.duration, 2), error=error)
        if self.reflect_enabled and self.role != "subagent" and status != "cancelled" and task_text.strip() and not trivial:
            snapshot = self._llm_messages()  # reflect on this run only, even if the session moves on

            def _reflect() -> None:
                try:
                    from .reflection import reflect

                    result.experience_ids = reflect(self, task_text, result, messages=snapshot)
                except Exception as exc:  # reflection must never break the task result
                    self.emit("reflection.failed", error=str(exc))

            def start_reflection():
                if self.settings.background_reflection:
                    self.runtime.track_reflection(self.runtime.spawn(_reflect, name="reflection"))
                else:
                    _reflect()

            if self.budget.team_turn:
                self.budget.team_turn.defer_learning(self, start_reflection)
            else:
                start_reflection()
        return result

    def resume(self) -> RunResult:
        """Continue a session whose last run was interrupted (e.g. the process died while waiting
        for a human). Dangling tool calls are executed (re-asking the human if needed) first."""
        return self.run(None)

    def _last_user_text(self) -> str:
        for r in reversed(self.sessions.records(self.session_id)):
            if r["message"].get("role") == "user":
                return r["meta"].get("display") or r["message"].get("content", "")
        return ""

    def _pending_tool_calls(self) -> list[dict[str, Any]]:
        msgs = self.sessions.messages(self.session_id)
        for i in range(len(msgs) - 1, -1, -1):
            m = msgs[i]
            if m.get("role") == "assistant" and m.get("tool_calls"):
                answered = {x.get("tool_call_id") for x in msgs[i + 1 :] if x.get("role") == "tool"}
                return [tc for tc in m["tool_calls"] if tc["id"] not in answered]
            if m.get("role") in {"user", "assistant"}:
                return []
        return []

    def _answer_unrun(self, calls: list[dict[str, Any]], text: str, **meta: Any) -> None:
        """Give every call that will not run a result, so the stored transcript stays complete and valid."""
        for c in calls:
            self.sessions.append(self.session_id, {"role": "tool", "tool_call_id": c["id"], "content": text},
                                 meta={"tool": c["function"]["name"], **meta})

    def _run_tool_calls(self, calls: list[dict[str, Any]]) -> int:
        names = [tc["function"]["name"] for tc in calls]
        if ("ask_user" in names and "ask_user" in self.tools and not self.discussion_only
                and {"delegate_task", "message_agent"}.intersection(names)):
            index = names.index("ask_user")
            # Arguments for this batch were generated before the answer was known.
            # Close their tool calls without executing them and let the next turn plan from the answer.
            try:
                return self._run_tool_calls([calls[index]])
            finally:
                self._answer_unrun(calls[:index] + calls[index + 1:],
                                   "Not run: this turn requested user clarification. Use the answer above and issue "
                                   "fresh tool calls for the work that is still needed.", clarification_pending=True)
        n = 0
        for i, tc in enumerate(calls):
            try:
                self._check_cancel()
            except Cancelled:
                self._answer_unrun(calls[i:], "(cancelled by the user before this call ran)", cancelled=True)
                raise
            name = tc["function"]["name"]
            raw = tc["function"].get("arguments") or "{}"
            t = self.tools.get(name)
            self.emit("tool.started", tool=name, call_id=tc["id"], args=_preview_args(raw))
            started = time.time()
            sig = name + "\x00" + " ".join(raw.split())
            if name == "run_checks" and (fast := getattr(self.budget, "fast", None)):
                sig = name + "\x00" + fast.check_signature(raw)
            elif name == "delegate_task" and self.room_id:
                # Retrying an existing review after its state or inputs changed is a different operation.
                request = loads(raw, {})
                tasks = request.get("tasks") if isinstance(request, dict) else None
                for task in tasks if isinstance(tasks, list) else ():
                    if not isinstance(task, dict) or not task.get("review") or not isinstance(task.get("task_id"), str):
                        continue
                    try:
                        card = self.runtime.board.get(task["task_id"])
                    except KeyError:
                        continue
                    if card["room_id"] == self.room_id:
                        sig += json.dumps(card.get("review"), sort_keys=True)
            self._call_sigs[sig] = self._call_sigs.get(sig, 0) + 1
            repeats = self._call_sigs[sig]
            stop: LoopDetected | None = None
            args: dict[str, Any] | None = None
            if repeats >= REPEAT_STOP:
                stop = LoopDetected(f"the same {name} call was repeated {repeats} times with identical arguments")
                out = f"ERROR: not run — {stop}. The loop guard is stopping this run."
            elif repeats >= REPEAT_WARN:
                self._hot_turns = 2  # degeneration sign: loosen sampling for the next turns
                out = (f"ERROR: you already made this exact {name} call {repeats - 1} times. "
                       "Change your approach or finish with what you have.")
            elif t is None:
                out = f"ERROR: unknown tool '{name}'. Available: {', '.join(sorted(self.tools))}"
            elif self.discussion_only and name in MUTATING_TOOLS:
                out = (f"ERROR: this is a discussion turn — {name} is not available now. Say briefly which part you can "
                       "take on (or [PASS]); the lead will delegate the actual work to you.")
            else:
                try:
                    args = json.loads(raw) if raw.strip() else {}
                    if not isinstance(args, dict):
                        raise ValueError("arguments must be a JSON object")
                except (json.JSONDecodeError, ValueError) as exc:
                    args = None
                    self._hot_turns = 2  # malformed arguments often come from runaway, repetitive generation
                    out = f"ERROR: invalid JSON arguments for {name}: {exc}"
                else:
                    out = execute(t, self._context(tc["id"]), args)
                    if self.review_spec and name in WRITE_TOOLS and not out.startswith("ERROR"):
                        from .team.review import review_write_feedback

                        if note := review_write_feedback(self.review_spec, self.paths, args["path"]):
                            out += f"\nReview report format: {note}"
            if len(out) > MAX_TOOL_RESULT:
                out = (out[: MAX_TOOL_RESULT // 2] + f"\n... [{len(out) - MAX_TOOL_RESULT} chars cut from the middle of this "
                       "result; read files in parts with read_file offset/limit, or narrow the command] ...\n"
                       + out[-MAX_TOOL_RESULT // 2 :])
            if stop is None:
                out, stop = self._progress_guard(name, sig, out, args)
            # The result is recorded even when the guard stops the run here: the call did run (an edit is on disk).
            self.sessions.append(self.session_id, {"role": "tool", "tool_call_id": tc["id"], "content": out},
                                 meta={"tool": name, "duration": round(time.time() - started, 3)})
            ok = not out.startswith("ERROR")
            if name in WRITE_TOOLS and ok:
                self._wrote_file = True
                path = (args or {}).get("path")
                if isinstance(path, str) and path.strip() and path not in self.written_paths:
                    self.written_paths.append(path)
            if name == "todo" and ok and (args or {}).get("todos") is not None:  # a plan write, not a read
                self._plan_step, self._plan_nudged = self._step, False
            self.emit("tool.finished", tool=name, call_id=tc["id"], ok=ok, preview=out[:600],
                      duration=round(time.time() - started, 2))
            n += 1
            if stop is not None:
                self._answer_unrun(calls[i + 1 :], f"(not run: the loop guard stopped this run — {stop})")
                raise stop
        return n

    def _progress_guard(self, name: str, raw: str, out: str, args: dict[str, Any] | None) -> tuple[str, LoopDetected | None]:
        """Detect repeated tool outcomes even when the agent saves the same script under new names."""
        duplicate_write = False
        if name == "run_checks":
            key = hash((name, raw, out))
        elif name in WRITE_TOOLS and not out.startswith("ERROR"):
            # A generic confirmation can hide a real edit, so keep the arguments in the result signature.
            key = hash((name, " ".join(raw.split()), out))
            if name == "write_file" and args is not None and not args.get("append"):
                content = args.get("content")
                # The model may pass a JSON object or list as content (the tool writes it JSON-encoded).
                content_key = hash(content if isinstance(content, str) else json.dumps(content, sort_keys=True, default=str))
                duplicate_write = content_key in self._written_content_sigs
                self._written_content_sigs.add(content_key)
        else:
            key = hash((name, out))
        seen = self._result_sigs.get(key, 0)
        self._result_sigs[key] = seen + 1
        if seen:
            self._stale_streak += 1
        elif not duplicate_write:
            # Copying identical content to a new path is neutral. It does not grow the streak on its own.
            self._stale_streak = 0
        if self._stale_streak >= STALE_STOP:
            stop = LoopDetected(f"the last {self._stale_streak} tool results repeated earlier results (no progress)")
            return out + f"\n\n[progress guard] {stop}; stopping this run.", stop
        if self._stale_streak >= STALE_NUDGE:
            out += (f"\n\n[progress guard] The last {self._stale_streak} tool results were identical to earlier ones — you are "
                    "not making progress. Stop repeating checks; either change approach or write your final answer now.")
        return out, None

    def _loop(self, usage: Usage, max_iter: int) -> tuple[int, int, str, str]:
        iterations = tool_calls = 0
        pending = self._pending_tool_calls()
        if pending:
            tool_calls += self._run_tool_calls(pending)
        schemas = [t.schema() for t in self.tools.values()]
        self._schemas = schemas
        partial: list[str] = []  # text of replies cut off at the output limit, continued in the next step
        markup_retries = 0
        announce_nudged = False
        conflict_nudged = False
        checkpoint_at = time.time() + 0.65 * (self.deadline - time.time()) if self.review_spec and self.deadline else None
        while iterations < max_iter:
            self._check_cancel()
            if self.is_root and self.budget.near_limit:
                # The last 10% of the run budget is reserved for the root agent's own summary.
                return iterations, tool_calls, self._wrap_up(usage, "The run budget is nearly exhausted."), "budget_exceeded"
            self._maybe_compact()
            iterations += 1
            self._step = iterations
            self._note_budget()
            if checkpoint_at is not None and time.time() >= checkpoint_at:
                checkpoint_at = None
                self.sessions.append(self.session_id, {"role": "user", "content": (
                    f"[system] Review time checkpoint. Save current evidence and outstanding checks to {self.review_spec['report']} "
                    "now. Use Verdict: INCOMPLETE until the requirement is decided.")}, meta={"checkpoint": True})
                self.emit("budget.checkpoint", reason="review_time", steps_left=max_iter - iterations + 1)
            self._remind_stale_plan(iterations)
            if max_iter >= 8 and iterations == int(max_iter * 0.8):
                # Budget checkpoint: a chance to verify and wrap up before the hard cap.
                left = max_iter - iterations + 1
                self.sessions.append(self.session_id, {"role": "user", "content": (
                    f"[system] Step budget checkpoint: {left} of {max_iter} steps left. If your deliverable is a file that "
                    "is not written yet, write it now with what you have (in parts if it is long), then refine it. "
                    "Prioritise finishing and verifying the core deliverable; drop nice-to-have extras; then give your "
                    "final answer.")}, meta={"checkpoint": True})
                self.emit("budget.checkpoint", steps_left=left)
                missing = self._missing_deliverables()
                if (missing or (not self._deliverables and not self._wrote_file)) \
                        and any(s["function"]["name"] in WRITE_TOOLS for s in schemas):
                    # Advice alone did not work: workers kept reading or experimenting until the step limit and never
                    # wrote their report. Until it exists, the next steps offer only the file tools: write, or answer.
                    self._write_only_steps = 2
                    what = (f"Your deliverable {', '.join(missing)} does not exist yet" if missing
                            else "You have not written any file yet")
                    self.sessions.append(self.session_id, {"role": "user", "content": (
                        f"[system] {what}. For the next two steps only write_file and edit_file are available: write it "
                        "now with what you have (in parts if it is long), or, if the task needs no file, give your "
                        "final answer.")}, meta={"checkpoint": True})
            self.emit("llm.request", iteration=iterations)
            # Greedy decoding (temperature 0) can lock into repetition; loosen it while the guard sees no progress.
            temp = 0.7 if (self._stale_streak >= 2 or self._hot_turns > 0) else None
            self._hot_turns = max(0, self._hot_turns - 1)
            streamer = _DeltaStreamer(self, iterations) if self.settings.stream else None
            review_turn = self.review_turn if self.review_turn is not None and self.review_turn.active else None
            step_schemas = schemas
            if self._write_only_steps > 0:
                self._write_only_steps -= 1
                step_schemas = [s for s in schemas if s["function"]["name"] in WRITE_TOOLS]
            def on_delta(kind: str, text: str) -> None:
                self._check_cancel()
                if streamer and (review_turn is None or kind != "content"):
                    streamer.feed(kind, text)

            resp = self.chat(self._llm_messages(), step_schemas or None, temperature=temp,
                             on_delta=on_delta if streamer or self.deadline is not None else None,
                             **self._turn_thinking())
            if streamer:
                streamer.flush()
            usage.add(resp.usage)
            msg = resp.to_message()
            meta = {"usage": resp.usage.__dict__, "finish": resp.finish_reason}
            if resp.tool_calls or review_turn is None:
                self.sessions.append(self.session_id, msg, meta=meta)
                self.emit("assistant.message", content=resp.content[:4000], tool_calls=[
                    {"name": tc.name, "args": _preview_args(tc.arguments)} for tc in resp.tool_calls])
            if resp.tool_calls and resp.finish_reason == "length":
                # The reply hit the output limit inside a tool call: its arguments are cut off, so it is not run.
                self._refuse_truncated(msg["tool_calls"], resp.usage.completion_tokens)
                continue
            if not resp.tool_calls:
                if TOOL_MARKUP.search(resp.content or "") and markup_retries < 2:
                    markup_retries += 1  # a tool call written as text: ask for a real one (or plain prose)
                    self.emit("tool_markup.leaked")
                    self.sessions.append(self.session_id, {"role": "user", "content": (
                        "[system] Your last reply contained tool-call markup as plain text instead of a real tool call. "
                        "Call the tool properly, or give your answer as plain prose.")}, meta={"markup_note": True})
                    continue
                if resp.finish_reason == "length":
                    partial.append(strip_tool_markup(resp.content))
                    self.sessions.append(self.session_id, {"role": "user", "content": (
                        "[system] Your reply was cut off at the output limit. Continue exactly where it stopped, without "
                        "repeating it.")}, meta={"length_note": True})
                    continue
                text = (resp.content or "").strip()
                if (not tool_calls and not announce_nudged and not partial and step_schemas and not self.discussion_only
                        and len(text) < 600 and "```" not in text and ANNOUNCE_ONLY.search(text)):
                    announce_nudged = True  # it said what it will do, then stopped: once, ask it to do it
                    self.emit("announce_only.nudged")
                    self.sessions.append(self.session_id, {"role": "user", "content": (
                        "[system] You described what you are going to do but made no tool call, so nothing has been "
                        "done yet. Carry out the task now with your tools; if no action is needed, give your final "
                        "answer instead.")}, meta={"announce_note": True})
                    continue
                final = "".join(partial) + strip_tool_markup(resp.content)
                if review_turn is not None:
                    if not conflict_nudged and (open_cards := review_turn.unresolved()):
                        conflict_nudged = True
                        ids = ", ".join(c["id"] for c in open_cards)
                        self.sessions.append(self.session_id, {"role": "user", "content":
                            f"[system] Disputed evidence remains on {ids}. If it can be checked, delegate an independent "
                            "review on that card with the deciding source and affected files. Otherwise report what is open."})
                        continue
                    final = review_turn.finalize(self, final)
                    msg["content"] = final
                    self.sessions.append(self.session_id, msg, meta=meta)
                    self.emit("assistant.message", content=final[:4000], tool_calls=[])
                return iterations, tool_calls, final, "completed"
            tool_calls += self._run_tool_calls(msg["tool_calls"])
        tool_calls += self._salvage_deliverables(usage, schemas)
        return iterations, tool_calls, self._wrap_up(usage, "The iteration limit was reached."), "max_iterations"

    def _note_budget(self) -> None:
        """Tell the root agent once when most of the run budget is spent (delegates and subagents share it, and a
        lead cannot otherwise see it: one started a third review round with 30 calls left, which then stopped)."""
        if not self.is_root or self._budget_noted or self.budget.fraction < BUDGET_NOTE_AT:
            return
        self._budget_noted = True
        self.sessions.append(self.session_id, {"role": "user", "content": (
            f"[system] Run budget: {self.budget.describe()}; the run stops at 100% and teammates stop at 90%. Fit the "
            "rest of the work into what is left: finish and verify the essential parts yourself, and start another "
            "delegation or review round only if the result depends on it.")}, meta={"budget_note": True})
        self.emit("budget.note", **self.budget.snapshot())

    def _remind_stale_plan(self, step: int) -> None:
        """One reminder when the plan has open items but has not been updated for PLAN_STALE_STEPS steps."""
        if self._plan_nudged or step - self._plan_step <= PLAN_STALE_STEPS or "todo" not in self.tools:
            return
        todos = self.sessions.get(self.session_id).meta.get("todos") or []
        if not any(t.get("status") in ("pending", "in_progress") for t in todos):
            return
        self._plan_nudged = True
        done = sum(1 for t in todos if t.get("status") == "completed")
        idle = step - self._plan_step - 1
        self.sessions.append(self.session_id, {"role": "user", "content": (
            f"[system] Your plan shows {done} of {len(todos)} items done and has not been updated for {idle} steps. "
            "People follow your progress through it: update it now in one todo call (merge=true) — mark finished "
            "items completed and the current one in_progress, cancel what you dropped — then continue.")},
            meta={"plan_note": True})
        self.emit("plan.stale", steps=idle, done=done, total=len(todos))

    def _missing_deliverables(self) -> list[str]:
        """Requested output files that do not exist (or are empty) yet; paths the policy cannot check are skipped."""
        missing = []
        for rel in self._deliverables:
            try:
                p = self.paths.resolve(rel)
            except Exception:  # noqa: BLE001 - outside the roots or invalid: nothing to check
                continue
            if not p.is_file() or p.stat().st_size == 0:
                missing.append(rel)
        return missing

    def _salvage_deliverables(self, usage: Usage, schemas: list[dict[str, Any]]) -> int:
        """At the step limit, one extra step with only the file tools if a requested output file is still missing,
        so the work done so far is saved instead of lost (a lead used to re-delegate "just write the file")."""
        missing = self._missing_deliverables()
        write = [s for s in schemas if s["function"]["name"] in WRITE_TOOLS]
        if not missing or not write:
            return 0
        self.sessions.append(self.session_id, {"role": "user", "content": (
            f"[system] The step limit is reached and {', '.join(missing)} does not exist yet. Write it now from what you "
            "have (only the file tools are available for this one step; mark unfinished parts as such).")},
            meta={"salvage": True})
        self.emit("deliverable.salvage", files=missing)
        resp = self.chat(self._llm_messages(), write, purpose="salvage")
        usage.add(resp.usage)
        msg = resp.to_message()
        self.sessions.append(self.session_id, msg, meta={"usage": resp.usage.__dict__, "finish": resp.finish_reason})
        if not resp.tool_calls:
            return 0
        if resp.finish_reason == "length":
            self._refuse_truncated(msg["tool_calls"], resp.usage.completion_tokens)
            return 0
        return self._run_tool_calls(msg["tool_calls"])

    def _refuse_truncated(self, calls: list[dict[str, Any]], out_tokens: int) -> None:
        """Answer every call of a reply that was cut off at the output limit (the transcript must stay valid)."""
        self.emit("output.truncated", tokens=out_tokens, tools=[c["function"]["name"] for c in calls])
        for c in calls:
            self.sessions.append(self.session_id, {"role": "tool", "tool_call_id": c["id"], "content": (
                f"ERROR: your reply hit the output limit ({out_tokens} tokens) and was cut off, so this call was not run. "
                "Make it smaller: write a large file in parts (write_file with the first part, then write_file with "
                "append=true for the rest, each well under 20,000 characters).")},
                meta={"tool": c["function"]["name"], "truncated": True})

    def _wrap_up(self, usage: Usage, why: str) -> str:
        """Ask for a final report so the user still gets a summary. The tools stay visible but cannot be called
        (tool_choice "none"): offered no tools at all, the model sometimes wrote its next tool call as text."""
        self.sessions.append(self.session_id, {"role": "user", "content": f"[system] {why} Stop using tools and report what "
                                               "you completed, what is unfinished, and why. Answer in plain prose."})
        schemas = getattr(self, "_schemas", None)
        resp = self.chat(self._llm_messages(), schemas or None, purpose="wrapup",
                         **({"tool_choice": "none"} if schemas else {}))
        usage.add(resp.usage)
        text = strip_tool_markup(resp.content)
        if not text:
            text = (f"(No final report: {why} The agent stopped before it could summarise; see this session's log "
                    "for what it did.)")
        if self.review_turn is not None and self.review_turn.active:
            text = self.review_turn.finalize(self, text, recheck=False)
        self.sessions.append(self.session_id, {"role": "assistant", "content": text})
        return text


class _DeltaStreamer:
    """Publishes streamed text as `assistant.delta` events, batched (~every 120 ms or 400 chars) so a
    fast stream does not flood the event bus / WebSocket."""

    def __init__(self, agent: "Agent", iteration: int):
        self.agent = agent
        self.iteration = iteration
        self.buf: dict[str, list[str]] = {"content": [], "reasoning": []}
        self.size = 0
        self.last = time.time()

    def feed(self, kind: str, text: str) -> None:
        if kind == "reset":  # the stream broke and is being retried: drop what was shown so far
            self.buf = {"content": [], "reasoning": []}
            self.size = 0
            self.agent.emit("assistant.delta", kind="reset", text="", iteration=self.iteration)
            return
        self.buf.setdefault(kind, []).append(text)
        self.size += len(text)
        if self.size >= 400 or time.time() - self.last >= 0.12:
            self.flush()

    def flush(self) -> None:
        for kind, parts in self.buf.items():
            if parts:
                self.agent.emit("assistant.delta", kind=kind, text="".join(parts), iteration=self.iteration)
        self.buf = {"content": [], "reasoning": []}
        self.size = 0
        self.last = time.time()


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

