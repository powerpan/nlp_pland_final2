"""Global settings, paths and provider configuration.

Precedence (highest first): explicit overrides > profile.yaml `settings` > PLAND_HOME/settings.yaml (the global
defaults edited on the web UI's Settings page) > environment / .env > built-in defaults.
Secrets (API keys) only ever come from the environment or a .env file, never from a YAML file.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

_DOTENV_LOADED = False
# Where each variable loaded by load_dotenv came from: a .env path, or "environment" when the shell already set it
# (the Settings page tells the user which file holds a key, never the key itself).
ENV_SOURCES: dict[str, str] = {}
GLOBAL_SETTINGS_FILE = "settings.yaml"
_global_lock = threading.Lock()
_global_cache: dict[Path, tuple[float, dict[str, Any]]] = {}


def _parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        elif " #" in val:
            val = val.split(" #", 1)[0].rstrip()
        if key:
            values[key] = val
    return values


def load_dotenv(extra: list[Path] | None = None, *, force: bool = False) -> None:
    """Load .env files into os.environ without overriding variables that are already set: the
    installation's own .env (repository root), then PLAND_HOME/.env (written by `pland setup`). The current
    folder's .env is deliberately not read: `pland` runs from any folder, and another project's .env must
    not change PlanD's key or home."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED and not force:
        return
    candidates = env_files() + list(extra or [])
    seen: set[Path] = set()
    for path in candidates:
        path = path.resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        for key, val in _parse_dotenv(path).items():
            if key in os.environ:
                ENV_SOURCES.setdefault(key, "environment")  # an earlier file, or the shell, already set it
            else:
                os.environ[key] = val
                ENV_SOURCES[key] = str(path)
    _DOTENV_LOADED = True


def env_files() -> list[Path]:
    """The .env files load_dotenv reads, in precedence order (the first one that sets a variable wins)."""
    home = os.environ.get("PLAND_HOME")
    return [Path(__file__).resolve().parent.parent / ".env",
            Path(home).expanduser() / ".env" if home else Path.home() / ".pland" / ".env"]


def pland_home() -> Path:
    load_dotenv()
    home = os.environ.get("PLAND_HOME")
    path = Path(home).expanduser() if home else Path.home() / ".pland"
    path.mkdir(parents=True, exist_ok=True)
    return path


# --------------------------------------------------------------------------- providers

@dataclass(frozen=True)
class ProviderSpec:
    name: str
    base_url_env: str
    key_env: str
    model_env: str
    default_base_url: str | None
    default_model: str | None
    supports_thinking: bool


PROVIDERS: dict[str, ProviderSpec] = {
    "deepseek": ProviderSpec(
        name="deepseek",
        base_url_env="DEEPSEEK_BASE_URL",
        key_env="DEEPSEEK_API_KEY",
        model_env="DEEPSEEK_MODEL",
        default_base_url="https://api.deepseek.com",
        default_model="deepseek-flash",
        supports_thinking=True,
    ),
    # HKGAI exposes an OpenAI-compatible chat-completions endpoint; its URL and model id come
    # from the user's HKGAI console, so there are deliberately no hard-coded defaults.
    "hkgai": ProviderSpec(
        name="hkgai",
        base_url_env="HKGAI_BASE_URL",
        key_env="HKGAI_API_KEY",
        model_env="HKGAI_MODEL",
        default_base_url=None,
        default_model=None,
        supports_thinking=True,
    ),
}


@dataclass
class ModelConfig:
    provider: str = "deepseek"
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    # Thinking mode (DeepSeek's switch; HKGAI thinks when a reasoning level is sent). On by default since the
    # official evaluation on DeepSeek: on the hard suite it lifted goal completion from ~66% to 87.5% on average at
    # similar cost (fewer degenerate loops), for ~1.3–2x latency on easy tasks. Short calls (discussion turns, approval
    # guard, compaction) switch it off per call.
    thinking: bool = True
    # Thinking intensity (see pland/llm/reasoning.py): None = provider default, "off", or a level (minimal…max).
    # A level implies thinking on; "off" switches it off. Clamped to what the provider accepts.
    reasoning_effort: str | None = None
    temperature: float | None = 0.0  # used only with thinking disabled
    # Output cap per reply (thinking tokens count toward it). DeepSeek accepts up to 393,216; 8,192 cut off a
    # reviewer's single large write_file. Billing is per token produced, so the cap only bounds runaway output.
    max_tokens: int | None = 32768
    timeout: float = 300.0
    max_retries: int = 3

    def resolved(self) -> "ModelConfig":
        load_dotenv()
        spec = PROVIDERS.get(self.provider)
        if spec is None:
            raise ValueError(f"Unknown provider '{self.provider}'. Allowed providers: {', '.join(PROVIDERS)}")
        from .llm.reasoning import resolve

        thinking, effort = resolve(self.thinking, self.reasoning_effort, self.provider)
        thinking = thinking and spec.supports_thinking
        return replace(
            self,
            base_url=self.base_url or os.environ.get(spec.base_url_env) or spec.default_base_url,
            api_key=self.api_key or os.environ.get(spec.key_env),
            model=self.model or os.environ.get(spec.model_env) or spec.default_model,
            thinking=thinking,
            reasoning_effort=effort if thinking else None,
        )


def default_provider() -> str:
    load_dotenv()
    return os.environ.get("PLAND_PROVIDER", "deepseek").strip().lower() or "deepseek"


# --------------------------------------------------------------------------- agent settings

@dataclass
class ApprovalConfig:
    # manual: ask the human for every operation that needs permission
    # smart:  a guard model call triages flagged shell/python commands and workspace file cleanup
    #         (approve / deny / escalate); git push, credentials and publishing go to the human
    # off:    never ask (still subject to the hardline blocklist)
    mode: str = "manual"
    timeout: float = 600.0
    # what to do when no human channel is attached (background/unattended runs)
    unattended: str = "deny"


@dataclass
class SandboxConfig:
    backend: str = "local"  # local | docker
    # OS-level confinement of the local backend: "auto" uses macOS Seatbelt (sandbox-exec) when
    # available — file reads/writes limited to the workspace (+ room shared folder) and the
    # toolchain; "off" runs commands with the full rights of the OS user.
    os_sandbox: str = "auto"
    command_timeout: float = 120.0
    max_output_chars: int = 20000
    docker_image: str = "pland-sandbox:py3.11"  # built from docker/sandbox.Dockerfile on first use
    docker_network: str = "bridge"  # bridge | none
    docker_memory: str = "1g"
    docker_cpus: str = "1.0"


@dataclass
class AgentSettings:
    model: ModelConfig = field(default_factory=ModelConfig)
    approvals: ApprovalConfig = field(default_factory=ApprovalConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    # Steps (model calls) per run. Evaluation sessions needed p50 6 / p99 44 / max 61 steps, but a real repository
    # review hit 40 on every delegated worker; the step-budget checkpoint fires at 80%.
    max_iterations: int = 80
    toolsets: list[str] = field(default_factory=lambda: ["files", "code", "web", "git", "memory", "plan", "hitl", "delegation", "team"])
    reflection: bool = True
    background_reflection: bool = True  # return the answer first, reflect afterwards
    stream: bool = True  # stream turn responses and publish assistant.delta events (UI/CLI live text)
    # Compaction threshold for the model's view of a session (~100k tokens). DeepSeek's window is 1M,
    # but every call re-sends the whole conversation, so long Bot Chats are compacted well before it.
    context_char_budget: int = 400_000
    experience_top_k: int = 3
    max_delegation_depth: int = 2
    max_parallel_delegations: int = 4
    # Operator-owned ceilings for structured reviews. The delegator can request smaller limits.
    review_max_steps: int = 30
    review_timeout_seconds: int = 240
    fast_review_steps: int = 16
    fast_review_seconds: int = 210
    fast_followup_seconds: int = 120
    # Per top-level run (shared by every delegate/subagent it spawns; a group drive gets twice this). Cache hits
    # count 0.1 token. Raised from 120 / 3M after a 5-bot review used 216 of its 240 drive calls. At ~95% cache
    # hits this bounds a single run at roughly $1 of DeepSeek peak pricing (a group drive at roughly $2).
    max_run_calls: int = 300
    max_run_tokens: int = 8_000_000

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AgentSettings":
        data = dict(data or {})
        settings = cls()
        settings.model = ModelConfig(provider=default_provider())
        _apply(settings.model, data.pop("model", None))
        _apply(settings.approvals, data.pop("approvals", None))
        _apply(settings.sandbox, data.pop("sandbox", None))
        _apply(settings, data)
        return settings


def merge_settings(base: dict[str, Any] | None, over: dict[str, Any] | None) -> dict[str, Any]:
    """`over` on top of `base`; the nested sections (model, approvals, sandbox) merge key by key."""
    merged = dict(base or {})
    for key, val in (over or {}).items():
        if isinstance(val, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **val}
        else:
            merged[key] = val
    return merged


def global_settings(root: Path | None = None) -> dict[str, Any]:
    """The global defaults in PLAND_HOME/settings.yaml (empty when there is none). Re-read when the file changes,
    so every run picks up a change made on the Settings page without a restart."""
    path = (root or pland_home()) / GLOBAL_SETTINGS_FILE
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    with _global_lock:
        hit = _global_cache.get(path)
        if hit and hit[0] == mtime:
            return dict(hit[1])
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    data = {k: v for k, v in data.items() if isinstance(k, str)} if isinstance(data, dict) else {}
    with _global_lock:
        _global_cache[path] = (mtime, data)
    return dict(data)


def save_global_settings(root: Path, data: dict[str, Any]) -> None:
    """Write PLAND_HOME/settings.yaml atomically (empty sections are dropped)."""
    clean = {k: v for k, v in data.items() if v not in ({}, None)}
    path = root / GLOBAL_SETTINGS_FILE
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(clean, allow_unicode=True, sort_keys=False), encoding="utf-8")
    tmp.replace(path)
    with _global_lock:
        _global_cache.pop(path, None)


def _apply(target: Any, values: dict[str, Any] | None) -> None:
    for key, val in (values or {}).items():
        if key in {"api_key"}:
            continue  # secrets are env-only
        if hasattr(target, key) and not isinstance(getattr(target, key), (ModelConfig, ApprovalConfig, SandboxConfig)):
            setattr(target, key, val)
