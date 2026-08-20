import pytest
from pydantic import ValidationError

from app.schemas import EventBatchIn, EventIn, ProviderCredentialCreate, TestTarget


def test_event_accepts_provider_observability_fields():
    event = EventIn(
        provider="gemini",
        operation="models.generate_content",
        model="gemini-test",
        provider_request_id="gemini-request-123",
        retry_count=2,
        model_parameters={"temperature": 0.2, "max_output_tokens": 16},
        status="success",
    )

    assert event.provider_request_id == "gemini-request-123"
    assert event.retry_count == 2
    assert event.model_parameters["temperature"] == 0.2


def test_event_rejects_negative_retry_count():
    with pytest.raises(ValidationError):
        EventIn(
            provider="gemini",
            operation="models.generate_content",
            retry_count=-1,
            status="error",
        )


def test_cursor_is_accepted_for_managed_credentials_and_test_targets():
    assert ProviderCredentialCreate(provider="cursor", api_key="c" * 8).provider == "cursor"
    assert TestTarget(provider="cursor", model="composer-test").provider == "cursor"


def test_event_batch_accepts_up_to_one_hundred_events():
    batch = EventBatchIn(events=[EventIn(status="success")] * 100)

    assert len(batch.events) == 100


def test_event_batch_rejects_empty_and_oversized_payloads():
    with pytest.raises(ValidationError):
        EventBatchIn(events=[])

    with pytest.raises(ValidationError):
        EventBatchIn(events=[EventIn(status="success")] * 101)
