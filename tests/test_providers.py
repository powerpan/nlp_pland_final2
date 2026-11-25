"""Model access rules: only DeepSeek or HKGAI, never OpenAI/Anthropic, no silent fallbacks."""

from __future__ import annotations

import pytest

from pland.config import ModelConfig
from pland.llm import ForbiddenProviderError, check_endpoint
from pland.llm.base import LLMError
from pland.llm.openai_compat import OpenAICompatClient


@pytest.mark.parametrize("provider,url", [
    ("openai", "https://api.openai.com/v1"),
    ("anthropic", "https://api.anthropic.com"),
    ("deepseek", "https://api.openai.com/v1"),          # right name, wrong host
    ("deepseek", "https://evil.example.com"),           # deepseek must stay on deepseek.com
    ("hkgai", "https://my-proxy.openai.azure.com/v1"),  # azure openai is still openai
    ("hkgai", "https://api.anthropic.com/v1"),
])
def test_forbidden_endpoints(provider, url):
    with pytest.raises(ForbiddenProviderError):
        check_endpoint(provider, url)


def test_allowed_endpoints():
    check_endpoint("deepseek", "https://api.deepseek.com")
    check_endpoint("hkgai", "https://api.hkgai.example.hk/v1")


def test_hkgai_configuration_from_env(monkeypatch):
    monkeypatch.setenv("HKGAI_API_KEY", "k")
    monkeypatch.setenv("HKGAI_BASE_URL", "https://api.hkgai.example.hk/v1")
    monkeypatch.setenv("HKGAI_MODEL", "hkgai-v1")
    cfg = ModelConfig(provider="hkgai", thinking=True).resolved()
    assert cfg.base_url.endswith("/v1") and cfg.model == "hkgai-v1" and cfg.thinking is True
    client = OpenAICompatClient(ModelConfig(provider="hkgai"))
    payload = client._payload([{"role": "user", "content": "hi"}], None, False, None)
    # no DeepSeek-only `thinking` switch: HKGAI thinks when reasoning_effort carries a level
    assert "thinking" not in payload and payload["model"] == "hkgai-v1" and payload["reasoning_effort"] == "medium"


def test_missing_configuration_fails_loudly(monkeypatch):
    for k in ("HKGAI_API_KEY", "HKGAI_BASE_URL", "HKGAI_MODEL"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ForbiddenProviderError):
        OpenAICompatClient(ModelConfig(provider="hkgai"))   # no base URL → refused, no fallback
    monkeypatch.setenv("HKGAI_BASE_URL", "https://api.hkgai.example.hk/v1")
    with pytest.raises(LLMError):
        OpenAICompatClient(ModelConfig(provider="hkgai"))   # no key → refused
    with pytest.raises(ValueError):
        ModelConfig(provider="openai").resolved()


def test_no_other_model_sdk_in_codebase():
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1] / "pland"
    offenders = [p for p in root.rglob("*.py")
                 if re.search(r"^\s*(import|from)\s+(openai|anthropic)\b", p.read_text(encoding="utf-8"), re.M)]
    assert not offenders, offenders


def test_pricing_per_model(tmp_path):
    from pland.budget import Ledger
    from pland.llm.base import Usage
    from pland.llm.pricing import cost
    from pland.store import SHARED_SCHEMA, DB

    assert round(cost(1_000_000, 0, 0, "deepseek-flash"), 4) == 0.30
    assert round(cost(1_000_000, 1_000_000, 1_000_000, "deepseek-v4-pro"), 4) == round(0.044 + 3.96, 4)
    led = Ledger(DB(tmp_path / "s.db", SHARED_SCHEMA))
    led.record(root_run="w", run_id="r", profile="p", session_id="s", purpose="turn", model="deepseek-flash",
               usage=Usage(1_000_000, 0, 0), duration=1, ok=True)
    led.record(root_run="w", run_id="r", profile="p", session_id="s", purpose="turn", model="deepseek-v4-pro",
               usage=Usage(1_000_000, 0, 0), duration=1, ok=True)
    t = led.totals()
    assert t["cost_usd"] == round(0.30 + 1.32, 5) and t["models"] == ["deepseek-flash", "deepseek-v4-pro"]


def test_web_tools_use_deepseek_while_hkgai_runs_the_model(monkeypatch):
    """HKGAI has no search/fetch API: with it as the provider, the DeepSeek key still serves the web tools — and only
    ever goes to a DeepSeek host."""
    import httpx

    from pland.tools import web

    monkeypatch.setenv("PLAND_PROVIDER", "hkgai")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-ds-key-0123456789")
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/v1/tools/search":
            return httpx.Response(200, json={"results": [{"title": "PlanD", "url": "https://example.com/p", "summary": "s"}]})
        if request.url.path == "/v1/tools/fetch":
            return httpx.Response(200, json={"title": "Example", "content": "Example Domain"})
        return httpx.Response(200, text="<html></html>")  # DuckDuckGo / Bing: no results

    monkeypatch.setattr(web, "_client", httpx.Client(transport=httpx.MockTransport(handler)))
    backend, results = web.search("pland", 3)
    assert backend == "deepseek" and results[0]["url"] == "https://example.com/p"
    assert seen[-1].url.host == "api.deepseek.com" and seen[-1].headers["authorization"] == "Bearer fake-ds-key-0123456789"
    assert web._fetch_deepseek("https://example.com/") == ("Example", "Example Domain")

    seen.clear()
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://search.example.org")  # not DeepSeek: refused before any request
    backend, results = web.search("pland", 3)
    assert backend != "deepseek" and all(r.url.host != "search.example.org" for r in seen)
    assert all("fake-ds-key" not in r.headers.get("authorization", "") for r in seen)

    monkeypatch.delenv("DEEPSEEK_BASE_URL")
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    seen.clear()
    web.search("pland", 3)
    assert seen and all(r.url.host != "api.deepseek.com" for r in seen)  # no DeepSeek key: scraping fallbacks only
