"""Global settings, paths and provider configuration.

Precedence (highest first): explicit overrides > profile config.yaml > environment / .env > defaults.
Secrets (API keys) only ever come from the environment or a .env file, never from config.yaml.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

_DOTENV_LOADED = False


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
    """Load .env files into os.environ without overriding variables that are already set."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED and not force:
        return
    candidates = [Path(__file__).resolve().parent.parent / ".env"]
    home = os.environ.get("PLAND_HOME")
    candidates.append(Path(home).expanduser() / ".env" if home else Path.home() / ".pland" / ".env")
    candidates.extend(extra or [])
    seen: set[Path] = set()
    for path in candidates:
        path = path.resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        for key, val in _parse_dotenv(path).items():
            os.environ.setdefault(key, val)
    _DOTENV_LOADED = True


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
        supports_thinking=False,
    ),
}


@dataclass
class ModelConfig:
    provider: str = "deepseek"
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    # DeepSeek thinking mode. Off by default: tool loops are faster and cheaper without it,
    # and a profile can turn it on (`model.thinking: true`) for planning-heavy bots.
    thinking: bool = False
    reasoning_effort: str | None = None
    temperature: float | None = 0.0  # used only with thinking disabled
    max_tokens: int | None = 8192
    timeout: float = 300.0
    max_retries: int = 3

    def resolved(self) -> "ModelConfig":
        load_dotenv()
        spec = PROVIDERS.get(self.provider)
        if spec is None:
            raise ValueError(f"Unknown provider '{self.provider}'. Allowed providers: {', '.join(PROVIDERS)}")
        return replace(
            self,
            base_url=self.base_url or os.environ.get(spec.base_url_env) or spec.default_base_url,
            api_key=self.api_key or os.environ.get(spec.key_env),
            model=self.model or os.environ.get(spec.model_env) or spec.default_model,
            thinking=self.thinking and spec.supports_thinking,
        )


def default_provider() -> str:
    load_dotenv()
    return os.environ.get("PLAND_PROVIDER", "deepseek").strip().lower() or "deepseek"


# --------------------------------------------------------------------------- agent settings

@dataclass
class ApprovalConfig:
    # manual: ask the human for every operation that needs permission
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
    docker_image: str = "python:3.11-slim"
    docker_network: str = "bridge"  # bridge | none
    docker_memory: str = "1g"
    docker_cpus: str = "1.0"


@dataclass
class AgentSettings:
    model: ModelConfig = field(default_factory=ModelConfig)
    approvals: ApprovalConfig = field(default_factory=ApprovalConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    max_iterations: int = 40
    toolsets: list[str] = field(default_factory=lambda: ["files", "code", "web", "git", "memory", "plan", "hitl"])
    reflection: bool = True
    background_reflection: bool = True
    experience_top_k: int = 3
    # Per run. Cache hits count 0.1 token.
    max_run_calls: int = 120
    max_run_tokens: int = 3_000_000

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


def _apply(target: Any, values: dict[str, Any] | None) -> None:
    for key, val in (values or {}).items():
        if key in {"api_key"}:
            continue  # secrets are env-only
        if hasattr(target, key) and not isinstance(getattr(target, key), (ModelConfig, ApprovalConfig, SandboxConfig)):
            setattr(target, key, val)
