"""Chat-completions client for OpenAI-compatible endpoints (DeepSeek, HKGAI).

Implemented directly on httpx so that no third-party SDK can introduce an implicit default
provider or fallback route.
"""

from __future__ import annotations

import json
import random
import threading
import time
from typing import Any

import httpx

from ..config import ModelConfig
from .base import LLMError, LLMResponse, ToolCall, Usage
from .guard import check_endpoint
from .reasoning import PROVIDER_OFF_WORD, parse as _parse, wire_level as _wire_level

# Per the project's DeepSeek guide: retry only transient failures (429, 5xx, timeouts) with 1/2/4 s
# backoff, at most 3 times; 400/401/402/403 fail immediately.
_RETRY_STATUS = {408, 429, 500, 502, 503, 504}
PROVIDER_THINKING = {"deepseek": True, "hkgai": True}  # providers that can think (see pland/llm/reasoning.py)


class _StreamCut(Exception):
    """The stream broke after output had already been delivered; retrying would duplicate it."""


class OpenAICompatClient:
    def __init__(self, cfg: ModelConfig, transport: httpx.BaseTransport | None = None):
        cfg = cfg.resolved()
        check_endpoint(cfg.provider, cfg.base_url)
        if not cfg.api_key:
            raise LLMError(
                f"No API key for provider '{cfg.provider}'. Set it in .env (see .env.example)."
            )
        if not cfg.model:
            raise LLMError(f"No model configured for provider '{cfg.provider}'.")
        self.cfg = cfg
        self.provider = cfg.provider
        self.model = cfg.model
        self._url = cfg.base_url.rstrip("/") + "/chat/completions"
        self._http = httpx.Client(timeout=httpx.Timeout(cfg.timeout, connect=20.0), transport=transport)
        self._lock = threading.Lock()
        self.total_usage = Usage()
        self.calls = 0

    def _payload(self, messages, tools, json_mode, max_tokens, temperature=None, thinking=None,
                 effort=None, tool_choice=None) -> dict[str, Any]:
        cfg = self.cfg
        think = cfg.thinking if thinking is None else (thinking and PROVIDER_THINKING.get(cfg.provider, False))
        if json_mode and cfg.provider == "hkgai":
            think = False  # probed 2026-10-25: with thinking on, HKGAI's JSON mode returned malformed JSON in 2 of 3 calls
        effort =cfg.reasoning_effort if effort is None else _wire_level(_parse(effort), cfg.provider)
        payload: dict[str, Any] = {
            "model": cfg.model,
            "messages": [_clean_message(m, keep_reasoning=bool(tools) and think) for m in messages],
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if max_tokens or cfg.max_tokens:
            payload["max_tokens"] = max_tokens or cfg.max_tokens
        if cfg.provider == "deepseek":
            payload["thinking"] = {"type": "enabled" if think else "disabled"}
            if think and effort:
                payload["reasoning_effort"] = effort
        elif cfg.provider in PROVIDER_OFF_WORD:
            # no thinking switch: the effort alone turns it on (a level) or off (HKGAI: "none", sent explicitly)
            payload["reasoning_effort"] = (effort or _wire_level(None, cfg.provider)) if think else PROVIDER_OFF_WORD[cfg.provider]
        temp = cfg.temperature if temperature is None else temperature
        if not think and temp is not None:
            payload["temperature"] = temp
        return payload

    def chat(self, messages, tools=None, *, json_mode=False, max_tokens=None, temperature=None,
             on_delta=None, thinking=None, effort=None, tool_choice=None) -> LLMResponse:
        """One chat completion. With `on_delta(kind, text)` the response is streamed and each content /
        reasoning fragment is passed on as it arrives (kind = "content" | "reasoning"); the return value
        is the same assembled LLMResponse either way. `thinking` / `effort` override the configured
        thinking switch and intensity for this call only; `tool_choice="none"` shows the tools but allows no call."""
        payload = self._payload(messages, tools, json_mode, max_tokens, temperature, thinking, effort, tool_choice)
        if on_delta is not None:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        headers = {"Authorization": f"Bearer {self.cfg.api_key}", "Content-Type": "application/json"}
        last_err: Exception | None = None
        for attempt in range(self.cfg.max_retries + 1):
            try:
                if on_delta is None:
                    resp = self._http.post(self._url, headers=headers, content=json.dumps(payload))
                    if resp.status_code == 200:
                        return self._parse(resp.json())
                    status, body = resp.status_code, resp.text[:800]
                else:
                    with self._http.stream("POST", self._url, headers=headers, content=json.dumps(payload)) as resp:
                        if resp.status_code == 200:
                            return self._consume_stream(resp, on_delta)
                        status, body = resp.status_code, resp.read().decode("utf-8", "replace")[:800]
            except _StreamCut as exc:
                # The connection dropped after output had started. Retry the whole request (transient network
                # failures are common on long streams); listeners are told to discard the partial text.
                last_err = LLMError(f"stream from {self.provider} broke mid-response: {exc}", retryable=True)
                on_delta("reset", "")
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_err = LLMError(f"network error talking to {self.provider}: {exc}", retryable=True)
            else:
                retryable = status in _RETRY_STATUS
                last_err = LLMError(f"{self.provider} HTTP {status}: {body}", status=status, retryable=retryable)
                if not retryable:
                    raise last_err
            if attempt < self.cfg.max_retries:
                time.sleep((2 ** attempt) + random.random() * 0.25)
        assert last_err is not None
        raise last_err

    def _consume_stream(self, resp: httpx.Response, on_delta) -> LLMResponse:
        """Assemble a streamed (SSE) completion: content, reasoning_content and tool-call fragments
        (keyed by index) arrive as deltas; usage comes in the final chunk."""
        content: list[str] = []
        reasoning: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        finish = model = None
        usage: dict[str, Any] = {}
        emitted = False
        try:
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                model = chunk.get("model") or model
                if chunk.get("usage"):
                    usage = chunk["usage"]
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    piece = _reasoning_text(delta)
                    if piece:
                        reasoning.append(piece)
                        on_delta("reasoning", piece)
                        emitted = True
                    if delta.get("content"):
                        content.append(delta["content"])
                        on_delta("content", delta["content"])
                        emitted = True
                    for tc in delta.get("tool_calls") or []:
                        slot = calls.setdefault(int(tc.get("index", len(calls))), {"id": "", "name": "", "arguments": ""})
                        slot["id"] = tc.get("id") or slot["id"]
                        fn = tc.get("function") or {}
                        slot["name"] += fn.get("name") or ""
                        slot["arguments"] += fn.get("arguments") or ""
                    if choice.get("finish_reason"):
                        finish = choice["finish_reason"]
        except (httpx.TransportError, json.JSONDecodeError) as exc:
            if emitted:
                raise _StreamCut(str(exc)) from exc
            raise httpx.TransportError(str(exc)) from exc
        message: dict[str, Any] = {"content": "".join(content)}
        if reasoning:
            message["reasoning_content"] = "".join(reasoning)
        if calls:
            message["tool_calls"] = [{"id": c["id"] or f"call_{i}", "type": "function",
                                      "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}}
                                     for i, c in sorted(calls.items())]
        return self._parse({"choices": [{"message": message, "finish_reason": finish}], "usage": usage, "model": model})

    def _parse(self, data: dict[str, Any]) -> LLMResponse:
        try:
            choice = data["choices"][0]
            msg = choice.get("message") or {}
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"malformed response from {self.provider}: {str(data)[:500]}") from exc
        calls = []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function") or {}
            calls.append(
                ToolCall(id=tc.get("id") or f"call_{i}", name=fn.get("name", ""), arguments=fn.get("arguments") or "{}")
            )
        u = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(u.get("prompt_tokens") or 0),
            completion_tokens=int(u.get("completion_tokens") or 0),
            cached_tokens=int(u.get("prompt_cache_hit_tokens") or (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
        )
        usage.calls = 1
        with self._lock:
            self.total_usage.add(usage)
            self.calls += 1
        return LLMResponse(
            content=msg.get("content") or "",
            reasoning_content=_reasoning_text(msg) or None,
            tool_calls=calls,
            finish_reason=choice.get("finish_reason"),
            usage=usage,
            model=data.get("model"),
        )


_ALLOWED_KEYS = {"role", "content", "tool_calls", "tool_call_id", "name", "reasoning_content"}


def _reasoning_text(part: dict[str, Any]) -> str:
    """Reasoning from a message or stream delta: DeepSeek calls it `reasoning_content`, HKGAI `reasoning`."""
    text = part.get("reasoning_content") or part.get("reasoning")
    return text if isinstance(text, str) else ""


def _clean_message(msg: dict[str, Any], *, keep_reasoning: bool) -> dict[str, Any]:
    out = {k: v for k, v in msg.items() if k in _ALLOWED_KEYS}
    if not keep_reasoning:
        out.pop("reasoning_content", None)
    if out.get("role") == "assistant" and out.get("tool_calls") and not out.get("content"):
        out["content"] = ""
    if out.get("content") is None:
        out["content"] = ""
    return out
