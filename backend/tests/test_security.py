import hashlib

import pytest

from app.security import (
    display_prefix,
    hash_password,
    hash_token,
    is_valid_email,
    new_api_key,
    normalize_email,
    verify_password,
)


def test_password_hash_round_trips_and_is_salted():
    first = hash_password("a long enough password")
    second = hash_password("a long enough password")

    assert first != second
    assert verify_password("a long enough password", first)
    assert not verify_password("a different password", first)


@pytest.mark.parametrize("stored", ["", "plaintext", "bcrypt$1$2$3$aa$bb", "scrypt$nope"])
def test_malformed_password_hashes_never_verify(stored):
    assert verify_password("anything", stored) is False


def test_api_keys_have_kind_prefixes_and_high_entropy():
    ingest = new_api_key("ingest")
    runtime = new_api_key("runtime")

    assert ingest.startswith("llm_")
    assert runtime.startswith("llrt_")
    assert len(ingest) > 40 and len(runtime) > 40
    assert new_api_key("ingest") != ingest


def test_stored_token_hash_is_sha256_of_the_plaintext():
    raw = "llm_example-token"
    assert hash_token(raw) == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert display_prefix(raw) == "llm_exam"


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ("user@example.com", True),
        ("first.last+tag@sub.example.org", True),
        ("no-at-sign.example.com", False),
        ("two@@example.com", False),
        ("spaces in@example.com", False),
    ],
)
def test_email_validation(value, valid):
    assert is_valid_email(normalize_email(value)) is valid


def test_email_is_normalized_to_lowercase():
    assert normalize_email("  User@Example.COM ") == "user@example.com"
