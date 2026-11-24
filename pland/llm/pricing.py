"""Price table for cost estimates (USD per 1M tokens, DeepSeek list prices at peak hours — off-peak
is half). Source: https://api-docs.deepseek.com/quick_start/pricing (checked 2026-10-21)."""

from __future__ import annotations

PRICES: dict[str, tuple[float, float, float]] = {
    # model: (input cache hit, input cache miss, output)
    "deepseek-flash": (0.006, 0.30, 1.20),
    "deepseek-v4-flash": (0.006, 0.30, 1.20),
    "deepseek-v4-pro": (0.044, 1.32, 3.96),
}
DEFAULT = PRICES["deepseek-flash"]


def price_for(model: str | None) -> tuple[float, float, float]:
    if not model:
        return DEFAULT
    m = model.lower()
    for name, price in PRICES.items():
        if m == name or m.startswith(name):
            return price
    if "pro" in m:
        return PRICES["deepseek-v4-pro"]
    return DEFAULT


def cost(prompt_tokens: int, cached_tokens: int, completion_tokens: int, model: str | None = None) -> float:
    hit, miss, out = price_for(model)
    misses = max(0, prompt_tokens - cached_tokens)
    return (cached_tokens * hit + misses * miss + completion_tokens * out) / 1_000_000
