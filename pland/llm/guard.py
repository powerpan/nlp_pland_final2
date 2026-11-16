"""Hard guard: the runtime may only talk to DeepSeek or HKGAI.

Every model call in the system (main turns, reflection, planning, routing, memory curation) goes
through `make_client`, which calls `check_endpoint` before any network I/O. There is no fallback
provider, so a misconfiguration fails loudly instead of silently routing elsewhere.
"""

from __future__ import annotations

from urllib.parse import urlparse

ALLOWED_PROVIDERS = {"deepseek", "hkgai"}

_FORBIDDEN_HOST_SUFFIXES = (
    "openai.com",
    "openai.azure.com",
    "anthropic.com",
    "claude.ai",
)


class ForbiddenProviderError(RuntimeError):
    pass


def check_endpoint(provider: str, base_url: str | None) -> None:
    if provider not in ALLOWED_PROVIDERS:
        raise ForbiddenProviderError(
            f"Provider '{provider}' is not allowed. Only {sorted(ALLOWED_PROVIDERS)} may be used."
        )
    if not base_url:
        raise ForbiddenProviderError(f"No base URL configured for provider '{provider}'.")
    host = (urlparse(base_url).hostname or "").lower()
    if not host:
        raise ForbiddenProviderError(f"Invalid base URL: {base_url!r}")
    for suffix in _FORBIDDEN_HOST_SUFFIXES:
        if host == suffix or host.endswith("." + suffix):
            raise ForbiddenProviderError(f"Endpoint host '{host}' belongs to a forbidden provider.")
    if provider == "deepseek" and not (host == "deepseek.com" or host.endswith(".deepseek.com")):
        # A custom DeepSeek base URL is allowed only if it is still a DeepSeek host.
        raise ForbiddenProviderError(f"DeepSeek base URL must be a deepseek.com host, got '{host}'.")
