"""API keys and provider choice from the Settings page (pland/keys.py) — no network; the real .env is never touched."""

from __future__ import annotations

import json
import stat
import warnings

import httpx
import pytest

from pland import keys
from pland.server.app import create_app

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

KEY = "fake-test-key-0123456789abcdef01234"
NEW = "fake-new-key-0123456789abcdef012345"
VARS = ("DEEPSEEK_API_KEY", "HKGAI_API_KEY", "HKGAI_BASE_URL", "HKGAI_MODEL", "PLAND_PROVIDER", "DEEPSEEK_BASE_URL")


@pytest.fixture()
def env(rt, tmp_path, monkeypatch):
    """Stand-in .env files: the installation's and PLAND_HOME's (the developer's real .env is never read or written)."""
    from pland.config import load_dotenv

    load_dotenv()  # load the real files first (once per process), so nothing is loaded behind the test's back later
    install = tmp_path / "install.env"
    files = [install, rt.root / ".env"]
    monkeypatch.setattr(keys, "env_files", lambda: files)
    monkeypatch.setattr(keys, "ENV_SOURCES", {})
    for var in VARS:  # set-then-delete makes monkeypatch restore the original state, even "absent", afterwards
        monkeypatch.setenv(var, "placeholder")
        monkeypatch.delenv(var)
    return {"install": install, "home": rt.root / ".env"}


@pytest.fixture()
def client(rt):
    with TestClient(create_app(rt)) as c:
        yield c


def test_a_new_key_goes_to_the_data_folder_and_is_never_returned(rt, env, client):
    r = client.put("/api/settings/keys/deepseek", json={"key": KEY, "test": False})
    assert r.status_code == 200, r.text
    assert KEY not in r.text
    ds = next(p for p in r.json()["keys"]["providers"] if p["name"] == "deepseek")
    assert ds["key_set"] and ds["key_source"] == "PlanD data folder (.env)"
    assert f"DEEPSEEK_API_KEY={KEY}" in env["home"].read_text()
    assert stat.S_IMODE(env["home"].stat().st_mode) == 0o600
    assert client.get("/api/status").json()["api_key_set"] is True
    assert KEY not in client.get("/api/settings").text


def test_a_key_is_replaced_where_it_already_lives(rt, env, client, monkeypatch):
    env["install"].write_text(f"# mine\nOTHER=1\nexport DEEPSEEK_API_KEY={KEY}\n")
    monkeypatch.setenv("DEEPSEEK_API_KEY", KEY)
    keys.ENV_SOURCES["DEEPSEEK_API_KEY"] = str(env["install"])
    client.put("/api/settings/keys/deepseek", json={"key": NEW, "test": False})
    text = env["install"].read_text()
    assert f"DEEPSEEK_API_KEY={NEW}" in text and KEY not in text and "OTHER=1" in text and "# mine" in text
    assert not env["home"].exists()  # writing there would be shadowed by the installation's .env after a restart
    import os
    assert os.environ["DEEPSEEK_API_KEY"] == NEW  # the running server uses it at once


def test_remove_clears_every_file_and_the_process(rt, env, client, monkeypatch):
    env["install"].write_text(f"DEEPSEEK_API_KEY={KEY}\n")
    env["home"].write_text(f"DEEPSEEK_API_KEY={NEW}\nKEEP=1\n")
    monkeypatch.setenv("DEEPSEEK_API_KEY", KEY)
    keys.ENV_SOURCES["DEEPSEEK_API_KEY"] = str(env["install"])
    r = client.delete("/api/settings/keys/deepseek")
    assert r.status_code == 200
    assert "DEEPSEEK" not in env["install"].read_text() and env["home"].read_text() == "KEEP=1\n"
    assert client.get("/api/status").json()["api_key_set"] is False


def test_shell_exported_key_is_reported_and_warned_about(rt, env, client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", KEY)  # not from any file: the shell
    ds = next(p for p in client.get("/api/settings").json()["keys"]["providers"] if p["name"] == "deepseek")
    assert ds["key_source"] == "shell environment"
    r = client.put("/api/settings/keys/deepseek", json={"key": NEW, "test": False})
    assert "takes precedence after a restart" in r.json()["notice"]


@pytest.mark.parametrize("headers,code", [
    ({"Origin": "https://evil.example"}, 403),          # another web page posting to the local server
    ({"Host": "attacker.example:8765"}, 403),           # DNS rebinding
    ({"Content-Type": "text/plain"}, 422),              # a "simple" cross-site form post: not parsed as JSON
])
def test_key_changes_refuse_requests_from_elsewhere(rt, env, client, headers, code):
    body = json.dumps({"key": KEY, "test": False})
    h = {"Content-Type": "application/json", **headers}
    r = client.put("/api/settings/keys/deepseek", content=body, headers=h)
    assert r.status_code == code, r.text
    assert not env["home"].exists()


def test_bad_keys_and_providers_are_refused(rt, env, client):
    assert client.put("/api/settings/keys/deepseek", json={"key": "short", "test": False}).status_code == 400
    assert client.put("/api/settings/keys/deepseek", json={"key": "fake has space 0123456789abc", "test": False}).status_code == 400
    assert client.put("/api/settings/keys/openai", json={"key": KEY, "test": False}).status_code == 400
    assert not env["home"].exists()


def _transport(status_code, body):
    return httpx.MockTransport(lambda req: httpx.Response(status_code, json=body))


def test_key_test_maps_provider_answers(env):
    ok = keys.test_key("deepseek", KEY, transport=_transport(200, {
        "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}], "usage": {}, "model": "deepseek-flash"}))
    assert ok["ok"] and ok["model"] == "deepseek-flash"
    with pytest.raises(keys.KeySetupError, match="rejected this key"):
        keys.test_key("deepseek", KEY, transport=_transport(401, {"error": {"message": f"bad key {KEY}"}}))
    low = keys.test_key("deepseek", KEY, transport=_transport(402, {"error": {"message": "Insufficient Balance"}}))
    assert low["ok"] and "insufficient balance" in low["warning"]
    with pytest.raises(keys.KeySetupError) as exc:
        keys.test_key("deepseek", KEY, transport=_transport(400, {"error": {"message": f"echo {KEY}"}}))
    assert KEY not in str(exc.value)  # never echoed back, even if the provider repeats it


def test_hkgai_needs_key_endpoint_and_model_before_switching(rt, env, client):
    r = client.patch("/api/settings/provider", json={"provider": "hkgai"})
    assert r.status_code == 400 and "needs an API key and an endpoint and a model" in r.json()["detail"]
    for bad in ("http://hkgai.example/v1", "https://api.openai.com./v1"):
        r = client.patch("/api/settings/provider", json={"endpoint": {"provider": "hkgai", "base_url": bad}})
        assert r.status_code == 400, bad
    assert client.patch("/api/settings/provider", json={"endpoint": {"provider": "deepseek", "base_url": "https://x.deepseek.com"}}).status_code == 400
    client.patch("/api/settings/provider", json={"endpoint": {"provider": "hkgai", "base_url": "https://llm.hkgai.example/v1/", "model": "hkgai-chat"}})
    client.put("/api/settings/keys/hkgai", json={"key": NEW, "test": False})
    r = client.patch("/api/settings/provider", json={"provider": "hkgai"})
    assert r.status_code == 200, r.text
    assert client.get("/api/status").json()["provider"] == "hkgai"
    text = env["home"].read_text()
    assert "HKGAI_BASE_URL=https://llm.hkgai.example/v1\n" in text and "PLAND_PROVIDER=hkgai" in text


def test_endpoint_guard_ignores_a_trailing_dot():
    from pland.llm.guard import ForbiddenProviderError, check_endpoint

    with pytest.raises(ForbiddenProviderError):
        check_endpoint("hkgai", "https://api.openai.com./v1")
    with pytest.raises(ForbiddenProviderError):
        check_endpoint("deepseek", "https://api.deepseek.com.evil.example./")
    check_endpoint("deepseek", "https://api.deepseek.com.")


def test_switching_to_hkgai_says_where_web_search_goes(rt, env, client, monkeypatch):
    client.patch("/api/settings/provider", json={"endpoint": {"provider": "hkgai", "base_url": "https://llm.hkgai.example/v1", "model": "hk"}})
    client.put("/api/settings/keys/hkgai", json={"key": NEW, "test": False})
    r = client.patch("/api/settings/provider", json={"provider": "hkgai"}).json()
    assert r["keys"]["web"] == "fallback" and "add a DeepSeek key" in r["notice"]
    client.put("/api/settings/keys/deepseek", json={"key": KEY, "test": False})
    assert client.get("/api/settings").json()["keys"]["web"] == "deepseek"
    monkeypatch.setattr(keys, "default_provider", lambda: "deepseek")
    assert keys.configure("hkgai", root=rt.root)[-1].endswith("keep using DeepSeek's.")
    monkeypatch.setattr(keys, "default_provider", lambda: "hkgai")
    r = client.delete("/api/settings/keys/deepseek").json()
    assert "Web search and fetch no longer use DeepSeek" in r["notice"] and r["keys"]["web"] == "fallback"
