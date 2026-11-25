"""Global defaults (PLAND_HOME/settings.yaml) behind the Settings page, and the usage breakdowns — no network."""

from __future__ import annotations

import os
import time
import warnings

import pytest

from pland.config import global_settings
from pland.llm.base import Usage
from pland.server.app import create_app

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient


@pytest.fixture()
def client(rt):
    with TestClient(create_app(rt)) as c:
        yield c


def test_global_defaults_reach_profiles_without_their_own_value(rt, client):
    rt.profiles.create("coder", bot=True, settings={"max_iterations": 30})
    r = client.patch("/api/settings", json={"max_iterations": 120, "approvals": "smart", "reasoning": "high"})
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["values"]["max_iterations"] == 120 and view["values"]["reasoning"] == "high"
    assert set(view["stored"]) == {"max_iterations", "approvals", "reasoning"}
    assert view["overrides"] == {"max_iterations": ["coder"]}

    default = rt.profiles.get("default").settings()
    assert default.max_iterations == 120 and default.approvals.mode == "smart"
    assert default.model.thinking and default.model.reasoning_effort == "high"
    assert rt.profiles.get("coder").settings().max_iterations == 30  # the bot's own value wins
    assert rt.profiles.get("coder").settings().approvals.mode == "smart"  # ...and it inherits the rest


def test_reset_and_reasoning_choices(rt, client):
    client.patch("/api/settings", json={"reasoning": "off", "docker_memory": "2G", "docker_cpus": 2})
    s = rt.profiles.get("default").settings()
    assert s.model.thinking is False and s.sandbox.docker_memory == "2g" and s.sandbox.docker_cpus == "2"
    view = client.patch("/api/settings", json={"reasoning": "default", "docker_memory": None, "docker_cpus": ""}).json()
    assert view["stored"] == [] and global_settings(rt.root) == {}
    assert view["values"]["reasoning"] == "default" and view["values"]["docker_memory"] == view["defaults"]["docker_memory"]
    assert rt.profiles.get("default").settings().model.thinking is True


@pytest.mark.parametrize("body", [
    {"max_iterations": 0}, {"max_iterations": 999}, {"approvals": "sometimes"}, {"stream": "yes"},
    {"model": "gpt-4o"}, {"reasoning": "turbo"}, {"docker_memory": "lots"}, {"api_key": "x"}, {"nope": 1},
])
def test_invalid_values_are_refused_and_nothing_is_written(rt, client, body):
    r = client.patch("/api/settings", json=body)
    assert r.status_code == 400, r.text
    assert global_settings(rt.root) == {}


def test_settings_file_edits_are_picked_up_without_restart(rt):
    path = rt.root / "settings.yaml"
    path.write_text("max_run_calls: 77\nmodel: {max_tokens: 4096}\n", encoding="utf-8")
    s = rt.profiles.get("default").settings()
    assert s.max_run_calls == 77 and s.model.max_tokens == 4096
    time.sleep(0.01)
    path.write_text("max_run_calls: 88\n", encoding="utf-8")
    os.utime(path, (time.time() + 5, time.time() + 5))  # make sure the mtime differs on coarse filesystems
    assert rt.profiles.get("default").settings().max_run_calls == 88


def test_usage_reports_cost_per_bot_and_per_day(rt, client):
    for profile, model in (("default", "deepseek-flash"), ("coder", "deepseek-v4-pro"), ("coder", "deepseek-flash")):
        rt.ledger.record(root_run="w_1", run_id="r_1", profile=profile, session_id="s_1", purpose="turn", model=model,
                         usage=Usage(1000, 100, 800), duration=0.5, ok=True)
    u = client.get("/api/usage").json()
    assert u["calls"] == 3
    by = {r["profile"]: r for r in u["by_profile"]}
    assert by["coder"]["calls"] == 2 and by["default"]["calls"] == 1
    assert by["coder"]["cost_usd"] > by["default"]["cost_usd"] > 0
    assert len(u["by_day"]) == 1 and u["by_day"][0]["calls"] == 3
    assert abs(sum(r["cost_usd"] for r in u["by_profile"]) - u["cost_usd"]) < 1e-4
