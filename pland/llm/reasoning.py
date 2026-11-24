"""Thinking intensity: one vocabulary for every surface, clamped onto what each provider accepts.

A single ladder of levels, an explicit "off", and "unset"
meaning the provider's own default. A level the provider does not offer is clamped to the nearest
*weaker* supported level, so a clamp never raises cost. Unknown words are rejected rather than
guessed (typo guard).

DeepSeek (probed 2026-10-21 on deepseek-flash): `reasoning_effort` accepts none/minimal/low/medium/high/
xhigh/ultra/max and 422s anything else; `none` does NOT switch thinking off (only `thinking: disabled`
does), and with thinking disabled the field is ignored. On a counting puzzle low/medium/high thought for
~1.5–1.75k tokens and max for ~3k; leaving the field out landed in between.

HKGAI (probed 2026-10-25 on t2_hkgai-v3_fp8_1m_e7): `reasoning_effort` is the only switch. It accepts
none/minimal/low/medium/high/xhigh/max (400 for anything else); `none` and leaving the field out both mean
no thinking, any level turns it on. There is no `thinking` field (sent, it is ignored). The reasoning text
comes back as `reasoning`, not `reasoning_content`.
"""
from __future__ import annotations

# Canonical ladder, weakest to strongest.
LADDER: tuple[str, ...] = ("minimal", "low", "medium", "high", "xhigh", "max", "ultra")
# Everything a user can pick on some provider: "off", "default" (= unset) or a level; choices() is per provider.
CHOICES: tuple[str, ...] = ("off", "default", "minimal", "low", "medium", "high", "xhigh", "max")

OFF_WORDS = {"off", "none", "disabled", "disable", "false", "no", "0"}
DEFAULT_WORDS = {"", "default", "auto", "reset", "unset"}

# Levels each provider's wire accepts as `reasoning_effort` (empty: no effort knob).
PROVIDER_LEVELS: dict[str, tuple[str, ...]] = {
    "deepseek": ("low", "medium", "high", "max"),
    "hkgai": ("minimal", "low", "medium", "high", "xhigh", "max"),
}
# Providers that think only when asked: "default" (thinking on, no level chosen) sends this level, and
# "off" sends the provider's own word for no thinking.
PROVIDER_DEFAULT_LEVEL: dict[str, str] = {"hkgai": "medium"}
PROVIDER_OFF_WORD: dict[str, str] = {"hkgai": "none"}
# Declared vendor mappings consulted before clamping.
PROVIDER_OVERRIDES: dict[str, dict[str, str]] = {
    "deepseek": {"xhigh": "max", "ultra": "max"},
}

DESCRIPTIONS = {
    "off": "no thinking: fastest, cheapest; fine for chat and simple edits",
    "default": "thinking on at the provider's default depth (what the evaluation used)",
    "minimal": "thinking on, the shortest reasoning",
    "low": "thinking on, short reasoning",
    "medium": "thinking on, moderate reasoning",
    "high": "thinking on, thorough reasoning",
    "xhigh": "thinking on, more thorough than high",
    "max": "thinking on, deepest reasoning: about twice the reasoning tokens of high on DeepSeek",
}
PROVIDER_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "hkgai": {
        "default": "thinking on at medium (HKGAI does not think unless a level is sent)",
        "max": "thinking on, deepest reasoning",
    },
}


def choices(provider: str) -> tuple[str, ...]:
    """What a provider offers: "off", "default" and the levels its wire accepts."""
    return ("off", "default") + PROVIDER_LEVELS.get(provider, ())


def description(choice: str, provider: str) -> str:
    return PROVIDER_DESCRIPTIONS.get(provider, {}).get(choice) or DESCRIPTIONS[choice]


def parse(value: object) -> str | None:
    """Normalise a user-supplied intensity. Returns "off", a ladder level, or None for the provider
    default. Raises ValueError for anything unrecognised."""
    if value is None or value is True:
        return None
    if value is False:
        return "off"
    word = str(value).strip().lower()
    if word in DEFAULT_WORDS:
        return None
    if word in OFF_WORDS:
        return "off"
    if word in LADDER:
        return word
    raise ValueError(f"unknown thinking intensity '{value}'; use one of: {', '.join(CHOICES)}")


def clamp(level: str | None, provider: str) -> str | None:
    """Map a ladder level onto the provider's supported set: verbatim if supported, else a declared
    override, else the nearest weaker supported level (or the weakest one if nothing is weaker).
    None stays None; providers without an effort knob get None."""
    if level is None or level == "off":
        return level
    supported = PROVIDER_LEVELS.get(provider, ())
    if not supported:
        return None
    if level in supported:
        return level
    mapped = PROVIDER_OVERRIDES.get(provider, {}).get(level)
    if mapped in supported:
        return mapped
    idx = LADDER.index(level)
    weaker = [lvl for lvl in supported if LADDER.index(lvl) < idx]
    return max(weaker, key=LADDER.index) if weaker else min(supported, key=LADDER.index)


def resolve(thinking: bool, effort: object, provider: str) -> tuple[bool, str | None]:
    """(thinking on?, wire effort) from a profile's `thinking` flag and `reasoning_effort` setting.
    An effort of "off" switches thinking off; any level switches it on."""
    level = parse(effort)
    if level == "off":
        return False, None
    if level is not None:
        thinking = True
    return thinking, wire_level(level, provider) if thinking else None


def wire_level(level: str | None, provider: str) -> str | None:
    """The `reasoning_effort` to send with thinking on: the clamped level, or for a provider that thinks only
    when asked, its declared default level when none was chosen."""
    return clamp(level, provider) or PROVIDER_DEFAULT_LEVEL.get(provider)


def to_settings(choice: object) -> dict[str, object]:
    """The profile.yaml `model` fields that store a user's choice (raises ValueError if unknown)."""
    level = parse(choice)
    if level == "off":
        return {"thinking": False, "reasoning_effort": None}
    return {"thinking": True, "reasoning_effort": level}


def current(thinking: bool, effort: object) -> str:
    """The choice a stored (thinking, reasoning_effort) pair stands for: off | default | <level>."""
    try:
        level = parse(effort)
    except ValueError:
        level = None
    if level is not None:
        return level
    return "default" if thinking else "off"


def label(thinking: bool, effort: str | None) -> str:
    """The single word surfaces show: off | default | <level>."""
    if not thinking:
        return "off"
    return effort or "default"


def describe(choice: str, provider: str = "deepseek") -> str:
    """Display text for a choice, noting a clamp (e.g. "xhigh (sends max)") or a provider's stand-in default."""
    level = parse(choice)
    shown = choice if level is None or level == "off" else level
    if level == "off":
        return shown
    sent = wire_level(level, provider)
    if sent != level and (level is not None or sent is not None):
        return f"{shown} (sends {sent or 'nothing'} on {provider})"
    return shown
