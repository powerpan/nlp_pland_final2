"""Group rooms: several bots and the human in one conversation (Bot Mode group chat).

Turn-taking follows Hermes' group-room design, adapted so that collaboration produces real work:

* A human message addresses the @mentioned bots (`@all`/`@everyone` or no mention = every member).
* One addressed bot *leads* the response: the room's configured lead if addressed, else the first
  @mentioned bot, else the first member. Nothing about the lead is a fixed role — any bot can lead.
* Round 1: the other addressed bots speak first (brief: what they can contribute, risks, or
  `[PASS]`), then the lead acts on the request with full tools — typically decomposing it on the
  team board and handing subtasks to teammates with `delegate_task`, which really executes them in
  the teammates' own profiles, then integrating the results.
* Later rounds: bots @mentioned by bots get a turn; the room settles when a round is silent or
  limits are hit (max rounds / messages). A bot writing `@user` raises the room's "needs you" flag.
* Every member keeps one persistent room session (its private view of the room) and sees only the
  room messages posted since its last turn, plus its own memory. Private Bot Chats stay separate.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..sessions import SessionStore
from ..store import dumps, loads, new_id, now

if TYPE_CHECKING:
    from ..runtime import Runtime

MENTION = re.compile(r"(?<![\w.])@([a-z0-9][a-z0-9_-]{0,31})", re.IGNORECASE)
PASS_TOKENS = {"[pass]", "pass", "[silent]", "no_reply", "[no_reply]"}
MAX_ROUNDS = 3
MAX_MESSAGES = 12


class RoomManager:
    def __init__(self, runtime: "Runtime"):
        self.rt = runtime
        self.db = runtime.shared
        self._drive_locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    # ------------------------------------------------------------------ CRUD
    def _row(self, r: dict[str, Any] | None) -> dict[str, Any] | None:
        if r is None:
            return None
        r = dict(r)
        r["members"] = loads(r["members"], [])
        r["settings"] = loads(r["settings"], {})
        r["needs_you"] = bool(r["needs_you"])
        return r

    def create(self, name: str, members: list[str], *, lead: str | None = None) -> dict[str, Any]:
        members = [m.lstrip("@") for m in members]
        missing = [m for m in members if not self.rt.profiles.exists(m)]
        if missing:
            raise ValueError(f"unknown bots: {', '.join(missing)}")
        if not 1 <= len(members) <= 8:
            raise ValueError("a room needs 1-8 bots")
        if self.db.one("SELECT id FROM rooms WHERE name=?", (name,)):
            raise ValueError(f"a room named {name!r} already exists")
        rid = new_id("room_")
        settings = {"lead": lead.lstrip("@") if lead else None, "max_rounds": MAX_ROUNDS, "max_messages": MAX_MESSAGES}
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
            raise KeyError(rid)
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
        self.db.execute("DELETE FROM rooms WHERE id=?", (rid,))
        self.rt.bus.publish("room.deleted", room_id=rid)

    def shared_dir(self, rid: str) -> Path:
        path = self.rt.root / "rooms" / rid / "shared"
        path.mkdir(parents=True, exist_ok=True)
        return path

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
            raise KeyError(rid)
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
            lines.append(
                "You lead the response to the latest request. Act on it now. For multi-part work: record the plan with "
                "team_tasks, then hand each substantial subtask to the best-suited teammate with delegate_task (pass the "
                "board task_id; delegates execute with their own tools and report back; independent subtasks in one call run "
                "in parallel; sequence dependent ones — a task whose prerequisites are unfinished is refused). When a room "
                "member's role matches part of the request (research → researcher, tests → tester, review → reviewer), "
                "delegate that part to them: the team exists so specialists do their parts. Do small glue work yourself. "
                "Deliverables the team shares go in `shared/` (works in file tools and shell commands). Verify the integrated "
                "result yourself, then post a concise final reply. Ask the human with ask_user only if a decision is "
                "genuinely theirs."
            )
        elif role == "member":
            lines.append(
                "A teammate leads this request and will delegate the work. This is a discussion turn: you can read and look "
                "things up, but you cannot change files or run code now. Reply only if you add something useful — the part "
                "you are best suited for, a risk, or information you have — in at most 3 sentences. Otherwise reply exactly [PASS]."
            )
        else:
            lines.append(
                "You were @mentioned above. Do what was asked of you (use your tools if work is needed) and reply briefly. "
                "Do not redo or re-verify work others already verified. If nothing is actually required of you, reply exactly [PASS]."
            )
        lines.append("Write @name only when you need that teammate to act or answer now — never to thank, acknowledge, or say "
                     "nothing is needed (every @mention costs that teammate a turn). Use @user only to hand a question to the human.")
        return "\n".join(lines)

    def _member_turn(self, room: dict, member: str, role: str, hitl, budget=None) -> str | None:
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
        agent = Agent(self.rt, prof, sid, hitl=hitl or self.rt.default_hitl, room_id=rid, budget=budget,
                      discussion_only=(role == "member"))
        request = "\n".join(m["content"] for m in new_msgs if m["speaker"] == "user") or new_msgs[-1]["content"]
        result = agent.run(self._turn_prompt(room, member, new_msgs, role), meta={"room_turn": True, "role": role},
                           task_text=request[:4000])
        seen = max(all_ids + [last_seen])
        store.patch_meta(sid, {"last_seen": seen})
        self.rt.bus.publish("room.member_turn", room_id=rid, member=member, role=role, state="done", status=result.status)
        text = (result.text or "").strip()
        if result.status == "error":
            self.post(rid, member, f"⚠ {member} hit an error: {(result.error or text).splitlines()[0][:300]}", kind="activity")
            return None
        if not text or text.lower().strip(" .") in PASS_TOKENS or text.lower().startswith("[pass]"):
            return None
        posted = self.post(rid, member, text, meta={"session_id": sid, "run_id": result.run_id})
        # Bot messages are part of the room log; mark them seen for the speaker.
        store.patch_meta(sid, {"last_seen": max(seen, posted["id"])})
        return text

    def _mentions(self, text: str, members: list[str]) -> list[str]:
        found = []
        for m in MENTION.findall(text or ""):
            m = m.lower()
            if m in {"all", "everyone"}:
                return list(members) + ["@all"]
            if m in members and m not in found:
                found.append(m)
        return found

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

            lead_settings = self.rt.profiles.get(lead).settings()
            # One budget for the whole drive (all member turns and the work they delegate).
            budget = Budget(lead_settings.max_run_calls, lead_settings.max_run_tokens)
            posted = 0
            spoke: list[str] = []
            needs_you = False
            self.rt.bus.publish("room.drive", room_id=rid, state="started", lead=lead, addressed=addressed)
            order = [(m, "member") for m in addressed if m != lead] + [(lead, "lead")]
            for rnd in range(1, max_rounds + 1):
                next_round: list[str] = []
                round_posts = 0
                for member, role in order:
                    if posted >= max_msgs:
                        break
                    if budget.near_limit:
                        break
                    text = self._member_turn(room, member, role, hitl, budget)
                    if text is None:
                        continue
                    posted += 1
                    round_posts += 1
                    spoke.append(member)
                    if re.search(r"(?<![\w.])@user\b", text, re.IGNORECASE):
                        needs_you = True
                    for m in self._mentions(text, members):
                        if m != "@all" and m != member and m not in next_round:
                            next_round.append(m)
                if needs_you or posted >= max_msgs or round_posts == 0 or not next_round:
                    break
                order = [(m, "mentioned") for m in next_round]
            if needs_you:
                self.update(rid, needs_you=True)
            self.rt.bus.publish("room.drive", room_id=rid, state="settled", posted=posted, speakers=spoke, needs_you=needs_you)
            return {"posted": posted, "speakers": spoke, "lead": lead, "needs_you": needs_you, "budget": budget.snapshot()}
