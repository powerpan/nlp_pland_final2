"""Team task board: the shared, explicit record of how a goal was decomposed and who owns what.

Boards are scoped: a group room has one board (scope = room id); outside rooms, the scope is the
delegating agent's own name (`dm:<profile>`). Delegations linked to a board task update its status
automatically (todo → in_progress → done/failed) and store the delegate's report as the result.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..store import dumps, loads, new_id, now

if TYPE_CHECKING:
    from ..runtime import Runtime

STATUSES = ("todo", "in_progress", "done", "failed", "blocked")


class TaskBoard:
    def __init__(self, runtime: "Runtime"):
        self.rt = runtime
        self.db = runtime.shared

    def _row(self, r: dict[str, Any]) -> dict[str, Any]:
        r = dict(r)
        r["depends_on"] = loads(r.get("depends_on"), [])
        return r

    def add(self, scope: str, title: str, *, description: str = "", assignee: str | None = None, created_by: str,
            parent_id: str | None = None, depends_on: list[str] | None = None) -> dict[str, Any]:
        tid = new_id("t_")
        ts = now()
        self.db.execute(
            "INSERT INTO team_tasks(id, room_id, title, description, assignee, status, created_by, parent_id, depends_on, created, updated)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (tid, scope, title, description, assignee, "todo", created_by, parent_id, dumps(depends_on or []), ts, ts),
        )
        task = self.get(tid)
        self.rt.bus.publish("task.updated", room_id=scope, task=task)
        return task

    def get(self, tid: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM team_tasks WHERE id=?", (tid,))
        if row is None:
            raise KeyError(f"no task {tid}")
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
        if status:
            rows = self.db.query("SELECT * FROM team_tasks WHERE room_id=? AND status=? ORDER BY created", (scope, status))
        else:
            rows = self.db.query("SELECT * FROM team_tasks WHERE room_id=? ORDER BY created", (scope,))
        return [self._row(r) for r in rows]

    def render(self, scope: str) -> str:
        tasks = self.list(scope)
        if not tasks:
            return "(board is empty)"
        lines = []
        for t in tasks:
            deps = f" deps={','.join(t['depends_on'])}" if t["depends_on"] else ""
            who = f" @{t['assignee']}" if t["assignee"] else " (unassigned)"
            res = f"\n    result: {t['result'][:300]}" if t.get("result") else ""
            lines.append(f"- [{t['status']}] {t['id']}: {t['title']}{who}{deps}{res}")
        return "\n".join(lines)
