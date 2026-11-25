from __future__ import annotations

import json
import os
import re

import pytest

from pland import config
from pland.hitl import ScriptedHITL
from pland.llm.base import LLMResponse
from pland.llm.factory import set_client_override
from pland.llm.scripted import ScriptedLLM, _coerce
from pland.runtime import Runtime
from pland.store import DB

# Unit tests never see the developer's real setup: no .env file is read (keys, PLAND_PROVIDER) and provider variables
# exported by the shell are dropped, so the suite behaves the same whichever provider the developer uses.
for _var in ("PLAND_PROVIDER", "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL", "HKGAI_API_KEY", "HKGAI_BASE_URL",
             "HKGAI_MODEL"):
    os.environ.pop(_var, None)


@pytest.fixture(autouse=True)
def _no_real_dotenv(monkeypatch):
    monkeypatch.setattr(config, "env_files", lambda: [])


REFLECTION = json.dumps({"outcome": "success", "summary": "did it", "lessons": ["check files exist"],
                         "procedure": "1. write 2. verify", "tags": ["test"], "memory_notes": []})


class RoutingLLM:
    """Routes each chat call to a per-agent script, identified by the '(@name)' in the system prompt.
    Reflection and compaction calls get canned answers."""

    def __init__(self, scripts: dict[str, list], reflection: str = REFLECTION):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.reflection = reflection
        self.calls: list[tuple[str, list[dict]]] = []
        self.turns: list[dict] = []  # per agent call: name, thinking and effort overrides
        self.configs: list = []  # ModelConfig of every client the agents asked for
        self.provider, self.model = "scripted", "scripted"

    def __call__(self, cfg):
        self.configs.append(cfg)
        return self

    def chat(self, messages, tools=None, *, json_mode=False, max_tokens=None, temperature=None, on_delta=None, thinking=None,
             effort=None, tool_choice=None) -> LLMResponse:
        system = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
        last = messages[-1].get("content") or "" if messages else ""
        if "extract reusable experience" in system or str(last).startswith("[reflection request"):
            self.reflections = getattr(self, "reflections", 0) + 1
            return LLMResponse(content=self.reflection)
        if "compress agent transcripts" in system:
            return LLMResponse(content="summary")
        m = re.search(r"\(@([a-z0-9_-]+)\)", system)
        name = m.group(1) if m else "?"
        self.calls.append((name, messages))
        self.turns.append({"name": name, "thinking": thinking, "effort": effort})
        script = self.scripts.get(name) or []
        if not script:
            return LLMResponse(content=f"[{name}] done")
        step = script.pop(0)
        if callable(step) and not isinstance(step, dict):
            step = step(messages, tools)
        return _coerce(step)


@pytest.fixture()
def rt(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAND_HOME", str(tmp_path / "home"))
    runtime = Runtime(tmp_path / "home", hitl=ScriptedHITL(default_reply="use defaults"))
    _orig_agent = runtime.agent

    def agent(*a, **kw):  # tests expect reflection to have finished when run() returns
        ag = _orig_agent(*a, **kw)
        ag.settings.background_reflection = False
        return ag

    runtime.agent = agent
    yield runtime
    set_client_override(None)
    runtime.shutdown()
    DB.close_all()


@pytest.fixture()
def script(rt):
    def install(scripts: dict[str, list] | list, **kw):
        if isinstance(scripts, list):
            scripts = {"default": scripts}
        llm = RoutingLLM(scripts, **kw)
        set_client_override(llm)
        return llm

    return install


__all__ = ["RoutingLLM", "ScriptedLLM"]
