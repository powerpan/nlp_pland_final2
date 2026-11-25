"""Import a team's roster and role prompts from a Mid_Test-style Markdown file."""
from __future__ import annotations

import re
from threading import Lock
from typing import TYPE_CHECKING

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode

from ..profiles import NAME_RE

if TYPE_CHECKING:
    from ..runtime import Runtime


class TeamFileConflict(ValueError):
    """An existing profile or room uses the name for a different configuration."""


_import_lock = Lock()


def parse_role_file(text: str) -> tuple[str, dict[str, tuple[str, str]]]:
    if len(text.encode("utf-8")) > 256 * 1024:
        raise ValueError("Team files must be 256 KiB or smaller.")
    text = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    document = SyntaxTreeNode(MarkdownIt("commonmark").enable("table").parse(text)).children
    titles = [n.children[0].content for n in document if n.tag == "h1"]
    if len(titles) != 1 or not (team := re.sub(r"^Scenario\s+\d+\s*[:：]\s*", "", titles[0], flags=re.I).strip()):
        raise ValueError("The team file needs one main heading with the group name.")

    roles: dict[str, str] = {}
    tables = [n for n in document if n.type == "table"]
    for table in tables:
        header, *body = table.children
        columns = [cell.children[0].content.strip().lower() for cell in header.children[0].children]
        if columns != ["agent id", "role"]:
            continue
        if roles or not body:
            raise ValueError("Use one Agent ID / Role table with 1 to 8 bots.")
        for row in body[0].children:
            handle, title = (cell.children[0].content.strip() for cell in row.children)
            if handle.startswith("`") and handle.endswith("`"):
                handle = handle[1:-1]
            if not NAME_RE.fullmatch(handle) or handle in {"default", "user", "system"} or not title or handle in roles:
                raise ValueError(f"Invalid, reserved or duplicate bot in the role table: {handle}")
            roles[handle] = title
    if not 1 <= len(roles) <= 8:
        raise ValueError("Use one Agent ID / Role table with 1 to 8 bots.")

    prompts: dict[str, str] = {}
    for index, node in enumerate(document):
        if node.tag != "h2":
            continue
        heading = node.children[0].content.strip()
        match = re.fullmatch(r"(.+?)\s*\(([^()]+)\)", heading)
        if not match or roles.get(handle := match[2]) != match[1].strip() or handle in prompts:
            raise ValueError(f"Role heading does not match a unique table entry: {heading}")
        block = document[index + 1] if index + 1 < len(document) else None
        if not block or block.type != "fence" or not block.content.strip():
            raise ValueError(f"Add a fenced role prompt below the heading for @{handle}.")
        # CommonMark allows a fence to end at EOF. An unfinished file could swallow other roles.
        end = lines[block.map[1] - 1].strip()
        if len(end) < len(block.markup) or end.strip(block.markup[0]):
            raise ValueError(f"Close the fenced role prompt for @{handle}.")
        prompts[handle] = block.content.strip()
    missing = [f"@{name}" for name in roles if name not in prompts]
    if missing:
        raise ValueError(f"Missing role prompts: {', '.join(missing)}")
    return team, {name: (title, prompts[name]) for name, title in roles.items()}


def import_role_file(rt: "Runtime", text: str) -> dict:
    team, roles = parse_role_file(text)
    lead = next(iter(roles))
    with _import_lock:
        room = rt.rooms.by_name(team)
        new_group = room is None
        if room and (set(room["members"]) != set(roles) or room["settings"].get("lead") != lead):
            raise TeamFileConflict(f"The existing group has different members or a different lead: {team}")
        missing = []
        for name, (title, prompt) in roles.items():
            if not rt.profiles.exists(name):
                missing.append(name)
                continue
            profile = rt.profiles.get(name)
            if not profile.is_bot or profile.title != title or profile.soul != prompt:
                raise TeamFileConflict(f"@{name} already exists with a different role. Choose a new ID or edit the existing bot.")
        created = []
        try:
            for name in missing:
                title, prompt = roles[name]
                rt.profiles.create(name, title=title, soul=prompt, description=" ".join(prompt.split())[:350], bot=True)
                created.append(name)
            if room is None:
                room = rt.rooms.create(team, list(roles), lead=lead)
        except Exception:
            # Undo only this attempt's unassigned profiles. A concurrently created group may already use one.
            assigned = {name for group in rt.rooms.list() for name in group["members"]}
            for name in created:
                if name not in assigned:
                    rt.profiles.delete(name)
            raise
        for name in created:
            rt.bus.publish("profile.created", profile=name)
        return {"group": room["id"], "name": team, "lead": lead, "members": list(roles),
                "created_group": new_group, "created_bots": created}
