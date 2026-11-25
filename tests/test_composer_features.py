"""Thinking intensity, per-chat model, file uploads, team templates and launch helpers — no network."""

from __future__ import annotations

import json
import time
import warnings

import httpx
import pytest

from pland import cli
from pland.config import ModelConfig, load_dotenv
from pland.llm import reasoning
from pland.llm.openai_compat import OpenAICompatClient
from pland.server.app import create_app
from pland.sessions import SessionStore
from pland.team.templates import apply_template, list_templates

with warnings.catch_warnings():  # starlette's TestClient warns about its httpx backend at import time
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient


@pytest.fixture()
def client(rt):
    with TestClient(create_app(rt)) as c:
        yield c


def wait_idle(client, profile, sid, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/profiles/{profile}/sessions/{sid}/messages").json()
        if not data["busy"]:
            return data
        time.sleep(0.02)
    raise AssertionError("run did not finish")


# --------------------------------------------------------------------------- intensity vocabulary

def test_parse_and_clamp_follow_the_ladder():
    assert reasoning.parse(None) is None and reasoning.parse("default") is None and reasoning.parse("") is None
    assert reasoning.parse("OFF") == "off" and reasoning.parse("none") == "off" and reasoning.parse(False) == "off"
    assert reasoning.parse(" High ") == "high"
    with pytest.raises(ValueError):
        reasoning.parse("turbo")
    # DeepSeek: verbatim if offered, declared overrides, else nearest weaker (never escalates cost)
    assert reasoning.clamp("medium", "deepseek") == "medium"
    assert reasoning.clamp("xhigh", "deepseek") == "max" and reasoning.clamp("ultra", "deepseek") == "max"
    assert reasoning.clamp("minimal", "deepseek") == "low"
    assert reasoning.clamp("high", "hkgai") == "high" and reasoning.clamp("ultra", "hkgai") == "max"
    assert reasoning.resolve(False, "high", "deepseek") == (True, "high")  # a level switches thinking on
    assert reasoning.resolve(True, "off", "deepseek") == (False, None)
    assert reasoning.resolve(True, None, "deepseek") == (True, None)
    assert reasoning.to_settings("off") == {"thinking": False, "reasoning_effort": None}
    assert reasoning.to_settings("max") == {"thinking": True, "reasoning_effort": "max"}
    assert reasoning.current(True, None) == "default" and reasoning.current(False, None) == "off"
    assert reasoning.describe("xhigh") == "xhigh (sends max on deepseek)"
    assert reasoning.choices("deepseek") == ("off", "default", "low", "medium", "high", "max")


def test_hkgai_offers_its_seven_slots_and_thinks_only_when_asked():
    # probed: HKGAI accepts none/minimal/low/medium/high/xhigh/max; no field (or none) means no thinking
    assert reasoning.choices("hkgai") == ("off", "default", "minimal", "low", "medium", "high", "xhigh", "max")
    assert reasoning.clamp("minimal", "hkgai") == "minimal" and reasoning.clamp("xhigh", "hkgai") == "xhigh"
    assert reasoning.resolve(True, None, "hkgai") == (True, "medium")  # "default" must still think there
    assert reasoning.resolve(True, "off", "hkgai") == (False, None)
    assert reasoning.describe("default", "hkgai") == "default (sends medium on hkgai)"
    assert reasoning.describe("default", "deepseek") == "default" and reasoning.describe("xhigh", "hkgai") == "xhigh"
    assert "medium" in reasoning.description("default", "hkgai")


def test_hkgai_payload_sends_the_level_or_none():
    cfg = dict(provider="hkgai", api_key="k", base_url="https://api.hkgai.example.hk/v1", model="hk-1")
    c, seen = _capture(ModelConfig(**cfg))
    c.chat([{"role": "user", "content": "hi"}])  # bot setting "default"
    assert seen[-1]["reasoning_effort"] == "medium" and "thinking" not in seen[-1] and "temperature" not in seen[-1]
    c.chat([{"role": "user", "content": "hi"}], thinking=False)  # e.g. a discussion turn or the approval guard
    assert seen[-1]["reasoning_effort"] == "none" and seen[-1]["temperature"] == 0
    c.chat([{"role": "user", "content": "hi"}], thinking=True, effort="xhigh")  # a chat's own setting
    assert seen[-1]["reasoning_effort"] == "xhigh"
    c.chat([{"role": "user", "content": "hi"}], thinking=True, effort="default")
    assert seen[-1]["reasoning_effort"] == "medium"
    c.chat([{"role": "user", "content": "hi"}], json_mode=True)  # JSON mode never thinks there (malformed JSON when it did)
    assert seen[-1]["reasoning_effort"] == "none" and seen[-1]["response_format"] == {"type": "json_object"}
    for setting, sent in (("minimal", "minimal"), ("max", "max"), ("ultra", "max"), ("off", "none")):
        c2, seen2 = _capture(ModelConfig(**cfg, reasoning_effort=setting))
        c2.chat([{"role": "user", "content": "hi"}])
        assert seen2[-1]["reasoning_effort"] == sent, setting


def test_hkgai_reasoning_field_is_read_and_replayed():
    body = {"model": "hk-1", "choices": [{"message": {"content": "27", "reasoning": "9 stay, buys 18", "tool_calls": None}}],
            "usage": {"prompt_tokens": 9, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 4}}}
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=body)

    c = OpenAICompatClient(ModelConfig(provider="hkgai", api_key="k", base_url="https://api.hkgai.example.hk/v1", model="hk-1"),
                           transport=httpx.MockTransport(handler))
    r = c.chat([{"role": "user", "content": "sheep?"}])
    assert r.reasoning_content == "9 stay, buys 18" and r.usage.cached_tokens == 4
    tools = [{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}]
    c.chat([{"role": "user", "content": "x"}, {**r.to_message(), "content": ""}], tools)
    assert seen[-1]["messages"][1].get("reasoning_content") == "9 stay, buys 18"  # replayed with tools, as for DeepSeek
    body["choices"][0]["message"] = {"content": "plain", "reasoning": None}
    assert c.chat([{"role": "user", "content": "x"}]).reasoning_content is None


def _capture(cfg: ModelConfig):
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "deepseek-flash", "choices": [{"message": {"content": "ok"}}],
                                         "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    return OpenAICompatClient(cfg, transport=httpx.MockTransport(handler)), seen


def test_deepseek_payload_carries_the_toggle_and_the_effort():
    c, seen = _capture(ModelConfig(provider="deepseek", api_key="k", reasoning_effort="xhigh"))
    c.chat([{"role": "user", "content": "hi"}])
    assert seen[-1]["thinking"] == {"type": "enabled"} and seen[-1]["reasoning_effort"] == "max"
    c.chat([{"role": "user", "content": "hi"}], thinking=False)  # e.g. a discussion turn
    assert seen[-1]["thinking"] == {"type": "disabled"} and "reasoning_effort" not in seen[-1]
    c.chat([{"role": "user", "content": "hi"}], thinking=True, effort="low")  # a chat's own setting
    assert seen[-1]["reasoning_effort"] == "low"
    c.chat([{"role": "user", "content": "hi"}], thinking=True, effort="default")  # provider default: field omitted
    assert "reasoning_effort" not in seen[-1]
    off, seen_off = _capture(ModelConfig(provider="deepseek", api_key="k", reasoning_effort="off"))
    off.chat([{"role": "user", "content": "hi"}])
    # "none" does not switch DeepSeek's thinking off (probed); only the toggle does
    assert seen_off[-1]["thinking"] == {"type": "disabled"} and "reasoning_effort" not in seen_off[-1]


# --------------------------------------------------------------------------- per-chat settings in the agent

def test_chat_intensity_and_model_override_reach_the_model(rt, script):
    llm = script({"default": [{"content": "one"}, {"content": "two"}, {"content": "three"}]})
    prof = rt.profiles.get("default")
    store = SessionStore(prof)
    sid = store.create(kind="chat").id
    rt.agent(prof, sid).run("first")
    assert llm.turns[-1]["thinking"] is None and llm.turns[-1]["effort"] is None  # profile setting
    store.patch_meta(sid, {"reasoning": "max", "model": "deepseek-v4-pro"})
    rt.agent(prof, sid).run("second")
    assert llm.turns[-1] == {"name": "default", "thinking": True, "effort": "max"}
    assert llm.configs[-1].model == "deepseek-v4-pro"
    store.patch_meta(sid, {"reasoning": "off"})
    rt.agent(prof, sid).run("third")
    assert llm.turns[-1]["thinking"] is False


def test_subagent_inherits_the_chat_settings(rt, script):
    script({"default": [
        {"tool_calls": [("delegate_task", {"tasks": [{"goal": "count to three", "context": "just count"}]})]},
        {"content": "1 2 3"},
        {"content": "done"},
    ]})
    prof = rt.profiles.get("default")
    store = SessionStore(prof)
    sid = store.create(kind="chat", meta={"reasoning": "low", "model": "deepseek-v4-pro"}).id
    rt.agent(prof, sid).run("delegate a small count")
    sub = [s for s in store.list(kinds=("subagent",))]
    assert sub and sub[0].meta["reasoning"] == "low" and sub[0].meta["model"] == "deepseek-v4-pro"


# --------------------------------------------------------------------------- web API

def test_profile_and_chat_intensity_via_api(client, rt):
    r = client.post("/api/profiles", json={"name": "thinker", "title": "Thinker", "reasoning": "high"})
    assert r.status_code == 201, r.text
    assert client.get("/api/profiles/thinker").json()["settings"]["reasoning"] == "high"
    assert client.patch("/api/profiles/thinker", json={"reasoning": "off"}).status_code == 200
    m = rt.profiles.get("thinker").settings().model
    assert m.thinking is False and reasoning.current(m.thinking, m.reasoning_effort) == "off"
    assert client.patch("/api/profiles/thinker", json={"reasoning": "turbo"}).status_code == 400

    sid = client.post("/api/profiles/thinker/sessions", json={}).json()["id"]
    row = client.patch(f"/api/profiles/thinker/sessions/{sid}", json={"reasoning": "max", "model": "deepseek-v4-pro"}).json()
    assert row["reasoning"] == "max" and row["model"] == "deepseek-v4-pro" and row["title"] == ""
    assert client.get(f"/api/profiles/thinker/sessions/{sid}/messages").json()["session"]["reasoning"] == "max"
    assert client.patch(f"/api/profiles/thinker/sessions/{sid}", json={"reasoning": "reset", "model": ""}).json()["reasoning"] is None
    assert client.patch(f"/api/profiles/thinker/sessions/{sid}", json={"model": "gpt-4o"}).status_code == 400
    assert client.patch(f"/api/profiles/thinker/sessions/{sid}", json={"reasoning": "loud"}).status_code == 400
    assert client.patch(f"/api/profiles/thinker/sessions/{sid}", json={"title": "renamed"}).json()["title"] == "renamed"


def test_upload_and_attach_to_a_chat(client, rt, script):
    script({"default": [{"content": "I read it."}]})
    up = client.post("/api/profiles/default/uploads?filename=../../notes.md", content=b"# hi\n")
    assert up.status_code == 201, up.text
    assert up.json() == {"path": "uploads/notes.md", "name": "notes.md", "size": 5}
    again = client.post("/api/profiles/default/uploads?filename=notes.md", content=b"second")
    assert again.json()["path"] == "uploads/notes-2.md"  # never overwrites
    ws = rt.profiles.get("default").workspace
    assert (ws / "uploads/notes.md").read_bytes() == b"# hi\n"
    assert client.post("/api/profiles/default/uploads?filename=report.pdf", content=b"%PDF").status_code == 415
    assert client.post("/api/profiles/default/uploads?filename=.env", content=b"X=1").json()["path"] == "uploads/env"

    sid = client.post("/api/profiles/default/sessions", json={}).json()["id"]
    bad = client.post(f"/api/profiles/default/sessions/{sid}/messages", json={"text": "x", "attachments": ["hello.py"]})
    assert bad.status_code == 400
    r = client.post(f"/api/profiles/default/sessions/{sid}/messages", json={"text": "", "attachments": ["uploads/notes.md"]})
    assert r.status_code == 202, r.text
    data = wait_idle(client, "default", sid)
    user = [i for i in data["items"] if i["role"] == "user"][0]["content"]
    assert "`uploads/notes.md`" in user and "your workspace" in user


def test_room_uploads_go_to_the_shared_folder(client, rt):
    client.post("/api/profiles", json={"name": "ann", "title": "Ann"})
    rid = client.post("/api/rooms", json={"name": "Desk", "members": ["ann"]}).json()["id"]
    up = client.post(f"/api/rooms/{rid}/uploads?filename=data.csv", content=b"a,b\n1,2\n").json()
    assert up["path"] == "uploads/data.csv"
    assert (rt.rooms.shared_dir(rid) / "uploads/data.csv").exists()
    assert client.get(f"/api/rooms/{rid}/files?path=uploads").json()["entries"][0]["name"] == "data.csv"


def test_static_files_are_revalidated(client):
    assert client.get("/app.js").headers["cache-control"] == "no-cache"
    assert client.get("/api/status").json()["app"] == "pland"


# --------------------------------------------------------------------------- team templates

def test_requirements_team_template(client, rt):
    t = {x["id"]: x for x in list_templates()}["requirements-team"]
    assert [b["name"] for b in t["bots"]] == ["lead", "researcher", "coder", "reviewer", "writer"]
    rep = client.post("/api/team-templates/requirements-team/apply").json()
    assert rep["created"] == ["lead", "researcher", "coder", "reviewer", "writer"]
    assert [g["status"] for g in rep["groups"]] == ["created", "created"]
    s = {n: rt.profiles.get(n).settings() for n in rep["created"]}
    assert reasoning.current(s["lead"].model.thinking, s["lead"].model.reasoning_effort) == "high"
    assert reasoning.current(s["writer"].model.thinking, s["writer"].model.reasoning_effort) == "low"
    assert "code" not in s["researcher"].toolsets and "web" not in s["writer"].toolsets
    assert s["reviewer"].sandbox.backend in {"docker", "local"}  # local (with a note) where Docker is missing
    room = rt.rooms.by_name("Build team")
    assert room["members"] == ["lead", "researcher", "coder", "reviewer", "writer"] and room["settings"]["lead"] == "lead"
    again = apply_template(rt, "requirements-team")  # idempotent: nothing is overwritten
    assert again["created"] == [] and len(again["skipped"]) == 5 and {g["status"] for g in again["groups"]} == {"exists"}
    assert client.post("/api/team-templates/nope/apply").status_code == 404


# --------------------------------------------------------------------------- CLI and launch

def test_setup_flags_and_profile_set(rt, monkeypatch):
    monkeypatch.setattr(cli, "_runtime", lambda hitl=None: rt)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    assert cli.main(["setup", "-y", "--reasoning", "max", "--backend", "local", "--approvals", "manual"]) == 0
    m = rt.profiles.get("default").settings().model
    assert m.thinking is True and m.reasoning_effort == "max"
    assert cli.main(["profile", "create", "quick", "--reasoning", "off"]) == 0
    assert rt.profiles.get("quick").settings().model.thinking is False
    assert cli.main(["profile", "set", "quick", "--reasoning", "low"]) == 0
    assert rt.profiles.get("quick").settings().model.reasoning_effort == "low"
    assert cli.main(["profile", "set", "quick", "--reasoning", "turbo"]) == 1


def test_no_command_means_chat():
    assert cli.build_parser().parse_args(["chat"]).cmd == "chat"
    assert cli.build_parser().parse_args([]).cmd is None  # main() turns this into `chat`


def test_dotenv_ignores_the_current_folder(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("PLAND_TEST_FROM_CWD=1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PLAND_TEST_FROM_CWD", raising=False)
    load_dotenv(force=True)
    import os

    assert "PLAND_TEST_FROM_CWD" not in os.environ


def test_restricted_profiles_are_told_their_limits(rt):
    from pland.prompts import build_system_prompt

    full = build_system_prompt(rt, rt.profiles.get("default"), tool_names={"run_shell", "web_search", "read_file"})
    assert "Limits of this profile" not in full  # default profiles (and every evaluation run) are unchanged
    rt.profiles.create("scribe", settings={"toolsets": ["files", "team"]})
    text = build_system_prompt(rt, rt.profiles.get("scribe"), tool_names={"read_file", "write_file", "message_agent"})
    assert "You cannot run code" in text and "You cannot search or browse the web" in text
    assert "ask a teammate who can (message_agent)" in text


# --------------------------------------------------------------------------- long outputs, wrap-up, markup

def test_tool_call_cut_off_at_the_output_limit_is_not_run(rt, script):
    from pland.llm.base import LLMResponse, ToolCall, Usage

    cut = LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="write_file", arguments='{"path": "r.md", "content": "# Rep')],
                      finish_reason="length", usage=Usage(10, 8192, 0))
    script({"default": [cut,
                        {"tool_calls": [("write_file", {"path": "r.md", "content": "# Report\n"})]},
                        {"tool_calls": [("write_file", {"path": "r.md", "content": "part two\n", "append": True})]},
                        {"content": "written in two parts"}]})
    prof = rt.profiles.get("default")
    agent = rt.agent(prof)
    res = agent.run("write a long report")
    assert res.text == "written in two parts"
    tools = [m for m in agent.sessions.messages(agent.session_id) if m["role"] == "tool"]
    assert "hit the output limit (8192 tokens)" in tools[0]["content"] and "append=true" in tools[0]["content"]
    assert (prof.workspace / "r.md").read_text() == "# Report\npart two\n"


def test_cut_off_prose_is_continued(rt, script):
    from pland.llm.base import LLMResponse

    script({"default": [LLMResponse(content="The answer is forty", finish_reason="length"), {"content": "-two."}]})
    assert rt.agent("default").run("question").text == "The answer is forty-two."


def test_leaked_tool_markup_is_retried_and_never_reported(rt, script):
    leak = '<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name="run_shell">ls'
    script({"default": [{"content": leak}, {"content": "Real answer."}]})
    assert rt.agent("default").run("do it").text == "Real answer."
    from pland.agent import strip_tool_markup

    assert strip_tool_markup("Done so far: A, B.\n" + leak) == "Done so far: A, B."
    assert strip_tool_markup(leak) == ""


def test_wrap_up_shows_tools_but_forbids_calls(rt):
    from pland.llm.factory import set_client_override
    from pland.llm.scripted import ScriptedLLM

    calls = iter(range(1000))

    def step(msgs, tools):
        if "Stop using tools" in str(msgs[-1].get("content")):
            return {"content": '<｜｜DSML｜｜ invoke name="run_shell">'}  # markup even now: the report must not carry it
        return {"tool_calls": [("list_dir", {"path": f"d{next(calls)}"})]}

    llm = ScriptedLLM(step)
    set_client_override(lambda cfg: llm)
    res = rt.agent("default").run("explore", max_iterations=3)
    assert res.status == "max_iterations"
    wrap = [r for r in llm.requests if str(r["messages"][-1].get("content")).startswith("[system] The iteration limit")]
    assert len(wrap) == 1 and wrap[0]["tool_choice"] == "none" and wrap[0]["tools"]
    assert "DSML" not in res.text and res.text.startswith("(No final report")


def test_checkpoint_forces_a_write_when_nothing_was_written(rt):
    from pland.llm.factory import set_client_override
    from pland.llm.scripted import ScriptedLLM

    reads = iter(range(1000))

    def step(msgs, tools):
        names = {t["function"]["name"] for t in tools or []}
        if names and names <= {"write_file", "edit_file"}:
            return {"tool_calls": [("write_file", {"path": "report.md", "content": "# Findings so far\n"})]}
        if "report.md" in str(msgs[-1].get("content")):
            return {"content": "report written"}
        return {"tool_calls": [("list_dir", {"path": f"d{next(reads)}"})]}  # a worker that only ever reads

    llm = ScriptedLLM(step)
    set_client_override(lambda cfg: llm)
    prof = rt.profiles.get("default")
    res = rt.agent(prof).run("audit everything", max_iterations=10)
    assert (prof.workspace / "report.md").read_text() == "# Findings so far\n"
    offered = [{t["function"]["name"] for t in r["tools"] or []} for r in llm.requests]
    assert {"write_file", "edit_file"} in offered  # the step after the checkpoint offered only the file tools
    assert res.text == "report written"


def test_checkpoint_does_not_restrict_after_a_write(rt):
    from pland.llm.factory import set_client_override
    from pland.llm.scripted import ScriptedLLM

    n = iter(range(1000))

    def step(msgs, tools):
        i = next(n)
        if i == 0:
            return {"tool_calls": [("write_file", {"path": "draft.md", "content": "x"})]}
        return {"tool_calls": [("list_dir", {"path": f"d{i}"})]}

    llm = ScriptedLLM(step)
    set_client_override(lambda cfg: llm)
    rt.agent("default").run("work", max_iterations=10)
    offered = [{t["function"]["name"] for t in r["tools"] or []} for r in llm.requests if r["tools"]]
    assert all("list_dir" in names for names in offered)


def test_roster_shows_what_teammates_cannot_do(rt):
    from pland.prompts import team_section

    rt.profiles.create("scribe", title="Writer", settings={"toolsets": ["files", "team"]})
    rt.profiles.create("dev", title="Coder")
    text = team_section(rt, rt.profiles.get("default"))
    assert "@scribe: Writer [cannot run code; no web access; no git]" in text
    assert "@dev: Coder\n" in text + "\n" and "split a broad review" in text


def test_deliverables_are_read_from_expected_output():
    from pland.team.delegation import deliverables

    assert deliverables({"expected_output": "write shared/r/01-review.md and 02-scan.csv; see https://x.org/a.html"}) == \
        ["shared/r/01-review.md", "02-scan.csv"]
    assert deliverables({"expected_output": "~/n.md, ../y.py; v2.6.4, e.g. a version"}) == ["~/n.md", "../y.py"]
    assert deliverables({"expected_output": "a short answer"}) == [] and deliverables({}) == []


def _worker(rt, session_meta, step):
    from pland.llm.factory import set_client_override
    from pland.llm.scripted import ScriptedLLM

    llm = ScriptedLLM(step)
    set_client_override(lambda cfg: llm)
    prof = rt.profiles.get("default")
    sid = SessionStore(prof).create(kind="delegation", meta=session_meta).id
    return llm, prof, rt.agent(prof, sid, role="delegate")


def test_checkpoint_names_a_missing_deliverable_even_after_other_writes(rt):
    n = iter(range(1000))

    def step(msgs, tools):
        names = {t["function"]["name"] for t in tools or []}
        if names and names <= {"write_file", "edit_file"}:
            return {"tool_calls": [("write_file", {"path": "out/report.md", "content": "# Report\n"})]}
        if "out/report.md" in str(msgs[-1].get("content")) and msgs[-1].get("role") == "tool":
            return {"content": "done"}
        i = next(n)
        if i == 0:
            return {"tool_calls": [("write_file", {"path": "probe.py", "content": "print(1)"})]}  # a helper, not the report
        return {"tool_calls": [("list_dir", {"path": f"d{i}"})]}

    llm, prof, agent = _worker(rt, {"deliverables": ["out/report.md"]}, step)
    res = agent.run("review it", max_iterations=10)
    assert (prof.workspace / "out/report.md").exists() and res.text == "done"
    notes = [m["content"] for m in agent.sessions.messages(agent.session_id) if m["role"] == "user"]
    assert any("out/report.md does not exist yet" in t for t in notes)


def test_step_limit_saves_a_missing_deliverable(rt):
    n = iter(range(1000))

    def step(msgs, tools):
        names = {t["function"]["name"] for t in tools or []}
        last = str(msgs[-1].get("content"))
        if "Stop using tools" in last:
            return {"content": "partial report"}
        if names and names <= {"write_file", "edit_file"} and "step limit is reached" in last:
            return {"tool_calls": [("write_file", {"path": "final.md", "content": "# What I found so far\n"})]}
        if names and names <= {"write_file", "edit_file"}:
            return {"content": "not yet"}  # ignores the checkpoint
        return {"tool_calls": [("list_dir", {"path": f"d{next(n)}"})]}

    llm, prof, agent = _worker(rt, {"deliverables": ["final.md"]}, step)
    agent.run("audit", max_iterations=6)
    assert (prof.workspace / "final.md").read_text() == "# What I found so far\n"
    assert any(r for r in llm.requests if str(r["messages"][-1].get("content")).startswith("[system] The step limit is reached"))
