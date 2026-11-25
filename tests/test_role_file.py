from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from pland.server.app import create_app
from pland.team.role_file import import_role_file


FILE = """# Scenario 7: Archive desk

| Agent ID | Role |
|---|---|
| `curator` | Curator |
| `scribe` | Records Editor |

## Records Editor (scribe)

```text
Record the findings.
Keep the original order.
```

## Curator (curator)

```text
Work with the requester.
```
"""


def test_role_file_import_through_api(rt):
    with TestClient(create_app(rt)) as client:
        body = {"content": "\ufeff" + FILE.replace("\n", "\r\n")}
        r = client.post("/api/team-templates/import", json=body)
        assert r.status_code == 200
        team = r.json()
        assert team["name"] == "Archive desk" and team["members"] == ["curator", "scribe"]
        assert team["created_group"] and team["created_bots"] == team["members"]
        room = rt.rooms.get(team["group"])
        assert room["settings"]["lead"] == "curator" and room["members"] == team["members"]
        assert room["settings"]["fast_mode"] is True
        p = rt.profiles.get("scribe")
        assert p.is_bot and p.title == "Records Editor" and p.meta["settings"] == {}
        assert p.soul == "Record the findings.\nKeep the original order."
        rt.rooms.post(room["id"], "user", "Remember the context.")
        client.patch(f"/api/rooms/{room['id']}", json={"fast_mode": False}).raise_for_status()
        repeated = client.post("/api/team-templates/import", json=body).json()
        assert not repeated["created_group"] and repeated["created_bots"] == []
        assert repeated["group"] == room["id"]
        assert rt.rooms.get(room["id"])["settings"]["fast_mode"] is False
        assert rt.rooms.messages(room["id"])[-1]["content"] == "Remember the context."


@pytest.mark.parametrize("text", [
    "# Task 1\n\nPlease write a report.",
    FILE[:FILE.index("## Curator")], FILE.rstrip().removesuffix("```"), FILE.replace("`scribe`", "`curator`"),
    FILE.replace("curator", "default"), FILE.replace("Curator (curator)", "Curator (other)"),
    FILE.replace("Work with the requester.", " "), "a" * (256 * 1024 + 1),
])
def test_invalid_team_file_creates_nothing(rt, text):
    with TestClient(create_app(rt)) as client:
        response = client.post("/api/team-templates/import", json={"content": text})
        assert response.status_code == 400 and response.json()["detail"]
    assert rt.rooms.list() == [] and rt.profiles.list(bots_only=True) == []


@pytest.mark.parametrize("conflict", ["bot", "group"])
def test_import_conflicts_do_not_overwrite_or_partially_create(rt, conflict):
    rt.profiles.create("scribe", title="Existing editor", soul="Keep my notes.")
    if conflict == "group":
        rt.rooms.create("Archive desk", ["scribe"], lead="scribe")
    with TestClient(create_app(rt)) as client:
        response = client.post("/api/team-templates/import", json={"content": FILE})
        assert response.status_code == 409
    assert not rt.profiles.exists("curator") and rt.profiles.get("scribe").soul == "Keep my notes."
    assert len(rt.rooms.list()) == int(conflict == "group")


def test_failed_creation_keeps_existing_bot_and_can_be_retried(rt, monkeypatch):
    rt.profiles.create("curator", title="Curator", soul="Work with the requester.")
    def fail(*args, **kwargs):
        raise OSError("room creation failed")
    with monkeypatch.context() as patch:
        patch.setattr(rt.rooms, "create", fail)
        with pytest.raises(OSError):
            import_role_file(rt, FILE)
    assert rt.profiles.exists("curator") and not rt.profiles.exists("scribe")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: import_role_file(rt, FILE), range(2)))
    assert results[0]["group"] == results[1]["group"]
    assert sorted(r["created_group"] for r in results) == [False, True]
