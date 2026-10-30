from app.schemas import EventIn
from app.services.events import MAX_ERROR_MESSAGE_CHARS, _error_message


def test_long_error_messages_are_capped_when_stored():
    event = EventIn(provider="openai", status="error", error={"type": "APIError", "message": "a" * 10_000})

    assert len(_error_message(event)) == MAX_ERROR_MESSAGE_CHARS


def test_events_without_an_error_message_store_none():
    assert _error_message(EventIn(provider="openai", status="success")) is None
    assert _error_message(EventIn(provider="openai", status="error", error={"type": "APIError"})) is None
