"""Profiles: the unit of agent identity and isolation.

A profile is a directory `<PLAND_HOME>/profiles/<name>/` holding everything that belongs to one
agent: its configuration (`profile.yaml`), persona (`SOUL.md`), bounded memories, skills, private
state database and a private workspace. A Bot in Bot Mode *is* a profile that carries roster
metadata (`bot: true`, title, avatar) plus one canonical "Bot Chat" session, so the same agent is
reachable from the CLI (`pland chat -p <name>`) and from the web UI.

Profiles isolate state logically (different directories, databases and tool roots). They are not
an OS sandbox by themselves — see pland/sandbox for execution isolation and its limits.
"""

from __future__ import annotations

import re
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .config import AgentSettings, global_settings, merge_settings, pland_home
from .store import DB, now, profile_db

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")

DEFAULT_SOUL = """You are a capable, careful autonomous agent. You complete tasks by actually doing them with your tools
(files, code execution, web, git) rather than describing steps, you verify your work, and you ask the human when an
instruction is ambiguous or a decision is theirs.
Be direct: match the length of your reply to the weight of the ask. Finished work gets a short report of what changed,
what is verified and what is left — not a replay of the process. No filler, no restating the request, no narrating
tool calls the user can see. Plain claims over adjectives; when unsure, say so plainly. Reply in the user's language.
"""

# Pigment colours for bot tiles (the web UI picks from the same list for new bots).
AVATAR_COLORS = ["#c8462a", "#33508c", "#4e7a4a", "#b07a1e", "#7a3e6a", "#2b7a78", "#5b6472", "#9a4a2e", "#6e7b2f", "#3a4fb8"]


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower()).strip("-_")
    return slug[:32] or "agent"


@dataclass
class Profile:
    name: str
    home: Path
    meta: dict[str, Any]

    # ----------------------------------------------------------------- paths
    @property
    def workspace(self) -> Path:
        p = self.home / "workspace"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def memories_dir(self) -> Path:
        p = self.home / "memories"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def skills_dir(self) -> Path:
        p = self.home / "skills"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db(self) -> DB:
        return profile_db(self.home)

    # ----------------------------------------------------------------- identity
    @property
    def title(self) -> str:
        return self.meta.get("title") or self.name

    @property
    def description(self) -> str:
        return self.meta.get("description") or ""

    @property
    def is_bot(self) -> bool:
        return bool(self.meta.get("bot"))

    @property
    def avatar(self) -> str:
        return self.meta.get("avatar") or AVATAR_COLORS[sum(map(ord, self.name)) % len(AVATAR_COLORS)]

    @property
    def soul(self) -> str:
        path = self.home / "SOUL.md"
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return DEFAULT_SOUL.strip()

    def settings(self) -> AgentSettings:
        """This profile's settings on top of the global defaults (PLAND_HOME/settings.yaml)."""
        root = self.home.parent.parent
        return AgentSettings.from_dict(merge_settings(global_settings(root), self.meta.get("settings")))

    def summary(self) -> dict[str, Any]:
        s = self.settings()
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "bot": self.is_bot,
            "avatar": self.avatar,
            "provider": s.model.provider,
            "model": s.model.resolved().model if s.model.provider else None,
            "toolsets": s.toolsets,
            "backend": s.sandbox.backend,
            "created": self.meta.get("created"),
        }

    # ----------------------------------------------------------------- persistence
    def save_meta(self) -> None:
        (self.home / "profile.yaml").write_text(
            yaml.safe_dump(self.meta, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    def bot_chats(self) -> list[dict[str, Any]]:
        """The bot's Bot Chats, most recently used first: one per working folder (workspace None = its private
        workspace). A bot has no other conversation list, so folders are what separate its contexts."""
        from .store import loads

        rows = self.db.query("SELECT id, title, meta, updated, created FROM sessions WHERE kind='bot_chat' "
                             "ORDER BY updated DESC, created DESC")
        return [{"id": r["id"], "title": r["title"], "workspace": loads(r["meta"], {}).get("workspace") or None,
                 "updated": r["updated"], "created": r["created"]} for r in rows]

    def bot_chat_id(self, folder: str | None = None, *, create: bool = True) -> str | None:
        """The Bot Chat for a working folder (None: the private workspace), created on first use. Switching a
        bot to another folder opens that folder's chat instead of mixing two projects in one context."""
        folder = str(folder) if folder else None
        for chat in sorted(self.bot_chats(), key=lambda c: c["created"]):
            if chat["workspace"] == folder:
                return chat["id"]
        if not create:
            return None
        from .sessions import SessionStore

        title = f"Bot Chat · {Path(folder).name}" if folder else "Bot Chat"
        return SessionStore(self).create(title=title, kind="bot_chat", meta={"workspace": folder} if folder else None).id

    def canonical_chat_id(self) -> str:
        """The bot's home Bot Chat (its private workspace), created on first use; messages from other bots
        (message_agent) arrive here."""
        return self.bot_chat_id(None)

    def latest_bot_chat_id(self) -> str | None:
        """The Bot Chat used most recently (what opening the bot shows)."""
        chats = self.bot_chats()
        return chats[0]["id"] if chats else None


class ProfileManager:
    def __init__(self, root: Path | None = None):
        self.root = root or pland_home()
        self.dir = self.root / "profiles"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.ensure_default()

    def ensure_default(self) -> Profile:
        if not (self.dir / "default" / "profile.yaml").exists():
            return self.create("default", title="PlanD", description="General-purpose assistant (single-agent mode).", bot=False)
        return self.get("default")

    def exists(self, name: str) -> bool:
        return (self.dir / name / "profile.yaml").is_file()

    def get(self, name: str) -> Profile:
        home = self.dir / name
        meta_path = home / "profile.yaml"
        if not meta_path.is_file():
            raise KeyError(f"no such profile: {name}")
        meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        return Profile(name=name, home=home, meta=meta)

    def list(self, *, bots_only: bool = False) -> list[Profile]:
        out = []
        for child in sorted(self.dir.iterdir()):
            if child.is_dir() and (child / "profile.yaml").is_file():
                p = self.get(child.name)
                if not bots_only or p.is_bot:
                    out.append(p)
        return out

    def create(
        self,
        name: str,
        *,
        title: str | None = None,
        description: str = "",
        soul: str | None = None,
        bot: bool = True,
        settings: dict[str, Any] | None = None,
        clone_from: str | None = None,
        avatar: str | None = None,
    ) -> Profile:
        if not NAME_RE.match(name):
            raise ValueError("profile name must match [a-z0-9][a-z0-9_-]{0,31}")
        with self._lock:
            home = self.dir / name
            if (home / "profile.yaml").exists():
                raise ValueError(f"profile '{name}' already exists")
            home.mkdir(parents=True, exist_ok=True)
            base_settings: dict[str, Any] = {}
            if clone_from:
                src = self.get(clone_from)
                base_settings = dict(src.meta.get("settings") or {})
                for sub in ("memories", "skills"):
                    if (src.home / sub).is_dir():
                        shutil.copytree(src.home / sub, home / sub, dirs_exist_ok=True)
                if soul is None:
                    soul = src.soul
            base_settings.update(settings or {})
            meta = {
                "title": title or name,
                "description": description,
                "bot": bot,
                "created": now(),
                "settings": base_settings,
            }
            if avatar:
                meta["avatar"] = avatar
            profile = Profile(name=name, home=home, meta=meta)
            profile.save_meta()
            (home / "SOUL.md").write_text((soul or DEFAULT_SOUL).strip() + "\n", encoding="utf-8")
            for fname in ("MEMORY.md", "USER.md"):
                path = profile.memories_dir / fname
                if not path.exists():
                    path.write_text("", encoding="utf-8")
            profile.workspace  # create
            profile.skills_dir
            profile.db  # initialise schema
            return profile

    def update(self, name: str, **changes: Any) -> Profile:
        with self._lock:
            profile = self.get(name)
            soul = changes.pop("soul", None)
            settings = changes.pop("settings", None)
            for key, val in changes.items():
                if val is not None and key in {"title", "description", "bot", "avatar", "hidden"}:
                    profile.meta[key] = val
            if settings:
                profile.meta["settings"] = merge_settings(profile.meta.get("settings"), settings)
            profile.save_meta()
            if soul is not None:
                (profile.home / "SOUL.md").write_text(soul.strip() + "\n", encoding="utf-8")
            return profile

    def delete(self, name: str) -> None:
        if name == "default":
            raise ValueError("the default profile cannot be deleted")
        with self._lock:
            home = self.dir / name
            if not home.exists():
                raise KeyError(name)
            db_path = (home / "state.db").resolve()
            with DB._registry_lock:
                db = DB._registry.pop(db_path, None)
            if db is not None:
                db._conn.close()
            shutil.rmtree(home)
