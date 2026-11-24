"""Team templates: a ready-made set of bots and groups, added to Bot Mode on request.

PlanD has no built-in roles (requirements §12); a template is just data — bot identities, settings and
SOULs plus group rosters — applied with `pland team apply <id>`, the web UI's "Team templates" dialog or
`POST /api/team-templates/<id>/apply`. Existing bots and groups are left alone unless `update=True`.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from ..llm import reasoning

if TYPE_CHECKING:
    from ..runtime import Runtime

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "team_templates"


def list_templates() -> list[dict[str, Any]]:
    out = []
    for path in sorted(TEMPLATES_DIR.glob("*.yaml")):
        t = load_template(path.stem)
        out.append({"id": t["id"], "title": t.get("title", t["id"]), "description": t.get("description", ""),
                    "bots": [{k: b.get(k) for k in ("name", "title", "description", "reasoning", "backend", "toolsets")}
                             for b in t.get("bots", [])],
                    "groups": t.get("groups", [])})
    return out


def load_template(template_id: str) -> dict[str, Any]:
    path = TEMPLATES_DIR / f"{template_id}.yaml"
    if not path.is_file() or path.resolve().parent != TEMPLATES_DIR:
        raise KeyError(f"no team template '{template_id}'")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault("id", template_id)
    return data


def _settings(bot: dict[str, Any], docker_ok: bool) -> tuple[dict[str, Any], str | None]:
    model: dict[str, Any] = {}
    if bot.get("model"):
        model["model"] = bot["model"]
    if "reasoning" in bot:
        model.update(reasoning.to_settings(bot["reasoning"]))
    settings: dict[str, Any] = {"model": model} if model else {}
    note = None
    backend = bot.get("backend")
    if backend == "docker" and not docker_ok:
        backend, note = "local", f"@{bot['name']}: Docker is not available, so it runs commands locally"
    if backend:
        settings["sandbox"] = {"backend": backend}
    if bot.get("toolsets"):
        settings["toolsets"] = list(bot["toolsets"])
    if bot.get("approvals"):
        settings["approvals"] = {"mode": bot["approvals"]}
    return settings, note


def apply_template(rt: "Runtime", template_id: str, *, update: bool = False) -> dict[str, Any]:
    """Create the template's bots and groups. Returns what was created, updated, skipped and any notes."""
    from ..sandbox import DockerBackend

    t = load_template(template_id)
    docker_ok = DockerBackend.available()
    report: dict[str, Any] = {"template": t["id"], "created": [], "updated": [], "skipped": [], "groups": [], "notes": []}
    for bot in t.get("bots", []):
        name = bot["name"]
        settings, note = _settings(bot, docker_ok)
        if note:
            report["notes"].append(note)
        fields = {"title": bot.get("title"), "description": bot.get("description", ""), "soul": bot.get("soul"),
                  "avatar": bot.get("avatar")}
        if rt.profiles.exists(name):
            if update:
                rt.profiles.update(name, settings=settings, bot=True, **fields)
                report["updated"].append(name)
            else:
                report["skipped"].append(name)
            continue
        rt.profiles.create(name, bot=True, settings=settings, **fields)
        report["created"].append(name)
    for group in t.get("groups", []):
        existing = rt.rooms.by_name(group["name"])
        if existing:
            report["groups"].append({"name": group["name"], "id": existing["id"], "status": "exists"})
            continue
        room = rt.rooms.create(group["name"], group["members"], lead=group.get("lead"))
        report["groups"].append({"name": group["name"], "id": room["id"], "status": "created"})
    return report
