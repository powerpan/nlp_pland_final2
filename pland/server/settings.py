"""Global defaults behind the web UI's Settings page (PLAND_HOME/settings.yaml).

Every profile's settings are its own `profile.yaml` values on top of these (see `Profile.settings`), so a value set
here reaches the main chat and every bot that does not override it. The page works with flat field names; this module
maps them to the nested settings structure, validates them and reports which profiles override each one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .. import keys
from ..config import AgentSettings, ModelConfig, default_provider, global_settings, save_global_settings
from ..llm import reasoning

MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
MEMORY_RE = re.compile(r"^\d+(\.\d+)?[mMgG]$")


@dataclass(frozen=True)
class Field:
    path: tuple[str, ...]
    kind: str  # choice | int | float | bool | model | reasoning | memory | cpus
    choices: tuple[str, ...] = ()
    lo: float = 0
    hi: float = 0


FIELDS: dict[str, Field] = {
    # model
    "model": Field(("model", "model"), "model"),
    "reasoning": Field(("model", "reasoning_effort"), "reasoning"),
    "max_tokens": Field(("model", "max_tokens"), "int", lo=1024, hi=393_216),
    "stream": Field(("stream",), "bool"),
    # behaviour
    "approvals": Field(("approvals", "mode"), "choice", ("manual", "smart", "off")),
    "approval_timeout": Field(("approvals", "timeout"), "int", lo=30, hi=3600),
    "unattended": Field(("approvals", "unattended"), "choice", ("deny", "approve")),
    "reflection": Field(("reflection",), "bool"),
    "background_reflection": Field(("background_reflection",), "bool"),
    "experience_top_k": Field(("experience_top_k",), "int", lo=0, hi=10),
    # sandbox
    "backend": Field(("sandbox", "backend"), "choice", ("local", "docker")),
    "os_sandbox": Field(("sandbox", "os_sandbox"), "choice", ("auto", "off")),
    "command_timeout": Field(("sandbox", "command_timeout"), "int", lo=5, hi=1800),
    "docker_network": Field(("sandbox", "docker_network"), "choice", ("bridge", "none")),
    "docker_memory": Field(("sandbox", "docker_memory"), "memory"),
    "docker_cpus": Field(("sandbox", "docker_cpus"), "cpus", lo=0.25, hi=16),
    # limits
    "max_iterations": Field(("max_iterations",), "int", lo=1, hi=200),
    "max_run_calls": Field(("max_run_calls",), "int", lo=10, hi=2000),
    "max_run_tokens": Field(("max_run_tokens",), "int", lo=100_000, hi=50_000_000),
    "max_parallel_delegations": Field(("max_parallel_delegations",), "int", lo=1, hi=8),
    "max_delegation_depth": Field(("max_delegation_depth",), "int", lo=1, hi=4),
    "context_char_budget": Field(("context_char_budget",), "int", lo=50_000, hi=2_000_000),
}


def _get(obj: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        obj = getattr(obj, key)
    return obj


def flat_values(settings: AgentSettings) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, f in FIELDS.items():
        if f.kind == "reasoning":
            out[name] = reasoning.current(settings.model.thinking, settings.model.reasoning_effort)
        elif f.kind == "model":
            try:
                out[name] = settings.model.resolved().model
            except ValueError:
                out[name] = settings.model.model
        else:
            out[name] = _get(settings, f.path)
    return out


def _stored(data: dict[str, Any], name: str) -> bool:
    f = FIELDS[name]
    section = data
    for key in f.path[:-1]:
        section = section.get(key)
        if not isinstance(section, dict):
            return False
    if f.kind == "reasoning":
        return "reasoning_effort" in section or "thinking" in section
    return f.path[-1] in section


def view(rt) -> dict[str, Any]:
    """Current global values, built-in defaults, what the file stores and which profiles override each field."""
    stored = global_settings(rt.root)
    built_in = AgentSettings.from_dict(None)
    overrides: dict[str, list[str]] = {name: [] for name in FIELDS}
    for prof in rt.profiles.list():
        own = prof.meta.get("settings") or {}
        for name in FIELDS:
            if _stored(own, name):
                overrides[name].append(prof.name)
    provider = default_provider()
    try:
        cfg = ModelConfig(provider=provider).resolved()
        model, base_url, key_set = cfg.model, cfg.base_url, bool(cfg.api_key)
    except ValueError:
        model, base_url, key_set = None, None, False
    return {
        "values": flat_values(AgentSettings.from_dict(stored)),
        "defaults": flat_values(built_in),
        "stored": [name for name in FIELDS if _stored(stored, name)],
        "overrides": {k: v for k, v in overrides.items() if v},
        "provider": {"name": provider, "model": model, "base_url": base_url, "api_key_set": key_set},
        "keys": keys.status(rt.root),  # per provider: key set? from which file? (never the key)
        "file": str(rt.root / "settings.yaml"),
    }


def _check(name: str, f: Field, value: Any, provider: str) -> Any:
    if f.kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be true or false")
        return value
    if f.kind == "choice":
        if value not in f.choices:
            raise ValueError(f"{name} must be one of {', '.join(f.choices)}")
        return value
    if f.kind in ("int", "cpus"):
        try:
            num = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be a number") from None
        if not f.lo <= num <= f.hi:
            raise ValueError(f"{name} must be between {f.lo:g} and {f.hi:g}")
        return f"{num:g}" if f.kind == "cpus" else int(num)
    if f.kind == "memory":
        word = str(value).strip()
        if not MEMORY_RE.match(word):
            raise ValueError(f"{name} must look like 512m or 2g")
        return word.lower()
    if f.kind == "model":
        word = str(value).strip()
        if not MODEL_ID_RE.match(word):
            raise ValueError("invalid model id")
        if provider == "deepseek" and not word.startswith("deepseek-"):
            raise ValueError("the provider is DeepSeek; choose a deepseek-* model")
        return word
    raise ValueError(f"unsupported field {name}")


def patch(rt, changes: dict[str, Any]) -> dict[str, Any]:
    """Apply flat changes to settings.yaml. None, "" or "reset" removes a value (back to the built-in default)."""
    unknown = [k for k in changes if k not in FIELDS]
    if unknown:
        raise ValueError(f"unknown settings: {', '.join(unknown)}")
    data = global_settings(rt.root)
    provider = default_provider()
    for name, value in changes.items():
        f = FIELDS[name]
        *parents, leaf = f.path
        section = data
        for key in parents:
            section = section.setdefault(key, {})
            if not isinstance(section, dict):
                raise ValueError(f"settings.yaml has a malformed '{key}' section")
        reset = value is None or (isinstance(value, str) and value.strip().lower() in {"", "reset"})
        if f.kind == "reasoning":
            section.pop("thinking", None)
            section.pop("reasoning_effort", None)
            if not reset and str(value).strip().lower() != "default":
                section.update(reasoning.to_settings(value))
            continue
        if reset:
            section.pop(leaf, None)
        else:
            section[leaf] = _check(name, f, value, provider)
    for key in [k for k, v in data.items() if v == {}]:
        del data[key]
    save_global_settings(rt.root, data)
    return view(rt)
