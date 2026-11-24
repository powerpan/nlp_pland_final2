"""Guardrails for real model usage: per-run budgets and a per-call ledger.

A top-level run (a user task, a room turn, an evaluation task) owns one `Budget`; every delegate and
subagent it spawns charges the same budget, so a whole collaboration tree is capped together.
The project's DeepSeek guide suggests 120 model calls and 3M tokens per run (cache hits counted as 0.1
token); PlanD started there and raised the defaults (AgentSettings.max_run_calls / max_run_tokens: 300 calls,
8M tokens) after real team tasks ran out — the caps still apply to every run. The last 10% is reserved for
the root agent to write its summary: once 90% is used, non-root agents stop and new delegations are refused.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from .llm.base import Usage
from .llm.pricing import cost
from .store import DB, new_id


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Budget:
    max_calls: int = 300
    max_tokens: float = 8_000_000
    calls: int = 0
    usage: Usage = field(default_factory=Usage)
    started: float = field(default_factory=time.time)
    root_run: str = field(default_factory=lambda: new_id("w_"))

    def __post_init__(self):
        self._lock = threading.Lock()

    @property
    def fraction(self) -> float:
        return max(self.calls / self.max_calls, self.usage.weighted_tokens / self.max_tokens)

    @property
    def near_limit(self) -> bool:
        return self.fraction >= 0.9

    def check(self, *, root: bool) -> None:
        with self._lock:
            limit = 1.0 if root else 0.9
            if self.fraction >= limit:
                raise BudgetExceeded(
                    f"run budget exhausted ({self.calls}/{self.max_calls} calls, "
                    f"{int(self.usage.weighted_tokens)}/{int(self.max_tokens)} weighted tokens)"
                )
            self.calls += 1

    def charge(self, usage: Usage) -> None:
        with self._lock:
            self.usage.add(usage)

    def describe(self) -> str:
        """One line for agents: what this run has used of its caps."""
        return (f"{self.calls}/{self.max_calls} model calls and {int(self.usage.weighted_tokens):,}/"
                f"{int(self.max_tokens):,} weighted tokens used ({round(self.fraction * 100)}%)")

    def snapshot(self) -> dict:
        return {"calls": self.calls, "prompt_tokens": self.usage.prompt_tokens, "cached_tokens": self.usage.cached_tokens,
                "completion_tokens": self.usage.completion_tokens, "weighted_tokens": int(self.usage.weighted_tokens),
                "cost_usd": round(self.usage.cost_usd, 5), "fraction": round(self.fraction, 3)}


class Ledger:
    """Append-only record of every model call (no message content, no secrets)."""

    def __init__(self, db: DB):
        self.db = db

    def record(self, *, root_run: str, run_id: str, profile: str, session_id: str, purpose: str, model: str,
               usage: Usage, duration: float, ok: bool, error: str | None = None) -> None:
        self.db.execute(
            "INSERT INTO llm_calls(ts, root_run, run_id, profile, session_id, purpose, model, prompt_tokens, cached_tokens,"
            " completion_tokens, duration, ok, error) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (time.time(), root_run, run_id, profile, session_id, purpose, model, usage.prompt_tokens, usage.cached_tokens,
             usage.completion_tokens, round(duration, 3), int(ok), (error or "")[:300]),
        )

    def totals(self, root_run: str | None = None, since: float | None = None) -> dict:
        sql = ("SELECT COUNT(*) calls, COALESCE(SUM(prompt_tokens),0) prompt, COALESCE(SUM(cached_tokens),0) cached,"
               " COALESCE(SUM(completion_tokens),0) completion, COALESCE(SUM(duration),0) seconds FROM llm_calls WHERE 1=1")
        params: list = []
        if root_run:
            sql += " AND root_run=?"
            params.append(root_run)
        if since:
            sql += " AND ts>=?"
            params.append(since)
        row = self.db.one(sql, params) or {}
        u = Usage(int(row.get("prompt") or 0), int(row.get("completion") or 0), int(row.get("cached") or 0))
        # cost per model (prices differ ~4-7x between flash and pro)
        by_model = self.db.query(sql.replace("SELECT COUNT(*) calls,", "SELECT model, COUNT(*) calls,") + " GROUP BY model", params)
        total_cost = sum(cost(int(r["prompt"] or 0), int(r["cached"] or 0), int(r["completion"] or 0), r["model"]) for r in by_model)
        return {"calls": int(row.get("calls") or 0), "prompt_tokens": u.prompt_tokens, "cached_tokens": u.cached_tokens,
                "completion_tokens": u.completion_tokens, "cache_hit_rate": round(u.cached_tokens / u.prompt_tokens, 3) if u.prompt_tokens else 0.0,
                "cost_usd": round(total_cost, 5), "model_seconds": round(float(row.get("seconds") or 0), 1),
                "models": sorted({r["model"] for r in by_model if r["model"]})}
