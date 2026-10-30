from decimal import Decimal

import pytest

from app.pricing import estimate_cost_usd, price_for_model


@pytest.mark.parametrize(
    "model",
    [
        "claude-sonnet-5-5",
        "claude-sonnet-4-5-20250929",
        "claude-opus-5-5",
        "claude-haiku-5-5",
        "claude-haiku-4-5",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite-preview-09-2025",
        "gemini-2.5-pro",
        "gemini-3.1-pro-preview-customtools",
        "gpt-4o-mini-2024-07-18",
    ],
)
def test_common_models_have_a_price(model):
    assert price_for_model(model) is not None


def test_longest_prefix_wins():
    assert price_for_model("gemini-2.5-flash-lite-preview").input_per_million == Decimal("0.10")
    assert price_for_model("gemini-2.5-flash").input_per_million == Decimal("0.30")
    assert price_for_model("gpt-4o-mini-2024-07-18").input_per_million == Decimal("0.15")


def test_claude_cost_uses_input_and_output_rates():
    # 1,000 input tokens at $2/M plus 500 output tokens at $10/M.
    assert estimate_cost_usd("claude-sonnet-5-5", 1000, 500) == Decimal("0.00700000")


def test_gemini_cost_is_estimated_from_text_rates():
    # 1,000,000 input tokens at $0.30/M plus 1,000,000 output tokens at $2.50/M.
    assert estimate_cost_usd("gemini-2.5-flash", 1_000_000, 1_000_000) == Decimal("2.80000000")


def test_tiered_models_switch_rates_above_the_threshold():
    short = estimate_cost_usd("gemini-2.5-pro", 200_000, 0)
    long = estimate_cost_usd("gemini-2.5-pro", 200_001, 0)
    assert short == Decimal("0.25000000")
    assert long == (Decimal(200_001) * Decimal("2.50") / Decimal(1_000_000)).quantize(Decimal("0.00000001"))


def test_haiku_5_5_tier_applies_above_100k_prompt_tokens():
    assert estimate_cost_usd("claude-haiku-5-5", 100_000, 0) == Decimal("0.01000000")
    assert estimate_cost_usd("claude-haiku-5-5", 100_001, 0) == Decimal("0.05000050")


@pytest.mark.parametrize(
    "model",
    [
        None,
        "",
        "claude-mystery-9",
        "gemini-2.5-flash-image",
        "gemini-2.5-flash-native-audio-preview",
        "gemini-3.1-flash-live-preview",
        "gpt-4o-audio-preview",
    ],
)
def test_unpriced_models_return_none_instead_of_zero(model):
    assert estimate_cost_usd(model, 1000, 1000) is None
