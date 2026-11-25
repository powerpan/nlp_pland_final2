"""An agent's knowledge of the platform it runs on: the handbook, the `platform_info` tool, and the checks that keep
the prose in step with the code."""

import re

import pytest

from pland import handbook
from pland.cli import build_parser
from pland.config import AgentSettings
from pland.prompts import build_system_prompt
from pland.server.settings import FIELDS
from pland.tools import load_builtin_tools
from pland.tools.registry import TOOLS, ToolContext, execute


def make(rt, name="default", **kw):
    return rt.agent(name, **kw)


def ctx_of(agent) -> ToolContext:
    return ToolContext(runtime=agent.runtime, agent=agent, profile=agent.profile, settings=agent.settings,
                       session_id=agent.session_id, run_id="r", backend=agent.backend, paths=agent.paths,
                       hitl=agent.hitl, approvals=None, room_id=agent.room_id)


def ask(agent, topic: str) -> str:
    return execute(TOOLS["platform_info"], ctx_of(agent), {"topic": topic})


# ------------------------------------------------------------------ the tool

def test_every_topic_renders(rt):
    agent = make(rt)
    for topic in handbook.TOPICS:
        out = ask(agent, topic)
        assert not out.startswith("ERROR"), (topic, out[:200])
        assert len(out) > 300, topic
        assert len(out) < 24_000, f"{topic} would be cut by the tool-result cap"


def test_unknown_topic_is_refused_with_the_list(rt):
    out = execute(TOOLS["platform_info"], ctx_of(make(rt)), {"topic": "pricing"})
    assert out.startswith("ERROR") and "collaboration" in out


def test_tool_reaches_every_agent_whatever_its_toolsets(rt):
    rt.profiles.create("writer", title="Writer", settings={"toolsets": ["files"]})
    assert "platform_info" in make(rt, "writer").tools
    assert "platform_info" in make(rt, role="subagent").tools
    assert "run_shell" not in make(rt, "writer").tools  # the bot's own restriction still holds


def test_agent_answers_from_the_handbook_in_a_run(rt, script):
    script([{"tool_calls": [("platform_info", {"topic": "collaboration"})]}, {"content": "We collaborate through delegation."}])
    agent = make(rt)
    result = agent.run("你如何與團隊協作？")
    assert result.status == "completed"
    tool_msgs = [m for m in agent.sessions.messages(agent.session_id) if m["role"] == "tool"]
    assert any("delegate_task" in (m["content"] or "") and "[PASS]" in (m["content"] or "") for m in tool_msgs)


def test_system_prompt_points_at_the_tool(rt):
    prof = rt.profiles.get("default")
    with_tool = build_system_prompt(rt, prof, tool_names={"platform_info", "read_file"})
    assert "PlanD" in with_tool and "platform_info" in with_tool
    assert "platform_info" not in build_system_prompt(rt, prof, tool_names={"read_file"})


# ------------------------------------------------------------------ live status

def test_status_reports_this_agents_own_setup(rt):
    rt.profiles.create("coder", title="Coder", description="writes Python", settings={
        "toolsets": ["files", "code", "plan"], "approvals": {"mode": "smart"}, "max_iterations": 33,
        "model": {"reasoning_effort": "high"}})
    rt.profiles.create("reviewer", title="Reviewer")
    room = rt.rooms.create("Build", ["coder", "reviewer"], lead="reviewer")
    out = ask(make(rt, "coder"), "status")
    assert "Coder (@coder)" in out and "a bot in the roster" in out
    assert "`smart`" in out and "33 steps" in out and "high" in out
    assert "files, code, plan" in out and "Without:" in out and "web" in out
    assert "@reviewer (Reviewer)" in out
    assert f"Group '{room['name']}'" in out and "lead @reviewer" in out
    alone = ask(make(rt), "status")
    assert "the default single agent" in alone


def test_status_and_configuration_never_show_a_key(rt, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "not-a-real-key-SENTINEL-0123456789")
    agent = make(rt)
    for topic in handbook.TOPICS:
        assert "SENTINEL" not in ask(agent, topic), topic
    assert "API key is set" in ask(agent, "status")


def test_configuration_shows_the_value_in_effect(rt):
    rt.profiles.create("slow", title="Slow", settings={"max_run_calls": 77, "sandbox": {"command_timeout": 45}})
    out = ask(make(rt, "slow"), "configuration")
    row = next(line for line in out.splitlines() if line.startswith("| `max_run_calls`"))
    assert row.rstrip(" |").endswith("77") and "| 300 |" in row
    assert re.search(r"\| `sandbox\.command_timeout` .*\| 120 \| 45 \|", out)


# ------------------------------------------------------------------ prose stays in step with the code

def test_every_setting_is_documented():
    assert set(handbook.SETTING_NOTES) == set(FIELDS), "a Settings-page field has no note (or a note has no field)"
    missing = handbook.all_setting_paths() - handbook.documented_setting_paths()
    assert not missing, f"AgentSettings fields the configuration topic does not cover: {sorted(missing)}"
    stale = set(handbook.FILE_ONLY_NOTES) - handbook.all_setting_paths()
    assert not stale, f"documented settings that no longer exist: {sorted(stale)}"


def test_defaults_quoted_in_the_prose_match_the_code():
    s = AgentSettings()
    limits = handbook.read_topic("limits")
    for needle in (f"default {s.max_iterations})", f"default {s.max_run_calls})", f"default {s.max_run_tokens:,};",
                   f"default {s.model.max_tokens:,},", f"default {s.context_char_budget:,}",
                   f"default {int(s.sandbox.command_timeout)})"):
        assert needle in limits, needle
    collab = handbook.read_topic("collaboration")
    assert f"default {s.max_parallel_delegations})" in collab and f"default {s.max_delegation_depth})" in collab
    from pland.agent import MAX_TOOL_RESULT
    from pland.memory import LIMITS
    from pland.team import delegation, rooms

    assert f"{MAX_TOOL_RESULT:,} characters" in limits
    memory = handbook.read_topic("memory")
    assert f"{LIMITS['memory']:,} characters" in memory and f"{LIMITS['user']:,} characters" in memory
    assert f"after {rooms.MAX_ROUNDS} rounds or {rooms.MAX_MESSAGES} messages" in collab
    assert f"up to {delegation.MAX_RETURN_FILES} files" in collab


def test_every_tool_and_toolset_is_listed():
    load_builtin_tools()
    out = handbook.tools_reference()
    for name, t in TOOLS.items():
        assert f"`{name}`" in out, name
        assert t.toolset in handbook.TOOLSET_NOTES, f"toolset {t.toolset!r} has no note"
    for toolset in AgentSettings().toolsets:
        assert toolset in handbook.TOOLSET_NOTES
        assert toolset in handbook.FILE_ONLY_NOTES["toolsets"]


def test_tools_named_in_the_prose_exist():
    load_builtin_tools()
    names = set()
    for topic in handbook.TOPICS:
        if topic not in handbook.GENERATED:
            names |= set(re.findall(r"`([a-z]+_[a-z_]+)`", handbook.read_topic(topic)))
    settings_words = {p.split(".")[-1] for p in handbook.all_setting_paths()} | set(FIELDS)

    def params(schema) -> set[str]:  # argument names of every tool, nested ones included
        found = set()
        if isinstance(schema, dict):
            for key, val in (schema.get("properties") or {}).items():
                found |= {key} | params(val)
            found |= params(schema.get("items"))
        return found

    known = set(TOOLS) | settings_words | {"room_member"} | set().union(*(params(t.parameters) for t in TOOLS.values()))
    unknown = names - known
    assert not unknown, f"the handbook names tools or settings that do not exist: {sorted(unknown)}"


def test_cli_commands_named_in_the_handbook_exist():
    parser = build_parser()
    sub = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
    text_ = handbook.read_topic("interfaces")
    for cmd in set(re.findall(r"`pland ([a-z]+)", text_)):
        assert cmd in sub.choices, f"`pland {cmd}` is not a command"
    chat = sub.choices["chat"].format_help()
    for flag in ("--bot-chat", "--session", "--reasoning", "--yolo", "-w", "-q", "-c", "-p"):
        assert flag in text_ and flag in chat, flag
    import inspect

    from pland import cli

    source = inspect.getsource(cli)
    for slash in set(re.findall(r"`(/[a-z]+)", text_)):
        assert f'"{slash}' in source, f"{slash} is not a CLI slash command"


def test_topics_and_files_agree():
    files = {p.stem for p in handbook.HERE.glob("*.md")}
    assert files == set(handbook.TOPICS) - handbook.GENERATED
    overview = handbook.read_topic("overview")
    for topic in handbook.TOPICS:
        assert f"`{topic}`" in overview or topic == "overview"


@pytest.mark.parametrize("topic", sorted(set(handbook.TOPICS) - handbook.GENERATED))
def test_handbook_files_ship_with_the_package(topic):
    pyproject = (handbook.HERE.parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^pland = \[.*"handbook/\*\.md".*\]', pyproject, re.M), "handbook files are not package data"
    assert (handbook.HERE / f"{topic}.md").is_file()
