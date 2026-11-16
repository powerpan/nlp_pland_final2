"""Deterministic offline LLM used by unit tests and the harness self-test.

It never touches the network. A script is a list of steps; each step is either an `LLMResponse`,
a dict shorthand ({"content": ..., "tool_calls": [(name, args), ...]}), or a callable that
receives (messages, tools) and returns one of those.
"""

from __future__ import annotations

import itertools
import json
import threading
from typing import Any, Callable

from .base import LLMResponse, ToolCall, Usage

Step = LLMResponse | dict | Callable[[list[dict], list[dict] | None], Any]

_ids = itertools.count(1)


def _coerce(step: Any) -> LLMResponse:
    if isinstance(step, LLMResponse):
        return step
    if isinstance(step, str):
        return LLMResponse(content=step)
    if isinstance(step, dict):
        calls = []
        for item in step.get("tool_calls", []):
            name, args = item
            calls.append(ToolCall(id=f"call_{next(_ids)}", name=name, arguments=json.dumps(args, ensure_ascii=False)))
        return LLMResponse(content=step.get("content", ""), tool_calls=calls, usage=Usage(10, 5))
    raise TypeError(f"unsupported scripted step: {step!r}")


class ScriptedLLM:
    provider = "scripted"

    def __init__(self, steps: list[Step] | Callable | None = None, *, model: str = "scripted", default: Step | None = "OK"):
        self.model = model
        self._steps = list(steps) if isinstance(steps, list) else []
        self._fn = steps if callable(steps) else None
        self._default = default
        self._lock = threading.Lock()
        self.requests: list[dict[str, Any]] = []
        self.total_usage = Usage()
        self.calls = 0

    def chat(self, messages, tools=None, *, json_mode=False, max_tokens=None) -> LLMResponse:
        with self._lock:
            self.requests.append({"messages": [dict(m) for m in messages], "tools": tools, "json_mode": json_mode})
            self.calls += 1
            if self._fn is not None:
                step = self._fn(messages, tools)
            elif self._steps:
                step = self._steps.pop(0)
            else:
                step = self._default
        if callable(step) and not isinstance(step, (dict, LLMResponse)):
            step = step(messages, tools)
        resp = _coerce(step)
        self.total_usage.add(resp.usage)
        return resp
