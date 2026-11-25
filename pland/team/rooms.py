"""Group rooms: several bots and the human in one conversation (Bot Mode group chat).

Turn-taking is designed so that collaboration produces real work:

* A human message addresses the @mentioned bots (`@all`/`@everyone` or no mention = every member).
* One addressed bot *leads* the response: the room's configured lead if addressed, else the first
  @mentioned bot, else the first member. Nothing about the lead is a fixed role — any bot can lead.
* Round 1: the other addressed bots speak first (brief: what they can contribute, risks, or
  `[PASS]`), then the lead acts on the request with full tools — typically decomposing it on the
  team board and handing subtasks to teammates with `delegate_task`, which really executes them in
  the teammates' own profiles, then integrating the results.
* Later rounds: explicit bot handoffs get a turn; the room settles when a round is silent or
  limits are hit (max rounds / messages). A bot writing `@user` raises the room's "needs you" flag.
* Every member keeps one persistent room session (its private view of the room) and sees only the
  room messages posted since its last turn, plus its own memory. Private Bot Chats stay separate.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..errors import NotFound
from ..sessions import SessionStore
from ..store import dumps, loads, new_id, now
from ..workspace import chosen
from .fast import FastMode, guidance
from .fast import enabled as fast_enabled
from .fast import is_reviewer as fast_reviewer

if TYPE_CHECKING:
    from ..runtime import Runtime

MENTION = re.compile(r"(?<![\w.])@([a-z0-9][a-z0-9_-]{0,31})", re.IGNORECASE)
PASS_TOKENS = {"[pass]", "pass", "[silent]", "no_reply", "[no_reply]"}
MAX_ROUNDS = 3
MAX_MESSAGES = 12
DEFAULT_FAST_MODE = True


class RoomManager:
    def __init__(self, runtime: "Runtime"):
        self.rt = runtime
        self.db = runtime.shared
        self._drive_locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._budgets: dict[str, Any] = {}  # the budget of each room's running drive (its Fast Mode rides on it)

    # ------------------------------------------------------------------ CRUD
    def _row(self, r: dict[str, Any] | None) -> dict[str, Any] | None:
        if r is None:
            return None
        r = dict(r)
        r["members"] = loads(r["members"], [])
        r["settings"] = loads(r["settings"], {})
        r["needs_you"] = bool(r["needs_you"])
        return r

    def create(self, name: str, members: list[str], *, lead: str | None = None,
               fast_mode: bool = DEFAULT_FAST_MODE) -> dict[str, Any]:
        members = [m.lstrip("@") for m in members]
        missing = [m for m in members if not self.rt.profiles.exists(m)]
        if missing:
            raise ValueError(f"unknown bots: {', '.join(missing)}")
        if not 1 <= len(members) <= 8:
            raise ValueError("a room needs 1-8 bots")
        if self.db.one("SELECT id FROM rooms WHERE name=?", (name,)):
            raise ValueError(f"a room named {name!r} already exists")
        rid = new_id("room_")
        settings = {"lead": lead.lstrip("@") if lead else None, "max_rounds": MAX_ROUNDS,
                    "max_messages": MAX_MESSAGES, "fast_mode": fast_mode}
        self.db.execute("INSERT INTO rooms(id, name, members, settings, created, updated) VALUES (?,?,?,?,?,?)",
                        (rid, name, dumps(members), dumps(settings), now(), now()))
        self.shared_dir(rid)
        room = self.get(rid)
        self.rt.bus.publish("room.created", room_id=rid, room=room)
        self.post(rid, "system", f"Room created with {', '.join('@' + m for m in members)}.", kind="system")
        return room

    def get(self, rid: str) -> dict[str, Any] | None:
        return self._row(self.db.one("SELECT * FROM rooms WHERE id=?", (rid,)))

    def by_name(self, name: str) -> dict[str, Any] | None:
        return self._row(self.db.one("SELECT * FROM rooms WHERE name=?", (name,)))

    def list(self) -> list[dict[str, Any]]:
        return [self._row(r) for r in self.db.query("SELECT * FROM rooms ORDER BY updated DESC")]

    def update(self, rid: str, *, name: str | None = None, members: list[str] | None = None,
               settings: dict[str, Any] | None = None, needs_you: bool | None = None) -> dict[str, Any]:
        room = self.get(rid)
        if room is None:
            raise NotFound(rid)
        if name:
            self.db.execute("UPDATE rooms SET name=? WHERE id=?", (name, rid))
        if members is not None:
            members = [m.lstrip("@") for m in members]
            missing = [m for m in members if not self.rt.profiles.exists(m)]
            if missing:
                raise ValueError(f"unknown bots: {', '.join(missing)}")
            self.db.execute("UPDATE rooms SET members=? WHERE id=?", (dumps(members), rid))
        if settings:
            merged = {**room["settings"], **settings}
            self.db.execute("UPDATE rooms SET settings=? WHERE id=?", (dumps(merged), rid))
        if needs_you is not None:
            self.db.execute("UPDATE rooms SET needs_you=? WHERE id=?", (int(needs_you), rid))
        self.db.execute("UPDATE rooms SET updated=? WHERE id=?", (now(), rid))
        room = self.get(rid)
        self.rt.bus.publish("room.updated", room_id=rid, room=room)
        return room

    def delete(self, rid: str) -> None:
        self.db.execute("DELETE FROM room_messages WHERE room_id=?", (rid,))
        self.db.execute("DELETE FROM team_reviews WHERE task_id IN (SELECT id FROM team_tasks WHERE room_id=?)", (rid,))
        self.db.execute("DELETE FROM rooms WHERE id=?", (rid,))
        self.rt.bus.publish("room.deleted", room_id=rid)

    def shared_dir(self, rid: str) -> Path:
        """The group's shared folder: a folder the user chose for the group (settings "workspace", see
        pland/workspace.py), else rooms/<id>/shared under PLAND_HOME."""
        room = self.get(rid)
        folder = chosen((room or {}).get("settings"))
        if folder and Path(folder).is_dir():
            return Path(folder).resolve()
        path = self.rt.root / "rooms" / rid / "shared"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def set_workspace(self, rid: str, folder: str | None) -> dict[str, Any]:
        """Point the group's shared folder at `folder` (validated by the caller; None = the default one). A group is
        one conversation, so its members keep their context; every member reads this note at its next turn
        (members see all room messages since their last turn) and its `shared/` link is re-pointed then."""
        room = self.get(rid)
        if room is None:
            raise NotFound(rid)
        before = str(self.shared_dir(rid))
        updated = self.update(rid, settings={"workspace": folder})
        after = str(self.shared_dir(rid))
        if after != before:
            default = str((self.rt.root / "rooms" / rid / "shared").resolve())
            name = lambda f: "the group's default shared folder" if f == default else f  # noqa: E731
            self.post(rid, "system", f"The group's shared folder is now {name(after)} (it was {name(before)}). `shared/` "
                      "points there from now on; files from the previous folder are no longer reachable.", kind="system")
        return self.get(rid) or updated

    # ------------------------------------------------------------------ messages
    def post(self, rid: str, speaker: str, content: str, *, kind: str = "message", meta: dict | None = None) -> dict[str, Any]:
        cur = self.db.execute("INSERT INTO room_messages(room_id, speaker, kind, content, meta, created) VALUES (?,?,?,?,?,?)",
                              (rid, speaker, kind, content, dumps(meta or {}), now()))
        self.db.execute("UPDATE rooms SET updated=? WHERE id=?", (now(), rid))
        msg = {"id": int(cur.lastrowid), "room_id": rid, "speaker": speaker, "kind": kind, "content": content,
               "meta": meta or {}, "created": now()}
        self.rt.bus.publish("room.message", room_id=rid, message=msg)
        return msg

    def messages(self, rid: str, *, after_id: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM room_messages WHERE room_id=? AND id>? ORDER BY id LIMIT ?", (rid, after_id, limit))
        for r in rows:
            r["meta"] = loads(r["meta"], {})
        return rows

    # ------------------------------------------------------------------ driving
    def drive_lock(self, rid: str) -> threading.Lock:
        with self._guard:
            return self._drive_locks.setdefault(rid, threading.Lock())

    def send(self, rid: str, text: str, *, hitl=None, background: bool = True) -> dict[str, Any]:
        room = self.get(rid)
        if room is None:
            raise NotFound(rid)
        msg = self.post(rid, "user", text)
        if room["needs_you"]:
            self.update(rid, needs_you=False)
        if background:
            self.rt.spawn(lambda: self.drive(rid, msg, hitl=hitl), name=f"room-{rid}")
            return {"message": msg, "driving": True}
        return {"message": msg, "result": self.drive(rid, msg, hitl=hitl)}

    def _member_session(self, member: str, rid: str, room_name: str) -> str:
        prof = self.rt.profiles.get(member)
        store = SessionStore(prof)
        sess = store.find(kind="room_member", room_id=rid)
        if sess is None:
            sess = store.create(title=f"Group: {room_name}", kind="room_member", room_id=rid, meta={"last_seen": 0})
        return sess.id

    def _turn_prompt(self, room: dict, member: str, new_msgs: list[dict], role: str) -> str:
        roster = []
        for m in room["members"]:
            p = self.rt.profiles.get(m)
            roster.append(f"@{m} ({p.title}{' — ' + p.description if p.description else ''})")
        lines = [f"[Group room \"{room['name']}\" — members: {'; '.join(roster)}; and the human (@user)]",
                 "New messages since your last turn:"]
        for m in new_msgs:
            who = "user (human)" if m["speaker"] == "user" else ("system" if m["speaker"] == "system" else "@" + m["speaker"])
            tag = " (activity)" if m["kind"] == "activity" else ""
            lines.append(f"[{who}{tag}]: {m['content'][:6000]}")
        lines.append("---")
        if role == "lead":
            budget = self._budgets.get(room["id"])
            if budget and budget.team_turn.inherited:
                lines.append("Unresolved decisions carried over from earlier work: " +
                             ", ".join(sorted(budget.team_turn.inherited)) +
                             ". Inspect those cards. For a continuation, keep the relevant decisions open until "
                             "verified. For a clearly independent new request, use team_tasks separate_request "
                             "with the old task_id and a concrete reason it cannot affect the new answer.")
            lines.append(
                "You lead the response to the latest request. Act on it now. For multi-part work: record the plan with "
                "team_tasks. Base each blocking check on an explicit requirement or something the recipient needs to "
                "use the result. Assign the decision or next step the work must support, and the evidence needed. "
                "Give an intermediate file a hard size limit only if the user or its destination requires one. "
                "Name that source and the file it applies to. Keep team estimates out of blocking checks. "
                "Keep the audience and required outputs of this request. Make design choices freely; treat extra audiences, "
                "formats and refinements as optional unless the request or actual use requires them. "
                "Allow equivalent wording and implementations. "
                "Delegate substantial independent work with delegate_task (pass the "
                "board task_id; delegates execute with their own tools and report back; independent subtasks in one call run "
                "in parallel; sequence dependent ones — a task whose prerequisites are unfinished is refused). When a room "
                "member can verify a draft while another works on an independent aspect, send both in one batch. "
                "For a simple request, read the inputs and deliver it directly. If a primary source answers a teammate's "
                "preliminary question, proceed with that answer. Build extra tools or investigate additional claims "
                "only when needed for a requested outcome. "
                "Deliverables the team shares go in `shared/` (works in file tools and shell commands). Verify the integrated "
                "acceptance evidence and report each requested outcome, what supports it, and anything still open. Ask the human with ask_user before delegating work "
                "that depends on their answer. Record actual prerequisites with depends_on. For an independent "
                "file review, pass its planned task_id and exact shared input and report paths. If an outcome must "
                "work in actual use, set review.observation to what the recipient should be able to do or obtain. "
                "On revisions reuse the same task_id, omit criterion/observation, and describe the affected behavior in goal. "
                "After PASS deliver when only optional polish remains. If a decision depends on research, pass the "
                "decision as a question or make it a prerequisite. Preserve the user's chosen source/version. "
                "Compare the returned evidence with instructions already given to workers. Correct affected work before delivery. "
                "A question settled by reading the input belongs in the original result. Use a dispute card only for "
                "a consequential disagreement still needing a decision. For a reusable rule, verify a case that "
                "distinguishes the competing interpretations. During cleanup, leave reviewed inputs "
                "and the signed report at their shared paths; copy them if you also need them elsewhere."
            )
        elif role == "member":
            lines.append(
                "A teammate leads this request and will delegate the work. This is a discussion turn: do not start the work "
                "(no file changes, code or web research now). Reply only if you add something useful — the part you are best "
                "suited for or a concrete concern supported by information you already have — in at most 3 sentences. "
                "If the assigned teammate can settle it just by reading the inputs, reply exactly [PASS]."
            )
        else:
            lines.append(
                "You were @mentioned above. Do what was asked of you (use your tools if work is needed) and reply briefly. "
                "Do not redo or re-verify work others already verified. If nothing is actually required of you, reply exactly [PASS]."
            )
        fast = getattr(self._budgets.get(room["id"]), "fast", None)
        if fast is not None and role in {"lead", "mentioned"}:
            lines.append(guidance(fast, "lead" if role == "lead" else "delegate"))
        lines.append("To ask another Bot for a public follow-up, start your reply with a line in the format "
                     "!handoff @name followed by the action. Use one leading line per handoff. "
                     "Plain @names in the rest of a reply are references. "
                     + ("Flag questions for the lead to raise with the human." if role == "member"
                        else "Use @user only to hand a question to the human."))
        return "\n".join(lines)

    def _member_turn(self, room: dict, member: str, role: str, hitl, budget=None) -> str | None:
        return self._post_member(room, member, self._run_member(room, member, role, hitl, budget))

    def _run_member(self, room: dict, member: str, role: str, hitl, budget=None) -> dict[str, Any] | None:
        """Run one member's turn (its agent loop in its room session); posting happens separately so
        independent discussion turns can run concurrently and still be posted in a stable order."""
        from ..agent import Agent

        rid = room["id"]
        prof = self.rt.profiles.get(member)
        sid = self._member_session(member, rid, room["name"])
        store = SessionStore(prof)
        sess = store.get(sid)
        last_seen = int(sess.meta.get("last_seen") or 0)
        new_msgs = [m for m in self.messages(rid, after_id=last_seen) if not (m["speaker"] == member and m["kind"] == "message")]
        all_ids = [m["id"] for m in self.messages(rid, after_id=last_seen)]
        if not new_msgs:
            return None
        self.rt.bus.publish("room.member_turn", room_id=rid, member=member, role=role, state="thinking")
        # The lead's turn is the drive's root: it shares the drive budget but keeps the last 10% for its summary.
        agent = Agent(self.rt, prof, sid, hitl=hitl or self.rt.default_hitl, room_id=rid, budget=budget,
                      budget_root=(role == "lead") if budget is not None else None, discussion_only=(role == "member"),
                      review_turn=budget.team_turn if budget and role == "lead" else None)
        request = "\n".join(m["content"] for m in new_msgs if m["speaker"] == "user") or new_msgs[-1]["content"]
        # Only the lead's turn does the main work; a discussion turn is a few sentences and a turn caused by an
        # a handoff is a follow-up, with a smaller budget than a lead turn.
        steps = {"member": 6, "mentioned": min(40, agent.settings.max_iterations)}.get(role)
        deadline = None
        if role == "mentioned" and getattr(budget, "fast", None) is not None and fast_reviewer(prof):
            # Fast Mode: a reviewer's @mention turn gets a review's limits (a real run did an uncounted review there).
            steps, deadline = min(steps, budget.fast.review_steps), time.time() + budget.fast.first_seconds
        result = agent.run(self._turn_prompt(room, member, new_msgs, role), meta={"room_turn": True, "role": role},
                           task_text=request[:4000], max_iterations=steps, deadline=deadline)
        seen = max(all_ids + [last_seen])
        store.patch_meta(sid, {"last_seen": seen})
        self.rt.bus.publish("room.member_turn", room_id=rid, member=member, role=role, state="done", status=result.status)
        return {"sid": sid, "store": store, "result": result, "seen": seen}

    def _post_member(self, room: dict, member: str, out: dict[str, Any] | None) -> str | None:
        if out is None:
            return None
        rid, result = room["id"], out["result"]
        text = (result.text or "").strip()
        if result.status == "error":
            self.post(rid, member, f"⚠ {member} hit an error: {(result.error or text).splitlines()[0][:300]}", kind="activity")
            return None
        if not text or text.lower().strip(" .") in PASS_TOKENS or text.lower().startswith("[pass]"):
            return None
        posted = self.post(rid, member, text, meta={"session_id": out["sid"], "run_id": result.run_id})
        # Bot messages are part of the room log; mark them seen for the speaker.
        out["store"].patch_meta(out["sid"], {"last_seen": max(out["seen"], posted["id"])})
        return text

    def _discussion_round(self, room: dict, members: list[str], hitl, budget) -> list[tuple[str, str | None]]:
        """Round-1 discussion turns are read-only and independent of each other (each member reacts to the
        human's request before the lead acts), so they run concurrently; replies are posted in roster order."""
        if len(members) <= 1:
            return [(m, self._member_turn(room, m, "member", hitl, budget)) for m in members]
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=min(4, len(members)), thread_name_prefix="room-discuss") as pool:
            futures = [(m, pool.submit(self._run_member, room, m, "member", hitl, budget)) for m in members]
            outs = [(m, f.result()) for m, f in futures]
        return [(m, self._post_member(room, m, out)) for m, out in outs]

    def _mentions(self, text: str, members: list[str]) -> list[str]:
        found = []
        for m in MENTION.findall(text or ""):
            m = m.lower()
            if m in {"all", "everyone"}:
                return list(members) + ["@all"]
            if m in members and m not in found:
                found.append(m)
        return found

    def _handoffs(self, text: str, members: list[str]) -> list[str]:
        targets = []
        for line in text.lstrip().splitlines():
            match = re.match(r"!handoff[ \t]+@([a-z0-9_-]+)[ \t]+\S", line, re.IGNORECASE)
            if match is None:
                break
            name = match[1].lower()
            if name in members and name not in targets:
                targets.append(name)
        return targets

    def drive(self, rid: str, human_msg: dict, *, hitl=None) -> dict[str, Any]:
        lock = self.drive_lock(rid)
        with lock:  # one drive per room at a time; later human messages queue behind it
            room = self.get(rid)
            members = room["members"]
            settings = room["settings"]
            max_rounds = int(settings.get("max_rounds") or MAX_ROUNDS)
            max_msgs = int(settings.get("max_messages") or MAX_MESSAGES)
            mentioned = [m for m in self._mentions(human_msg["content"], members) if m != "@all"]
            addressed = mentioned or list(members)
            lead = settings.get("lead") if settings.get("lead") in addressed else addressed[0]
            if mentioned and settings.get("lead") not in mentioned:
                lead = mentioned[0]
            from ..budget import Budget
            from .review import ReviewTurn

            lead_settings = self.rt.profiles.get(lead).settings()
            # One budget for the whole drive (all member turns and the work they delegate). Several agents share
            # it — a real implement/review loop ran out at 120 calls — so a drive gets twice the single-run budget.
            budget = Budget(lead_settings.max_run_calls * 2, lead_settings.max_run_tokens * 2)
            # The group's mode at dispatch bounds checking for the whole request.
            budget.fast = FastMode(self.rt, rid) if fast_enabled(room) else None
            budget.team_turn = ReviewTurn(self.rt.board, rid, budget.fast, user_text=human_msg["content"])
            self._budgets[rid] = budget
            posted = 0
            spoke: list[str] = []
            needs_you = False
            self.rt.bus.publish("room.drive", room_id=rid, state="started", lead=lead, addressed=addressed)
            # "settled" is published even if the drive fails: the server keeps a stopping room until it sees it.
            try:
                order = [(m, "member") for m in addressed if m != lead] + [(lead, "lead")]
                for rnd in range(1, max_rounds + 1):
                    next_round: list[str] = []
                    round_posts = 0
                    pre: dict[str, str | None] = {}
                    if rnd == 1:
                        discussants = [m for m, r in order if r == "member"]
                        pre = dict(self._discussion_round(room, discussants, hitl, budget)) if discussants else {}
                    for member, role in order:
                        if posted >= max_msgs:
                            break
                        if budget.near_limit:
                            break
                        text = pre[member] if member in pre else self._member_turn(room, member, role, hitl, budget)
                        if text is None:
                            continue
                        posted += 1
                        round_posts += 1
                        spoke.append(member)
                        # A suggestion from the opening discussion is advice to the lead, not an open request.
                        if role != "member" and re.search(r"(?<![\w.])@user\b", text, re.IGNORECASE):
                            needs_you = True
                        for m in self._handoffs(text, members):
                            if m != member and m not in next_round:
                                next_round.append(m)
                    if needs_you or posted >= max_msgs or round_posts == 0 or not next_round:
                        break
                    order = [(m, "mentioned") for m in next_round]
                needs_you = needs_you or bool(self.rt.broker.pending(room_id=rid))
                if needs_you:
                    self.update(rid, needs_you=True)
                fast_status = budget.fast.status() if budget.fast is not None else None
                if fast_status is not None:
                    summary = budget.fast.summary(fast_status)
                    if summary:
                        self.post(rid, lead, summary, kind="activity", meta={"fast_mode": fast_status})
                budget.team_turn.finish_learning(fast_status)
            finally:
                self._budgets.pop(rid, None)
                self.rt.bus.publish("room.drive", room_id=rid, state="settled", posted=posted, speakers=spoke, needs_you=needs_you)
            out = {"posted": posted, "speakers": spoke, "lead": lead, "needs_you": needs_you, "budget": budget.snapshot()}
            if budget.fast is not None:
                out["fast_mode"] = {**budget.fast.snapshot(), **fast_status}
            return out
