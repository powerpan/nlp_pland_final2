"""API keys and the provider choice, as the web Settings page manages them.

Keys live only in .env files (never in YAML or a database), as `pland setup` keeps them. The page can set, test or
remove a key but never read one back: every response says whether a key is set and which file it comes from, nothing
more. A key is written to the file that already provides it (the installation's .env wins over PLAND_HOME/.env when
both exist, so writing to the other one would be silently ignored after a restart); a new key goes to PLAND_HOME/.env.
Files are written atomically with permissions 600. The running process picks the change up at once (os.environ), so
the next run uses it without a restart.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import ENV_SOURCES, PROVIDERS, ModelConfig, default_provider, env_files, pland_home
from .llm.guard import ForbiddenProviderError, check_endpoint

KEY_RE = re.compile(r"^[A-Za-z0-9._~+/=\-]{16,256}$")  # no whitespace, quotes or "#": safe as a bare .env value
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,95}$")
LABELS = {"deepseek": "DeepSeek", "hkgai": "HKGAI"}


class KeySetupError(ValueError):
    """A request the page should show as a plain message (bad input, key rejected, provider not ready)."""


# --------------------------------------------------------------------------- .env files

def _line_key(line: str) -> str | None:
    text = line.strip()
    if not text or text.startswith("#") or "=" not in text:
        return None
    return text.partition("=")[0].strip().removeprefix("export ").strip()


def write_env(path: Path, updates: dict[str, str | None]) -> None:
    """Set (or, with None, remove) variables in one .env file, keeping every other line as it was."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    kept = [ln for ln in lines if _line_key(ln) not in updates]
    kept += [f"{k}={v}" for k, v in updates.items() if v is not None]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(kept) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def _file_has(path: Path, key: str) -> bool:
    try:
        return any(_line_key(ln) == key for ln in path.read_text(encoding="utf-8").splitlines())
    except OSError:
        return False


def source(var: str) -> str | None:
    """Where a variable's current value comes from: a .env path, "environment" (the shell), or None (unset)."""
    if not os.environ.get(var):
        return None
    return ENV_SOURCES.get(var, "environment")


def _describe(src: str | None, root: Path) -> str | None:
    if src is None:
        return None
    if src == "environment":
        return "shell environment"
    path = Path(src)
    if path == root / ".env":
        return "PlanD data folder (.env)"
    if path == env_files()[0]:
        return "installation folder (.env)"
    return path.name


def _target(var: str, root: Path) -> Path:
    src = source(var)
    if src and src != "environment":
        return Path(src)
    return root / ".env"


def _set(var: str, value: str | None, root: Path) -> str | None:
    """Write or remove one variable and update the running process. Returns a warning when the shell overrides it."""
    warning = None
    if value is None:
        for path in env_files():
            if _file_has(path, var):
                write_env(path, {var: None})
        if source(var) == "environment":
            warning = (f"{var} is also set in the shell environment PlanD was started from; it is cleared for this "
                       "server now but comes back after a restart unless you remove it there.")
        os.environ.pop(var, None)
        ENV_SOURCES.pop(var, None)
        return warning
    path = _target(var, root)
    shell = source(var) == "environment"
    if shell:
        warning = (f"{var} is also exported by the shell PlanD was started from; the shell value takes precedence after a "
                   "restart.")
    write_env(path, {var: value})
    os.environ[var] = value
    if not shell:
        ENV_SOURCES[var] = str(path)
    return warning


# --------------------------------------------------------------------------- status

def status(root: Path | None = None) -> dict[str, Any]:
    root = root or pland_home()
    current = default_provider()
    providers = []
    for name, spec in PROVIDERS.items():
        base_url = os.environ.get(spec.base_url_env) or spec.default_base_url
        model = os.environ.get(spec.model_env) or spec.default_model
        key_src = source(spec.key_env)
        providers.append({
            "name": name, "label": LABELS.get(name, name), "key_env": spec.key_env,
            "key_set": key_src is not None, "key_source": _describe(key_src, root),
            "base_url": base_url, "base_url_custom": bool(os.environ.get(spec.base_url_env)),
            "model": model, "editable_endpoint": spec.default_base_url is None,
            "ready": key_src is not None and bool(base_url) and bool(model),
        })
    env_file = str(root / ".env")
    home = str(Path.home())
    # the web tools use DeepSeek's Search/Fetch APIs whenever its key is set, also with HKGAI as the provider
    web = "deepseek" if source(PROVIDERS["deepseek"].key_env) else "fallback"
    return {"current": current, "providers": providers, "web": web,
            "env_file": "~" + env_file[len(home):] if env_file.startswith(home + os.sep) else env_file}


# --------------------------------------------------------------------------- changes

def _spec(provider: str):
    spec = PROVIDERS.get(provider)
    if spec is None:
        raise KeySetupError(f"unknown provider '{provider}'; allowed: {', '.join(PROVIDERS)}")
    return spec


def check_key(key: str) -> str:
    key = (key or "").strip()
    if not KEY_RE.match(key):
        raise KeySetupError("that does not look like an API key (16–256 characters, no spaces or quotes)")
    return key


def test_key(provider: str, key: str, *, transport=None, ledger=None) -> dict[str, Any]:
    """One tiny real call with the candidate key (thinking off, a few output tokens). Raises KeySetupError when the
    provider rejects the key or cannot be reached; returns {"ok", "model", "seconds", "warning"?}."""
    from .llm.base import LLMError, Usage
    from .llm.openai_compat import OpenAICompatClient

    cfg = ModelConfig(provider=provider, api_key=key, thinking=False, max_tokens=8, max_retries=0, timeout=30.0)
    started = time.time()
    try:
        client = OpenAICompatClient(cfg, transport=transport)
        resp = client.chat([{"role": "user", "content": "Reply with OK."}], max_tokens=8)
    except ForbiddenProviderError as exc:
        raise KeySetupError(str(exc)) from None
    except LLMError as exc:
        status_code = getattr(exc, "status", None)
        message = str(exc).replace(key, "***")[:300]
        if ledger is not None:
            ledger(provider, cfg, Usage(), time.time() - started, False, message)
        if status_code == 402:  # the key is valid; the account has no balance
            return {"ok": True, "model": cfg.resolved().model, "seconds": round(time.time() - started, 2),
                    "warning": f"{LABELS.get(provider, provider)} accepted the key but reports insufficient balance (HTTP 402)."}
        if status_code in (401, 403):
            raise KeySetupError(f"{LABELS.get(provider, provider)} rejected this key (HTTP {status_code}); nothing was saved.") from None
        raise KeySetupError(f"could not verify the key ({message}); nothing was saved. Check the network or save without "
                        "testing.") from None
    if ledger is not None:
        ledger(provider, cfg, resp.usage, time.time() - started, True, None)
    return {"ok": True, "model": resp.model or cfg.resolved().model, "seconds": round(time.time() - started, 2)}


def set_key(provider: str, key: str, root: Path | None = None) -> str | None:
    spec = _spec(provider)
    return _set(spec.key_env, check_key(key), root or pland_home())


def remove_key(provider: str, root: Path | None = None) -> str | None:
    spec = _spec(provider)
    warning = _set(spec.key_env, None, root or pland_home())
    if spec.name == "deepseek" and default_provider() != "deepseek":
        web = ("Web search and fetch no longer use DeepSeek: search falls back to DuckDuckGo and Bing, fetch to a "
               "direct download.")
        warning = f"{warning} {web}" if warning else web
    return warning


def check_base_url(provider: str, url: str) -> str:
    url = (url or "").strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise KeySetupError("the endpoint must be an https:// URL")
    try:
        check_endpoint(provider, url)
    except ForbiddenProviderError as exc:
        raise KeySetupError(str(exc)) from None
    return url


def configure(provider: str | None = None, *, endpoint: dict[str, Any] | None = None, root: Path | None = None) -> list[str]:
    """Change the provider in use (PLAND_PROVIDER) and/or a provider's endpoint and model (HKGAI has no defaults).
    `endpoint` = {"provider": name, "base_url": str|None, "model": str|None}; "" clears a value."""
    root = root or pland_home()
    warnings: list[str] = []
    if endpoint:
        spec = _spec(endpoint.get("provider") or "")
        if spec.default_base_url is not None and endpoint.get("base_url"):
            raise KeySetupError(f"{LABELS[spec.name]} uses its official endpoint; it cannot be changed here")
        if "base_url" in endpoint and endpoint["base_url"] is not None:
            value = endpoint["base_url"].strip()
            w = _set(spec.base_url_env, check_base_url(spec.name, value) if value else None, root)
            warnings += [w] if w else []
        if "model" in endpoint and endpoint["model"] is not None:
            value = endpoint["model"].strip()
            if value and not MODEL_ID_RE.match(value):
                raise KeySetupError("invalid model id")
            w = _set(spec.model_env, value or None, root)
            warnings += [w] if w else []
    if provider is not None:
        spec = _spec(provider)
        info = next(p for p in status(root)["providers"] if p["name"] == spec.name)
        if not info["ready"]:
            missing = [what for what, ok in (("an API key", info["key_set"]), ("an endpoint", bool(info["base_url"])),
                                             ("a model", bool(info["model"]))) if not ok]
            raise KeySetupError(f"{LABELS[spec.name]} needs {' and '.join(missing)} before it can be used")
        w = _set("PLAND_PROVIDER", spec.name, root)
        warnings += [w] if w else []
        if spec.name != "deepseek":
            warnings.append(f"{LABELS[spec.name]} has no web search or fetch API, so web search and fetch keep using "
                            "DeepSeek's." if source(PROVIDERS["deepseek"].key_env) else
                            f"{LABELS[spec.name]} has no web search or fetch API: add a DeepSeek key for them, or search "
                            "falls back to DuckDuckGo and Bing and fetch to a direct download.")
    return warnings
