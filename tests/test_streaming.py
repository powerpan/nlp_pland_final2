"""Streaming chat completions (SSE) against a mocked DeepSeek endpoint — no network."""

from __future__ import annotations

import json

import httpx
import pytest

from pland.config import ModelConfig
from pland.llm.base import LLMError
from pland.llm.openai_compat import OpenAICompatClient


def sse(chunks: list[dict]) -> bytes:
    return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def client(handler) -> OpenAICompatClient:
    cfg = ModelConfig(provider="deepseek", api_key="test-key", max_retries=2)
    return OpenAICompatClient(cfg, transport=httpx.MockTransport(handler))


def test_stream_assembles_content_reasoning_and_tool_calls(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    chunks = [
        {"model": "deepseek-flash", "choices": [{"delta": {"reasoning_content": "think "}}]},
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "write_", "arguments": '{"pa'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "file", "arguments": 'th": "a.txt"}'}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 7, "prompt_cache_hit_tokens": 64}},
    ]
    seen_payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(json.loads(request.content))
        return httpx.Response(200, content=sse(chunks), headers={"content-type": "text/event-stream"})

    deltas = []
    resp = client(handler).chat([{"role": "user", "content": "hi"}], [{"type": "function", "function": {"name": "write_file"}}],
                                on_delta=lambda kind, text: deltas.append((kind, text)))
    assert seen_payloads[0]["stream"] is True and seen_payloads[0]["stream_options"] == {"include_usage": True}
    assert resp.content == "Hello" and resp.reasoning_content == "think "
    assert resp.tool_calls[0].name == "write_file" and resp.tool_calls[0].parsed_arguments() == {"path": "a.txt"}
    assert resp.finish_reason == "tool_calls" and resp.usage.prompt_tokens == 100 and resp.usage.cached_tokens == 64
    assert deltas == [("reasoning", "think "), ("content", "Hel"), ("content", "lo")]


def test_stream_retries_only_before_output(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(503, content=b"busy")
        return httpx.Response(200, content=sse([{"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}]))

    resp = client(handler).chat([{"role": "user", "content": "hi"}], on_delta=lambda k, t: None)
    assert resp.content == "ok" and attempts["n"] == 2

    def bad(request):
        return httpx.Response(401, content=b'{"error": {"message": "bad key"}}')

    with pytest.raises(LLMError):
        client(bad).chat([{"role": "user", "content": "hi"}], on_delta=lambda k, t: None)


def test_agent_publishes_deltas(rt, script):
    from pland.llm.base import LLMResponse

    llm = script([{"content": "final answer"}])
    orig = llm.chat

    def chat(messages, tools=None, on_delta=None, **kw):
        resp = orig(messages, tools, **kw)
        if on_delta and resp.content:
            for piece in (resp.content[:5], resp.content[5:]):
                on_delta("content", piece)
        return resp

    llm.chat = chat
    events = []
    rt.bus.subscribe(lambda e: events.append(e) if e["type"] == "assistant.delta" else None)
    rt.agent("default").run("hi")
    assert "".join(e["text"] for e in events) == "final answer"
    assert isinstance(LLMResponse(), LLMResponse)
