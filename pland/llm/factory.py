from __future__ import annotations

import threading
from typing import Callable

from ..config import ModelConfig
from .base import LLMClient
from .openai_compat import OpenAICompatClient

# Tests and the evaluation self-test install an override so that every model call (agent turns,
# reflection, planning) is served by a ScriptedLLM instead of the network.
_override: Callable[[ModelConfig], LLMClient] | None = None
_lock = threading.Lock()


def set_client_override(factory: Callable[[ModelConfig], LLMClient] | None) -> None:
    global _override
    with _lock:
        _override = factory


def make_client(cfg: ModelConfig) -> LLMClient:
    with _lock:
        override = _override
    if override is not None:
        return override(cfg)
    return OpenAICompatClient(cfg)
