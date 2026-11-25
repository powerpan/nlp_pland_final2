"""Team task board: the shared, explicit record of how a goal was decomposed and who owns what.

Boards are scoped: a group room has one board (scope = room id); outside rooms, the scope is the
delegating agent's own name (`dm:<profile>`). Delegations linked to a board task update its status
automatically (todo → in_progress → done/failed) and store the delegate's report as the result.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..errors import NotFound
from ..store import dumps, loads, new_id, now
from .review import public_review, review_file_state
from .fast import scope_lines

if TYPE_CHECKING:
    from ..runtime import Runtime

STATUSES = ("todo", "in_progress", "done", "failed", "blocked")
TASK_ROWS = ("SELECT t.*, r.data AS review_data FROM team_tasks t "
             "LEFT JOIN team_reviews r ON r.task_id=t.id")


class TaskBoard:
    def __init__(self, runtime: "Runtime"):
        self.rt = runtime
        self.db = runtime.shared

    def _row(self, r: dict[str, Any]) -> dict[str, Any]:
        r = dict(r)
        r["depends_on"] = loads(r.get("depends_on"), [])
        # Older cards sometimes stored the displayed position instead of the task ID.
        if any(str(ref).removeprefix("#").isdecimal() for ref in r["depends_on"]):
            r["depends_on"] = self._dependency_ids(r["room_id"], r["depends_on"], before=r["id"])
        review = loads(r.pop("review_data"), None)
        if review is not None:
            if r["status"] in {"done", "blocked"} and review["verdict"] in {"pass", "fail"}:
                root = self.rt.rooms.shared_dir(r["room_id"])
                current, changed = review_file_state(root, review)
                if not current:
                    review["changed_inputs"] = changed
                    review["verdict"] = "stale"
                    r["status"] = "blocked"
                    r["result"] = "[Reviewed files changed. A new review is needed.]\n" + (r.get("result") or "")
            r["review"] = public_review(review)
        return r

    def record_review(self, tid: str, review: dict[str, Any]) -> None:
        self.db.execute("INSERT OR REPLACE INTO team_reviews(task_id, data) VALUES (?,?)", (tid, dumps(review)))

    def review_record(self, tid: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT data FROM team_reviews WHERE task_id=?", (tid,))
        return loads(row["data"], None) if row is not None else None

    def reviewed(self, scope: str) -> list[dict[str, Any]]:
        return [self._row(r) for r in self.db.query(TASK_ROWS + " WHERE t.room_id=? AND r.data IS NOT NULL ORDER BY t.created",
                                                   (scope,))]

    def _dependency_ids(self, scope: str, refs: list[str], *, before: str | None = None) -> list[str]:
        if not refs:
            return []
        sql = "SELECT id FROM team_tasks WHERE room_id=?"
        args = [scope]
        if before:
            sql += " AND rowid < (SELECT rowid FROM team_tasks WHERE id=?)"
            args.append(before)
        ids = [row["id"] for row in self.db.query(sql + " ORDER BY rowid", args)]
        positions = {str(i): tid for i, tid in enumerate(ids, 1)}
        resolved = []
        for ref in refs:
            tid = positions.get(str(ref).removeprefix("#"), str(ref))
            if tid not in ids and not before:
                raise ValueError(f"Unknown prerequisite {ref!r} on this board. List the board and use an existing task ID or number.")
            # Keep a dangling legacy reference visible; dispatch must reject it.
            if tid not in resolved:
                resolved.append(tid)
        return resolved

    def add(self, scope: str, title: str, *, description: str = "", assignee: str | None = None, created_by: str,
            parent_id: str | None = None, depends_on: list[str] | None = None,
            conflict_source: str | None = None) -> dict[str, Any]:
        tid = new_id("t_")
        ts = now()
        self.db.execute(
            "INSERT INTO team_tasks(id, room_id, title, description, assignee, status, created_by, parent_id, depends_on, created, updated, conflict_source)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (tid, scope, title, description, assignee, "blocked" if conflict_source else "todo", created_by, parent_id,
             dumps(self._dependency_ids(scope, depends_on or [])), ts, ts, conflict_source),
        )
        task = self.get(tid)
        self.rt.bus.publish("task.updated", room_id=scope, task=task)
        return task

    def get(self, tid: str) -> dict[str, Any]:
        row = self.db.one(TASK_ROWS + " WHERE t.id=?", (tid,))
        if row is None:
            raise NotFound(f"no task {tid}")
        return self._row(row)

    def update(self, tid: str, **fields: Any) -> dict[str, Any]:
        allowed = {"title", "description", "assignee", "status", "result"}
        sets, params = [], []
        for key, val in fields.items():
            if key in allowed and val is not None:
                if key == "status" and val not in STATUSES:
                    raise ValueError(f"status must be one of {STATUSES}")
                sets.append(f"{key}=?")
                params.append(val if key != "result" else str(val)[:8000])
        if not sets:
            return self.get(tid)
        sets.append("updated=?")
        params += [now(), tid]
        self.db.execute(f"UPDATE team_tasks SET {', '.join(sets)} WHERE id=?", params)
        task = self.get(tid)
        self.rt.bus.publish("task.updated", room_id=task["room_id"], task=task)
        return task

    def list(self, scope: str, status: str | None = None) -> list[dict[str, Any]]:
        rows = self.db.query(TASK_ROWS + " WHERE t.room_id=? ORDER BY t.rowid", (scope,))
        tasks = [self._row(r) for r in rows]
        return [t for t in tasks if t["status"] == status] if status else tasks

    def render(self, scope: str) -> str:
        tasks = self.list(scope)
        if not tasks:
            return "(board is empty)"
        lines = []
        for number, t in enumerate(tasks, 1):
            deps = f" deps={','.join(t['depends_on'])}" if t["depends_on"] else ""
            who = f" @{t['assignee']}" if t["assignee"] else " (unassigned)"
            if t.get("conflict_source"):
                who += f" — disputed: {t['description']}; check against {t['conflict_source']}"
            res = f"\n    result: {t['result'][:300]}" if t.get("result") else ""
            if review := t.get("review"):
                res = (f"\n    acceptance: {review.get('criterion') or t['title']} — {review['verdict'].upper()}"
                       f"\n    inputs: {', '.join(review['inputs'])}" + res)
            lines.append(f"- [{t['status']}] {t['id']} (#{number}): {t['title']}{who}{deps}{scope_lines(self.rt, t)}{res}")
        return "\n".join(lines)
