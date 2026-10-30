from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache


# Public list prices in USD per 1M tokens, checked against the vendor pricing pages on 2026-10-26.
# Cache, batch, priority, and regional pricing are not modeled, so costs are estimates.
PRICING_AS_OF = "2026-10-26"

# Models whose billing includes non-token units (audio, image, live sessions) are left unpriced
# instead of being estimated from text tokens.
UNPRICED_MARKERS = (
    "audio",
    "embedding",
    "image",
    "imagen",
    "live",
    "robotics",
    "transcribe",
    "tts",
    "veo",
)


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input_per_million: Decimal
    output_per_million: Decimal
    # Some providers charge a higher rate when the prompt exceeds a token threshold.
    long_prompt_threshold: int | None = None
    long_input_per_million: Decimal | None = None
    long_output_per_million: Decimal | None = None


def _price(input_rate: str, output_rate: str) -> ModelPrice:
    return ModelPrice(Decimal(input_rate), Decimal(output_rate))


def _tiered(
    input_rate: str,
    output_rate: str,
    threshold: int,
    long_input_rate: str,
    long_output_rate: str,
) -> ModelPrice:
    return ModelPrice(
        Decimal(input_rate),
        Decimal(output_rate),
        long_prompt_threshold=threshold,
        long_input_per_million=Decimal(long_input_rate),
        long_output_per_million=Decimal(long_output_rate),
    )


# Keys are model-ID prefixes. Dated snapshots such as "claude-sonnet-4-5-20250929" match the
# longest key followed by a hyphen.
MODEL_PRICING_PER_1M_TOKENS: dict[str, ModelPrice] = {
    # OpenAI (not re-verified in this pass)
    "gpt-4o": _price("2.50", "10.00"),
    "gpt-4o-mini": _price("0.15", "0.60"),
    "gpt-4.1": _price("2.00", "8.00"),
    "gpt-4.1-mini": _price("0.40", "1.60"),
    "gpt-4.1-nano": _price("0.10", "0.40"),
    "gpt-5-nano": _price("0.05", "0.40"),
    # Anthropic
    "claude-fable-5-1": _price("10", "50"),
    "claude-fable-5": _price("10", "50"),
    "claude-opus-5-5": _price("4", "20"),
    "claude-opus-5": _price("5", "25"),
    "claude-opus-4-8": _price("5", "25"),
    "claude-opus-4-7": _price("5", "25"),
    "claude-opus-4-6": _price("5", "25"),
    "claude-opus-4-5": _price("5", "25"),
    "claude-sonnet-5-5": _price("2", "10"),
    "claude-sonnet-5": _price("2", "10"),
    "claude-sonnet-4-6": _price("3", "15"),
    "claude-sonnet-4-5": _price("3", "15"),
    "claude-haiku-5-5": _tiered("0.10", "0.50", 100_000, "0.50", "2.50"),
    "claude-haiku-4-5": _price("1", "5"),
    # Gemini (text, image, and video token rates)
    "gemini-4-argon": _price("2.00", "10.00"),
    "gemini-3.8-flash": _price("0.75", "3.75"),
    "gemini-3.6-flash": _price("0.75", "3.75"),
    "gemini-3.5-flash-lite": _price("0.30", "2.50"),
    "gemini-3.1-pro-preview": _tiered("2.00", "12.00", 200_000, "4.00", "18.00"),
    "gemini-3.1-flash-lite": _price("0.25", "1.50"),
    "gemini-3-flash-preview": _price("0.50", "3.00"),
    "gemini-2.5-pro": _tiered("1.25", "10.00", 200_000, "2.50", "15.00"),
    "gemini-2.5-flash-lite": _price("0.10", "0.40"),
    "gemini-2.5-flash": _price("0.30", "2.50"),
}


@lru_cache(maxsize=1024)
def price_for_model(model: str | None) -> ModelPrice | None:
    if not model:
        return None

    normalized = model.strip().lower()
    if any(marker in normalized for marker in UNPRICED_MARKERS):
        return None
    if normalized in MODEL_PRICING_PER_1M_TOKENS:
        return MODEL_PRICING_PER_1M_TOKENS[normalized]

    for known_model in sorted(MODEL_PRICING_PER_1M_TOKENS, key=len, reverse=True):
        if normalized.startswith(f"{known_model}-"):
            return MODEL_PRICING_PER_1M_TOKENS[known_model]
    return None


def estimate_cost_usd(model: str | None, input_tokens: int, output_tokens: int) -> Decimal | None:
    """Return the estimated cost in USD, or None when the model has no published text-token price."""
    price = price_for_model(model)
    if price is None:
        return None

    input_rate = price.input_per_million
    output_rate = price.output_per_million
    if price.long_prompt_threshold is not None and input_tokens > price.long_prompt_threshold:
        input_rate = price.long_input_per_million or input_rate
        output_rate = price.long_output_per_million or output_rate

    input_cost = Decimal(input_tokens) * input_rate / Decimal(1_000_000)
    output_cost = Decimal(output_tokens) * output_rate / Decimal(1_000_000)
    return (input_cost + output_cost).quantize(Decimal("0.00000001"))
