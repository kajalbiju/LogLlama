from decimal import Decimal
from typing import Any


MODEL_PRICING_PER_1M_TOKENS: dict[str, tuple[Decimal, Decimal]] = {
    "gpt-4o": (Decimal("2.50"), Decimal("10.00")),
    "gpt-4o-mini": (Decimal("0.15"), Decimal("0.60")),
    "gpt-4.1": (Decimal("2.00"), Decimal("8.00")),
    "gpt-4.1-mini": (Decimal("0.40"), Decimal("1.60")),
    "gpt-4.1-nano": (Decimal("0.10"), Decimal("0.40")),
    "gpt-5-nano": (Decimal("0.05"), Decimal("0.40")),
    "gemini-3.5-flash": (Decimal("1.50"), Decimal("9.00")),
    "gemini-3.5-flash-lite": (Decimal("0.30"), Decimal("2.50")),
}


def estimate_cost_usd(model: str | None, input_tokens: int, output_tokens: int) -> Decimal:
    if not model:
        return Decimal("0")

    normalized_model = model.lower()
    pricing = MODEL_PRICING_PER_1M_TOKENS.get(normalized_model)
    if pricing is None:
        pricing = _versioned_model_pricing(normalized_model)
    if pricing is None:
        return Decimal("0")

    input_price, output_price = pricing
    input_cost = Decimal(input_tokens) * input_price / Decimal(1_000_000)
    output_cost = Decimal(output_tokens) * output_price / Decimal(1_000_000)
    return (input_cost + output_cost).quantize(Decimal("0.00000001"))


def extract_response_usage(response: Any) -> tuple[int, int]:
    if not isinstance(response, dict):
        return (0, 0)
    usage = response.get("usage") or response.get("usage_metadata")
    if not isinstance(usage, dict):
        return (0, 0)

    input_tokens = _first_int(
        usage,
        "input_tokens",
        "prompt_tokens",
        "prompt_token_count",
        "total_input_tokens",
    )
    output_tokens = _first_int(
        usage,
        "output_tokens",
        "completion_tokens",
        "candidates_token_count",
        "total_output_tokens",
    )
    return (input_tokens, output_tokens)


def _versioned_model_pricing(model: str) -> tuple[Decimal, Decimal] | None:
    for known_model, pricing in sorted(MODEL_PRICING_PER_1M_TOKENS.items(), key=lambda item: len(item[0]), reverse=True):
        if model.startswith(f"{known_model}-"):
            return pricing
    return None


def _first_int(payload: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    return 0
