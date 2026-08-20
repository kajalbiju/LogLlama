from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib import error

import pytest

import logllama.client as delivery
from logllama.config import LogLlamaConfig


@pytest.fixture(autouse=True)
def reset_delivery_dispatchers():
    delivery._reset_delivery_for_tests()
    yield
    delivery._reset_delivery_for_tests()


def config(**overrides: Any) -> LogLlamaConfig:
    values = {
        "api_key": "test-key",
        "endpoint": "http://logllama.test",
        "timeout_seconds": 0.1,
        "delivery_queue_size": 10,
        "delivery_batch_size": 3,
        "delivery_flush_interval_seconds": 0.02,
        "delivery_max_attempts": 1,
        "delivery_retry_backoff_seconds": 0.01,
    }
    values.update(overrides)
    return LogLlamaConfig(**values)


def test_events_are_coalesced_into_one_bounded_batch(monkeypatch):
    batches: list[list[dict[str, Any]]] = []
    monkeypatch.setattr(
        delivery,
        "_send_batch",
        lambda _config, events: batches.append(events) or True,
    )
    sdk_config = config()

    for index in range(3):
        assert delivery.post_event_async(sdk_config, {"external_id": str(index)})

    assert delivery.flush(1.0)
    assert [[event["external_id"] for event in batch] for batch in batches] == [
        ["0", "1", "2"]
    ]
    stats = delivery.delivery_stats()
    assert stats["accepted"] == 3
    assert stats["delivered"] == 3
    assert stats["dropped"] == 0
    assert len(stats["dispatchers"]) == 1


def test_delivery_retries_batch_before_persisting(monkeypatch):
    attempts = 0

    def send(_config, _events):
        nonlocal attempts
        attempts += 1
        return attempts == 3

    monkeypatch.setattr(delivery, "_send_batch", send)
    sdk_config = config(delivery_max_attempts=3)

    assert delivery.post_event_async(sdk_config, {"external_id": "retry-me"})
    assert delivery.flush(1.0)

    assert attempts == 3
    assert delivery.delivery_stats()["delivered"] == 1


def test_batch_endpoint_falls_back_to_single_event_on_404(monkeypatch):
    urls: list[str] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def urlopen(req, **_kwargs):
        urls.append(req.full_url)
        if req.full_url.endswith("/batch"):
            raise error.HTTPError(req.full_url, 404, "not found", {}, None)
        return Response()

    monkeypatch.setattr(delivery.request, "urlopen", urlopen)

    assert delivery._send_batch(config(), [{"external_id": "old-backend"}])
    assert urls == [
        "http://logllama.test/v1/events/batch",
        "http://logllama.test/v1/events",
    ]


def test_failed_batch_is_persisted_without_api_key(monkeypatch, tmp_path: Path):
    spool = tmp_path / "delivery.jsonl"
    monkeypatch.setattr(delivery, "_send_batch", lambda _config, _events: False)
    sdk_config = config(delivery_batch_size=1, delivery_spool_path=str(spool))

    assert delivery.post_event_async(
        sdk_config,
        {"external_id": "persist-me", "prompt": "safe payload"},
    )
    assert delivery.flush(1.0)

    payload = spool.read_text(encoding="utf-8")
    assert "persist-me" in payload
    assert "test-key" not in payload
    assert spool.stat().st_mode & 0o777 == 0o600
    stats = delivery.delivery_stats()
    assert stats["persisted"] == 1
    assert stats["spooled"] == 1
    assert stats["dropped"] == 0


def test_spooled_event_is_replayed_before_new_queue_items(monkeypatch, tmp_path: Path):
    spool = tmp_path / "delivery.jsonl"
    spool.write_text(json.dumps({"external_id": "from-disk"}) + "\n", encoding="utf-8")
    batches: list[list[str]] = []

    def capture(_config, events):
        batches.append([event["external_id"] for event in events])
        return True

    monkeypatch.setattr(delivery, "_send_batch", capture)
    sdk_config = config(delivery_spool_path=str(spool))

    assert delivery.post_event_async(sdk_config, {"external_id": "from-memory"})
    assert delivery.flush(1.0)

    assert batches[0] == ["from-disk"]
    assert [item for batch in batches for item in batch] == ["from-disk", "from-memory"]
    assert not spool.exists()


def test_queue_overflow_warns_and_increments_drop_counter(monkeypatch):
    dispatcher = delivery._EventDispatcher(config(delivery_queue_size=1))
    monkeypatch.setattr(dispatcher, "_ensure_worker", lambda: None)

    assert dispatcher.enqueue({"external_id": "accepted"})
    with pytest.warns(RuntimeWarning, match="delivery queue is full"):
        assert not dispatcher.enqueue({"external_id": "dropped"})

    stats = dispatcher.snapshot()
    assert stats["accepted"] == 1
    assert stats["dropped"] == 1
    assert stats["queue_depth"] == 1


def test_worker_caps_batches_at_backend_limit():
    dispatcher = delivery._EventDispatcher(config(delivery_batch_size=250))

    assert dispatcher.batch_size == 100
    assert dispatcher.snapshot()["batch_size"] == 100


def test_delivery_configuration_loads_from_environment(monkeypatch):
    import logllama.config as sdk_config

    monkeypatch.setattr(sdk_config, "_config", LogLlamaConfig())
    monkeypatch.setattr(sdk_config, "_env_loaded", True)
    monkeypatch.setenv("LOGLLAMA_DELIVERY_QUEUE_SIZE", "250")
    monkeypatch.setenv("LOGLLAMA_DELIVERY_BATCH_SIZE", "40")
    monkeypatch.setenv("LOGLLAMA_DELIVERY_FLUSH_INTERVAL_SECONDS", "0.5")
    monkeypatch.setenv("LOGLLAMA_DELIVERY_MAX_ATTEMPTS", "4")
    monkeypatch.setenv("LOGLLAMA_DELIVERY_RETRY_BACKOFF_SECONDS", "0.1")
    monkeypatch.setenv("LOGLLAMA_DELIVERY_SPOOL_PATH", "/tmp/logllama-test.jsonl")

    loaded = sdk_config.config_from_env()

    assert loaded.delivery_queue_size == 250
    assert loaded.delivery_batch_size == 40
    assert loaded.delivery_flush_interval_seconds == 0.5
    assert loaded.delivery_max_attempts == 4
    assert loaded.delivery_retry_backoff_seconds == 0.1
    assert loaded.delivery_spool_path == "/tmp/logllama-test.jsonl"
