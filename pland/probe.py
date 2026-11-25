"""Capability probe against the real model API (`pland doctor --probe`).

A handful of small calls: plain chat, native tool call, tool call with thinking mode (including the
reasoning replay on the follow-up turn), thinking intensity, JSON mode, and the DeepSeek Search/Fetch tools
(DeepSeek's even with HKGAI as the provider, which has none of its own).
"""

from __future__ import annotations

import json
import time

from .config import ModelConfig, default_provider
from .llm.base import Usage
from .llm.openai_compat import OpenAICompatClient

TOOLS = [{"type": "function", "function": {"name": "get_weather", "description": "Get the weather of a city",
                                           "parameters": {"type": "object", "properties": {"city": {"type": "string"}},
                                                          "required": ["city"]}}}]


def run_probe(console) -> bool:
    base = ModelConfig(provider=default_provider())
    total = Usage()
    results = []

    def check(name, fn):
        t0 = time.time()
        try:
            detail = fn()
            results.append((name, True, detail, time.time() - t0))
        except Exception as exc:
            results.append((name, False, f"{type(exc).__name__}: {str(exc)[:200]}", time.time() - t0))

    plain = OpenAICompatClient(base)

    def chat():
        r = plain.chat([{"role": "user", "content": "Reply with exactly: pong"}])
        total.add(r.usage)
        assert "pong" in r.content.lower(), r.content
        return f"{r.content.strip()!r} model={r.model}"

    def tools():
        r = plain.chat([{"role": "user", "content": "What's the weather in Taipei? Use the tool."}], TOOLS)
        total.add(r.usage)
        assert r.tool_calls and r.tool_calls[0].name == "get_weather", r
        return f"get_weather({r.tool_calls[0].arguments})"

    def tools_thinking():
        cfg = ModelConfig(provider=base.provider, thinking=True, reasoning_effort="low")
        c = OpenAICompatClient(cfg)
        msgs = [{"role": "user", "content": "What's the weather in Hong Kong? Use the tool, then answer in one sentence."}]
        r = c.chat(msgs, TOOLS)
        total.add(r.usage)
        assert r.tool_calls, "no tool call"
        msgs.append(r.to_message())
        msgs.append({"role": "tool", "tool_call_id": r.tool_calls[0].id, "content": "Sunny, 27°C"})
        r2 = c.chat(msgs, TOOLS)  # replays reasoning_content
        total.add(r2.usage)
        return f"reasoning={bool(r.reasoning_content)} final={r2.content.strip()[:80]!r}"

    def intensity():
        q = [{"role": "user", "content": "What is 17 * 23? Reply with the number only."}]
        deep = plain.chat(q, thinking=True, effort="max", max_tokens=2000)
        off = plain.chat(q, thinking=False, max_tokens=50)
        total.add(deep.usage)
        total.add(off.usage)
        assert deep.reasoning_content and not off.reasoning_content, "thinking switch not honoured"
        return f"max: {len(deep.reasoning_content)} reasoning chars · off: none · {off.content.strip()!r}"

    def json_mode():
        r = plain.chat([{"role": "user", "content": "Return a JSON object with keys a=1 and b='x'. Output JSON only."}], json_mode=True)
        total.add(r.usage)
        data = json.loads(r.content)
        assert data.get("a") == 1, data
        return r.content.strip()

    def search():
        from .tools.web import _search_deepseek

        res = _search_deepseek("DeepSeek API documentation", 3)
        assert res, "no results"
        return f"{len(res)} results, first: {res[0]['url']}"

    def fetch():
        from .tools.web import _fetch_deepseek

        title, text = _fetch_deepseek("https://example.com/")
        assert "Example Domain" in (title + text)
        return f"title={title!r} chars={len(text)}"

    for name, fn in [("chat", chat), ("tool call", tools), ("tool call + thinking (reasoning replay)", tools_thinking),
                     ("thinking intensity (max / off)", intensity),
                     ("JSON mode", json_mode), ("DeepSeek Search API", search), ("DeepSeek Fetch API", fetch)]:
        check(name, fn)
    for name, ok, detail, dt in results:
        console.print(f"{'[green]✓[/]' if ok else '[red]✗[/]'} {name:<42} {dt:5.1f}s  {detail}")
    console.print(f"usage: {total.prompt_tokens} prompt ({total.cached_tokens} cached) + {total.completion_tokens} completion "
                  f"≈ ${total.cost_usd:.4f}")
    return all(ok for _, ok, _, _ in results)
