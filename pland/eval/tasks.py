"""Load evaluation tasks (format: pland/eval/SCHEMA.md)."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SUITES_DIR = Path(__file__).parent / "suites"


@dataclass
class Task:
    id: str
    prompt: str
    title: str = ""
    category: str = "other"
    mode: str = "single"
    team: dict[str, Any] = field(default_factory=dict)
    setup: dict[str, Any] = field(default_factory=dict)
    hitl: dict[str, Any] = field(default_factory=dict)
    timeout: float = 600
    max_iterations: int = 40
    memory: str = "carry"
    checks: list[dict[str, Any]] = field(default_factory=list)
    required: list[str] | None = None
    source: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: str = "") -> "Task":
        data = normalize_aliases(data)
        if not data.get("id") or not data.get("prompt"):
            raise ValueError(f"task in {source or '?'} needs 'id' and 'prompt'")
        checks = []
        for i, c in enumerate(data.get("checks") or []):
            c = dict(c)
            c.setdefault("id", f"{c.get('type', 'check')}-{i + 1}")
            checks.append(c)
        return cls(
            id=str(data["id"]), prompt=str(data["prompt"]), title=str(data.get("title") or data["id"]),
            category=str(data.get("category") or "other"), mode=str(data.get("mode") or "single"),
            team=dict(data.get("team") or {}), setup=dict(data.get("setup") or {}), hitl=dict(data.get("hitl") or {}),
            timeout=float(data.get("timeout") or 600), max_iterations=int(data.get("max_iterations") or 40),
            memory=str(data.get("memory") or "carry"), checks=checks, required=data.get("required"), source=source,
        )

    @property
    def required_ids(self) -> list[str]:
        return list(self.required) if self.required else [c["id"] for c in self.checks]


_ID_KEYS = ("id", "task_id", "taskId", "name", "uid")
_PROMPT_KEYS = ("prompt", "instruction", "instructions", "question", "task", "input", "query", "goal")
_EXPECT_KEYS = ("expected_answer", "expected_output", "expected", "answer", "reference_answer", "ground_truth")


def normalize_aliases(data: dict[str, Any]) -> dict[str, Any]:
    """Accept common field names of other task formats, so an unseen (closed) test set can be run as-is.
    An expected answer without explicit checks becomes a case-insensitive `answer_contains` check."""
    data = dict(data)
    if not data.get("id"):
        for k in _ID_KEYS[1:]:
            if data.get(k):
                data["id"] = str(data[k])
                break
    if not data.get("prompt"):
        for k in _PROMPT_KEYS[1:]:
            if isinstance(data.get(k), str) and data[k].strip():
                data["prompt"] = data[k]
                break
    if not data.get("checks"):
        for k in _EXPECT_KEYS:
            val = data.get(k)
            if val not in (None, "") and not isinstance(val, (dict, list)):
                data["checks"] = [{"id": "expected-answer", "type": "answer_contains",
                                   "pattern": "(?i)" + re.escape(str(val).strip())}]
                break
    return data


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def resolve_suite(name_or_path: str) -> Path:
    p = Path(name_or_path).expanduser()
    if p.exists():
        return p.resolve()
    candidate = SUITES_DIR / name_or_path
    if candidate.exists():
        return candidate.resolve()
    raise FileNotFoundError(f"no suite '{name_or_path}' (looked in {SUITES_DIR} and the filesystem)")


def load_suite(path: Path) -> tuple[dict[str, Any], list[Task]]:
    meta: dict[str, Any] = {"name": path.stem if path.is_file() else path.name}
    raw: list[tuple[dict, str]] = []
    if path.is_file():
        files = [path]
    else:
        suite_file = path / "suite.yaml"
        if suite_file.exists():
            meta.update(yaml.safe_load(suite_file.read_text(encoding="utf-8")) or {})
        files = sorted(f for f in path.iterdir() if f.is_file() and f.name != "suite.yaml"
                       and f.suffix.lower() in {".yaml", ".yml", ".json", ".jsonl"})
    for f in files:
        text = f.read_text(encoding="utf-8")
        if f.suffix.lower() == ".jsonl":
            for i, line in enumerate(text.splitlines()):
                if line.strip():
                    raw.append((json.loads(line), f"{f.name}:{i + 1}"))
        elif f.suffix.lower() == ".json":
            data = json.loads(text)
            for item in data if isinstance(data, list) else [data]:
                raw.append((item, f.name))
        else:
            data = yaml.safe_load(text)
            if isinstance(data, dict) and "tasks" in data and "prompt" not in data:
                meta.update({k: v for k, v in data.items() if k != "tasks"})
                for item in data["tasks"]:
                    raw.append((item, f.name))
            else:
                for item in data if isinstance(data, list) else [data]:
                    raw.append((item, f.name))
    defaults = meta.get("defaults") or {}
    tasks = [Task.from_dict(_deep_merge(defaults, item), src) for item, src in raw]
    order = meta.get("order")
    if order:
        rank = {tid: i for i, tid in enumerate(order)}
        tasks.sort(key=lambda t: rank.get(t.id, len(rank)))
    ids = [t.id for t in tasks]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate task ids: {sorted(dupes)}")
    return meta, tasks
