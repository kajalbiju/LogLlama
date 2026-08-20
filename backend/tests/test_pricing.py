from decimal import Decimal

from app.pricing import estimate_cost_usd, extract_response_usage


def test_estimates_gemini_35_flash_lite_cost():
    assert estimate_cost_usd("gemini-3.5-flash-lite", 6, 1) == Decimal("0.00000430")


def test_estimates_versioned_gemini_35_flash_lite_cost():
    assert estimate_cost_usd("gemini-3.5-flash-lite-2026-07-23", 6, 1) == Decimal(
        "0.00000430"
    )


def test_extracts_gemini_interactions_usage():
    response = {
        "usage": {
            "total_input_tokens": 6,
            "total_output_tokens": 1,
            "total_tokens": 7,
        }
    }

    assert extract_response_usage(response) == (6, 1)
