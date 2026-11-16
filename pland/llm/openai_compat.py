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

_RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}


class OpenAICompatClient:
    def __init__(self, cfg: ModelConfig):
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
        self._http = httpx.Client(timeout=httpx.Timeout(cfg.timeout, connect=20.0))
        self._lock = threading.Lock()
        self.total_usage = Usage()
        self.calls = 0

    def _payload(self, messages, tools, json_mode, max_tokens) -> dict[str, Any]:
        cfg = self.cfg
        payload: dict[str, Any] = {
            "model": cfg.model,
            "messages": [_clean_message(m, keep_reasoning=bool(tools) and cfg.thinking) for m in messages],
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if max_tokens or cfg.max_tokens:
            payload["max_tokens"] = max_tokens or cfg.max_tokens
        if cfg.provider == "deepseek":
            payload["thinking"] = {"type": "enabled" if cfg.thinking else "disabled"}
            if cfg.thinking and cfg.reasoning_effort:
                payload["reasoning_effort"] = cfg.reasoning_effort
        if cfg.temperature is not None and not cfg.thinking:
            payload["temperature"] = cfg.temperature
        return payload

    def chat(self, messages, tools=None, *, json_mode=False, max_tokens=None) -> LLMResponse:
        payload = self._payload(messages, tools, json_mode, max_tokens)
        headers = {"Authorization": f"Bearer {self.cfg.api_key}", "Content-Type": "application/json"}
        last_err: Exception | None = None
        for attempt in range(self.cfg.max_retries + 1):
            try:
                resp = self._http.post(self._url, headers=headers, content=json.dumps(payload))
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_err = LLMError(f"network error talking to {self.provider}: {exc}", retryable=True)
            else:
                if resp.status_code == 200:
                    return self._parse(resp.json())
                body = resp.text[:800]
                retryable = resp.status_code in _RETRY_STATUS
                last_err = LLMError(
                    f"{self.provider} HTTP {resp.status_code}: {body}", status=resp.status_code, retryable=retryable
                )
                if not retryable:
                    raise last_err
            if attempt < self.cfg.max_retries:
                time.sleep(min(30.0, (2 ** attempt) + random.random()))
        assert last_err is not None
        raise last_err

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
        with self._lock:
            self.total_usage.add(usage)
            self.calls += 1
        return LLMResponse(
            content=msg.get("content") or "",
            reasoning_content=msg.get("reasoning_content"),
            tool_calls=calls,
            finish_reason=choice.get("finish_reason"),
            usage=usage,
            model=data.get("model"),
        )


_ALLOWED_KEYS = {"role", "content", "tool_calls", "tool_call_id", "name", "reasoning_content"}


def _clean_message(msg: dict[str, Any], *, keep_reasoning: bool) -> dict[str, Any]:
    out = {k: v for k, v in msg.items() if k in _ALLOWED_KEYS}
    if not keep_reasoning:
        out.pop("reasoning_content", None)
    if out.get("role") == "assistant" and out.get("tool_calls") and not out.get("content"):
        out["content"] = ""
    if out.get("content") is None:
        out["content"] = ""
    return out
