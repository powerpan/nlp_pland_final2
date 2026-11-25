"""Text the server sends to the web UI is translated too (pland/server/static/i18n/zh-Hant.server.json).

The server keeps writing English — the CLI, API clients and the bots read the same strings — and the browser
translates for display by matching each message against English templates with {name} placeholders (`ts()` in
app.js). This test collects those templates from the Python sources, so a new error message, notice or system line
without an entry fails here instead of turning up in English in a Chinese interface.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import yaml

from tests.test_i18n import SIMPLIFIED_ONLY, STATIC

ROOT = Path(__file__).resolve().parents[1] / "pland"
SERVER_ZH = STATIC / "i18n" / "zh-Hant.server.json"
_PLACEHOLDER = re.compile(r"\{(\w+)\}")

# Modules whose exception messages reach the browser as the `detail` of an API error.
RAISING = ("server/app.py", "server/files.py", "server/settings.py", "keys.py", "workspace.py", "team/rooms.py",
           "profiles.py", "team/templates.py", "team/role_file.py", "sessions.py", "hitl.py", "llm/reasoning.py")
# Phrases the server puts *inside* a message (the value of a placeholder).
PHRASES = {"the group's default shared folder", "a subagent", "an API key", "an endpoint", "a model",
           "answered", "expired", "cancelled", "settled"}  # a HITL request's status in "request {id} is already {status}"
# Messages that never reach the web UI's user: a wrong-usage reply to another API client, or a CLI-only path.
NOT_SHOWN = {"Reply with OK."}  # the prompt of the key test call (sent to the model, never displayed)


def template(node: ast.AST | None) -> str | None:
    """The message a string expression builds, with `{}` where a value is filled in (None: not a literal)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = template(node.left), template(node.right)
        return None if left is None or right is None else left + right
    return None


def branches(node: ast.AST | None) -> list[ast.AST]:
    """`a if cond else b` contributes both of its messages."""
    if isinstance(node, ast.IfExp):
        return branches(node.body) + branches(node.orelse)
    return [node] if node is not None else []


def tree(rel: str) -> ast.AST:
    return ast.parse((ROOT / rel).read_text(encoding="utf-8"))


def raised_messages(rel: str) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(tree(rel)):
        if not (isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call) and n.exc.args):
            continue
        name = getattr(n.exc.func, "id", getattr(n.exc.func, "attr", ""))
        if name in {"KeyError", "ToolError"} and rel not in {"profiles.py", "team/templates.py", "sessions.py"}:
            continue  # a bare id (KeyError(rid)) or a message for the model, not for the page
        arg = n.exc.args[1] if name == "HTTPException" and len(n.exc.args) > 1 else n.exc.args[0]
        out |= {t for t in map(template, branches(arg)) if t}
    return out


def sentences(rel: str, *, inside: tuple[str, ...] = ()) -> set[str]:
    """Full sentences a module returns as notices or reasons: non-docstring string literals ending in a full stop.
    `inside` limits the search to the named functions."""
    out: set[str] = set()
    mod = tree(rel)
    scopes = [n for n in ast.walk(mod) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and (not inside or n.name in inside)]
    for scope in scopes:
        docstring = ast.get_docstring(scope, clean=False)
        skip: set[int] = set()
        for n in ast.walk(scope):  # the constants inside an f-string are parts of its template, not messages
            if isinstance(n, ast.JoinedStr):
                skip |= {id(v) for v in ast.walk(n) if v is not n}
        for n in ast.walk(scope):
            if id(n) in skip:
                continue
            t = template(n) if isinstance(n, (ast.Constant, ast.JoinedStr)) else None
            if t and t != docstring and t.endswith(".") and (" " in t or inside) and len(t) > 5:
                out.add(t)
    return out


def room_lines() -> set[str]:
    """What the server posts into a group's transcript as a system note or an activity line (its first line)."""
    out: set[str] = set()
    for rel in ("team/rooms.py", "team/delegation.py"):
        for n in ast.walk(tree(rel)):
            if not (isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "post" and len(n.args) >= 3):
                continue
            kind = next((k.value.value for k in n.keywords if k.arg == "kind" and isinstance(k.value, ast.Constant)), None)
            if kind in {"system", "activity"}:
                out |= {t.split("\n")[0] for t in map(template, branches(n.args[2])) if t}
    return out


def guard_refusals() -> set[str]:
    cls = next(n for n in ast.walk(tree("server/app.py")) if isinstance(n, ast.ClassDef) and n.name == "SameOriginGuard")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "refusal")
    return {t for n in ast.walk(fn) if isinstance(n, ast.Return) and (t := template(n.value))}


def template_texts() -> set[str]:
    out: set[str] = set()
    for path in (ROOT / "team_templates").glob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        out |= {data["title"], data["description"]} | {b["description"] for b in data["bots"] if b.get("description")}
    return {" ".join(t.split()) for t in out}


def needed() -> set[str]:
    out = set(PHRASES) | room_lines() | guard_refusals() | template_texts()
    for rel in RAISING:
        out |= raised_messages(rel)
    out |= sentences("keys.py")  # warnings returned next to a saved key or provider
    out |= sentences("server/app.py", inside=("put_key", "delete_key", "patch_provider"))  # "Saved.", "Key removed." …
    out |= sentences("workspace.py", inside=("resolve",))  # the chosen folder is gone
    out |= sentences("team/fast.py", inside=("summary",))  # the first line of a Fast Mode group's closing summary
    return out - NOT_SHOWN


def shape(key: str) -> str:
    """A dictionary key with its placeholder names dropped, comparable to a collected template."""
    return _PLACEHOLDER.sub("{}", key)


def zh() -> dict[str, str]:
    return json.loads(SERVER_ZH.read_text(encoding="utf-8"))


def test_the_collector_finds_what_it_should():
    found = needed()
    for sample in ("no profile named {}", "{} is a system folder", "Saved (not tested).", "Key removed.",
                   "Room created with {}.", "→ delegated to {}: {}", "✓ finished delegated task: {}",
                   "refused: cross-site request", "{} must be between {} and {}", "Requirements team",
                   "{} is also exported by the shell PlanD was started from; the shell value takes precedence after a restart."):
        assert sample in found, sample
    assert len(found) > 100


def test_every_server_message_has_a_translation():
    have = {shape(k) for k in zh()}
    missing = sorted(needed() - have)
    assert not missing, "server text with no entry in zh-Hant.server.json:\n  " + "\n  ".join(missing)


def test_no_stale_entries():
    stale = sorted(k for k in zh() if shape(k) not in needed())
    assert not stale, "zh-Hant.server.json has entries the server no longer sends:\n  " + "\n  ".join(stale)


def test_entries_are_well_formed():
    data = zh()
    shapes: dict[str, str] = {}
    for key, value in data.items():
        assert value.strip(), key
        assert sorted(_PLACEHOLDER.findall(key)) == sorted(_PLACEHOLDER.findall(value)), f"placeholders differ: {key}"
        assert len(set(_PLACEHOLDER.findall(key))) == len(_PLACEHOLDER.findall(key)), f"a placeholder name repeats: {key}"
        assert "{}" not in key and not re.search(r"\}\{", key), f"two values with nothing between them cannot be told apart: {key}"
        assert not SIMPLIFIED_ONLY & set(value), f"Simplified characters in: {value}"
        assert shapes.setdefault(shape(key), key) == key, f"two entries for the same message: {key} / {shapes[shape(key)]}"


def test_dictionary_is_loaded_served_and_shipped(rt):
    from fastapi.testclient import TestClient

    from pland.server.app import create_app

    res = TestClient(create_app(rt)).get("/i18n/zh-Hant.server.json")
    assert res.status_code == 200 and res.json()["Key removed."] == "金鑰已移除。"
    assert ".server.json" in (STATIC / "boot.js").read_text(encoding="utf-8")  # the dictionary loader index.html runs first
    pyproject = (ROOT.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert '"server/static/i18n/*.json"' in pyproject
