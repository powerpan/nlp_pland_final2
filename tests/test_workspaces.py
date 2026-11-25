"""Per-conversation working folders (pland/workspace.py) — no network."""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

import pytest

from pland import cli
from pland import workspace as ws
from pland.sandbox.backends import LocalBackend
from pland.server.app import create_app
from pland.sessions import SessionStore

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient


@pytest.fixture()
def client(rt):
    with TestClient(create_app(rt)) as c:
        yield c


@pytest.fixture()
def project(tmp_path):
    p = tmp_path / "project"
    p.mkdir()
    (p / "data.txt").write_text("42\n", encoding="utf-8")
    return p.resolve()


def test_check_workspace_refuses_broad_and_private_folders(rt, project):
    assert ws.check_workspace(project, pland_root=rt.root) == project
    home = Path(os.path.expanduser("~"))
    for bad in ["/", str(home), "/etc", "/usr/local", str(rt.root), str(rt.root / "profiles"), "relative/path",
                str(project / "missing")]:
        with pytest.raises(ws.WorkspaceError):
            ws.check_workspace(bad, pland_root=rt.root)
    if (home / ".ssh").is_dir():
        with pytest.raises(ws.WorkspaceError):
            ws.check_workspace(home / ".ssh", pland_root=rt.root)
    folder, reason = ws.launch_folder_default(ws.INSTALL_ROOT, pland_root=rt.root)
    assert folder is None and "installation" in reason
    assert ws.launch_folder_default(project, pland_root=rt.root) == (project, "")


def test_agent_works_in_the_chosen_folder(rt, script, project):
    script({"default": [
        {"tool_calls": [("write_file", {"path": "out.md", "content": "hi"}), ("read_file", {"path": "data.txt"})]},
        {"content": "done"},
    ]})
    prof = rt.profiles.get("default")
    sid = SessionStore(prof).create(kind="chat", meta={"workspace": str(project)}).id
    agent = rt.agent(prof, sid)
    assert agent.workspace == project and agent.custom_workspace
    agent.run("write out.md and read data.txt")
    assert (project / "out.md").read_text() == "hi"
    assert not (prof.workspace / "out.md").exists()
    system = SessionStore(prof).messages(sid)[0]["content"]
    assert f"Working folder of this conversation: {project}" in system
    tool_out = [m["content"] for m in SessionStore(prof).messages(sid) if m["role"] == "tool"]
    assert any("42" in t for t in tool_out)


def test_folder_change_is_noted_and_a_missing_folder_stops_the_run(rt, script, project, tmp_path):
    script({"default": [{"content": "one"}, {"content": "two"}, {"content": "never"}]})
    prof = rt.profiles.get("default")
    store = SessionStore(prof)
    sid = store.create(kind="chat").id
    rt.agent(prof, sid).run("first")
    store.patch_meta(sid, {"workspace": str(project)})
    rt.agent(prof, sid).run("second")
    notes = [m["content"] for m in store.messages(sid) if m["role"] == "user" and m["content"].startswith("[system] The working folder")]
    assert len(notes) == 1 and str(project) in notes[0]
    gone = tmp_path / "gone"
    gone.mkdir()
    store.patch_meta(sid, {"workspace": str(gone)})
    gone.rmdir()
    res = rt.agent(prof, sid).run("third")
    assert res.status == "error" and "no longer exists" in res.text


def test_subagent_works_in_the_same_folder(rt, script, project):
    script({"default": [
        {"tool_calls": [("delegate_task", {"tasks": [{"goal": "write sub.txt", "context": "say ok"}]})]},
        {"tool_calls": [("write_file", {"path": "sub.txt", "content": "ok"})]},
        {"content": "wrote it"},
        {"content": "done"},
    ]})
    prof = rt.profiles.get("default")
    sid = SessionStore(prof).create(kind="chat", meta={"workspace": str(project)}).id
    rt.agent(prof, sid).run("delegate")
    assert (project / "sub.txt").read_text() == "ok"


@pytest.mark.skipif(sys.platform != "darwin" or not os.path.exists("/usr/bin/sandbox-exec"), reason="needs macOS Seatbelt")
def test_seatbelt_confines_commands_to_the_chosen_folder(tmp_path, project):
    home = tmp_path / "bot" / ".home"
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    # tmp_path plays /Users: everything below it is off limits except the chosen folder and the private HOME
    b = LocalBackend(workspace=project, home_dir=home, deny_roots=[tmp_path])
    r = b.run("pwd; touch inside.txt; echo $HOME", project)
    assert r.exit_code == 0 and (project / "inside.txt").exists() and str(home) in r.stdout
    assert not (project / ".home").exists()  # the private HOME stays with the bot
    r = b.run(f"touch {sibling}/x.txt", project)
    assert r.exit_code != 0 and not (sibling / "x.txt").exists()


# --------------------------------------------------------------------------- web API

def test_chat_folder_via_api(client, rt, project):
    sid = client.post("/api/profiles/default/sessions", json={}).json()["id"]
    row = client.get(f"/api/profiles/default/sessions/{sid}").json()
    assert row["workspace_custom"] is False and row["workspace"].endswith("workspace")
    assert client.patch(f"/api/profiles/default/sessions/{sid}", json={"workspace": "/etc"}).status_code == 400
    assert client.patch(f"/api/profiles/default/sessions/{sid}", json={"workspace": str(rt.root)}).status_code == 400
    row = client.patch(f"/api/profiles/default/sessions/{sid}", json={"workspace": str(project)}).json()
    assert row["workspace"] == str(project) and row["workspace_custom"] is True
    listing = client.get(f"/api/profiles/default/files?session={sid}").json()
    assert [e["name"] for e in listing["entries"]] == ["data.txt"]
    up = client.post(f"/api/profiles/default/uploads?session={sid}&filename=n.md", content=b"x").json()
    assert (project / up["path"]).read_bytes() == b"x"
    assert client.get("/api/workspaces/recent").json()[0] == str(project)
    back = client.patch(f"/api/profiles/default/sessions/{sid}", json={"workspace": "default"}).json()
    assert back["workspace_custom"] is False


def test_folder_listing_shows_folders_only(client, project):
    (project / "sub").mkdir()
    (project / ".hidden").mkdir()
    d = client.get(f"/api/fs/dirs?path={project}").json()
    assert [x["name"] for x in d["dirs"]] == ["sub"] and d["usable"] is True
    assert d["parent"] == str(project.parent)
    root = client.get("/api/fs/dirs?path=/").json()
    assert root["usable"] is False and "too broad" in root["reason"]
    assert client.get("/api/fs/dirs?path=relative").status_code == 400


def test_group_shared_folder_can_be_chosen(client, rt, project):
    client.post("/api/profiles", json={"name": "ann", "title": "Ann"})
    rid = client.post("/api/rooms", json={"name": "Proj", "members": ["ann"]}).json()["id"]
    row = client.patch(f"/api/rooms/{rid}", json={"workspace": str(project)}).json()
    assert row["workspace"] == str(project) and row["workspace_custom"] is True
    assert rt.rooms.shared_dir(rid) == project
    assert client.get(f"/api/rooms/{rid}/files").json()["entries"][0]["name"] == "data.txt"
    row = client.patch(f"/api/rooms/{rid}", json={"workspace": ""}).json()
    assert row["workspace_custom"] is False and rt.rooms.shared_dir(rid) != project


# --------------------------------------------------------------------------- CLI

def test_cli_folder_choice(rt, project, monkeypatch):
    prof = rt.profiles.get("default")
    store = SessionStore(prof)
    monkeypatch.setattr(cli, "_runtime", lambda hitl=None: rt)
    monkeypatch.chdir(project)
    sid = store.create(kind="chat").id
    assert "started pland in" in cli._choose_workspace(prof, store, sid, None, resumed=False)
    assert store.get(sid).meta["workspace"] == str(project)
    resumed = store.create(kind="chat").id
    assert cli._choose_workspace(prof, store, resumed, None, resumed=True) == ""  # keeps what it had
    assert "workspace" not in store.get(resumed).meta
    cli._choose_workspace(prof, store, sid, "default", resumed=False)
    assert store.get(sid).meta["workspace"] is None
    with pytest.raises(ValueError):
        cli._choose_workspace(prof, store, sid, "/etc", resumed=False)
    monkeypatch.chdir(Path(os.path.expanduser("~")))
    other = store.create(kind="chat").id
    assert "too broad" in cli._choose_workspace(prof, store, other, None, resumed=False)
    # bare options mean `chat`
    assert cli.build_parser().parse_args(["chat", "-w", str(project)]).workspace == str(project)


# --------------------------------------------------------------------------- bots and groups

def test_bot_chat_per_folder(rt, script, project, tmp_path):
    other = (tmp_path / "other")
    other.mkdir()
    other = other.resolve()
    script({"coder": [{"content": "in project"}, {"content": "in other"}, {"content": "home"}]})
    coder = rt.profiles.create("coder", title="Coder")
    home = coder.canonical_chat_id()
    a = coder.bot_chat_id(str(project))
    b = coder.bot_chat_id(str(other))
    assert len({home, a, b}) == 3 and coder.bot_chat_id(str(project)) == a  # one per folder, reused
    rt.agent(coder, a).run("work on the project")
    rt.agent(coder, b).run("work on the other one")
    store = SessionStore(coder)
    texts_a = " ".join(str(m.get("content")) for m in store.messages(a))
    assert "work on the project" in texts_a and "other one" not in texts_a  # contexts stay apart
    assert coder.latest_bot_chat_id() == b
    assert {c["workspace"] for c in coder.bot_chats()} == {None, str(project), str(other)}
    assert rt.agent(coder, a).workspace == project and rt.agent(coder, home).workspace == coder.workspace.resolve()


def test_bot_chat_api_switch_and_move(client, rt, project, tmp_path):
    client.post("/api/profiles", json={"name": "coder", "title": "Coder"})
    home = client.get("/api/profiles/coder/bot-chat").json()
    assert home["session"]["workspace_custom"] is False
    r = client.get(f"/api/profiles/coder/bot-chat?folder={project}").json()
    assert r["session_id"] != home["session_id"] and r["session"]["workspace"] == str(project)
    assert {t["workspace"] for t in r["threads"]} == {None, str(project)}
    assert client.get("/api/profiles/coder/bot-chat").json()["session_id"] == r["session_id"]  # the latest
    assert client.get(f"/api/profiles/coder/bot-chat?session={home['session_id']}").json()["session_id"] == home["session_id"]
    # moving the home chat onto a folder that already has its own chat is refused
    clash = client.patch(f"/api/profiles/coder/sessions/{home['session_id']}", json={"workspace": str(project)})
    assert clash.status_code == 409 and "already has a Bot Chat" in clash.text
    free = tmp_path / "free"
    free.mkdir()
    moved = client.patch(f"/api/profiles/coder/sessions/{home['session_id']}", json={"workspace": str(free)})
    assert moved.status_code == 200 and moved.json()["workspace_custom"] is True
    assert rt.profiles.get("coder").canonical_chat_id() not in {home["session_id"], r["session_id"]}  # a new home chat


def test_group_folder_change_is_announced_to_members(client, rt, script, project):
    script({"ann": [{"content": "first turn"}, {"content": "second turn"}]})
    client.post("/api/profiles", json={"name": "ann", "title": "Ann"})
    rid = client.post("/api/rooms", json={"name": "Proj", "members": ["ann"]}).json()["id"]
    rt.rooms.send(rid, "@ann hello", background=False)
    client.patch(f"/api/rooms/{rid}", json={"workspace": str(project)})
    notes = [m for m in rt.rooms.messages(rid) if m["kind"] == "system" and "shared folder is now" in m["content"]]
    assert len(notes) == 1 and str(project) in notes[0]["content"]
    client.patch(f"/api/rooms/{rid}", json={"workspace": str(project)})  # unchanged: no second note
    assert len([m for m in rt.rooms.messages(rid) if "shared folder is now" in m["content"]]) == 1
    rt.rooms.send(rid, "@ann what changed?", background=False)
    member_sid = [s for s in SessionStore(rt.profiles.get("ann")).list(kinds=("room_member",))][0].id
    seen = " ".join(str(m.get("content")) for m in SessionStore(rt.profiles.get("ann")).messages(member_sid))
    assert "shared folder is now" in seen  # the member read the note at its next turn
