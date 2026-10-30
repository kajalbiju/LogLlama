from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from logllama.client import EventTransport, _PermanentSendError, _RetryableSendError


def make_transport(sender, **overrides: Any) -> EventTransport:
    options: dict[str, Any] = {
        "endpoint": "http://unused.invalid",
        "api_key": "llm_test",
        "timeout_seconds": 1.0,
        "max_queue_size": 100,
        "batch_size": 50,
        "flush_interval_seconds": 60.0,
        "sender": sender,
        "retry_backoff_seconds": 0.0,
    }
    options.update(overrides)
    return EventTransport(**options)


def test_events_are_sent_in_batches_of_the_configured_size():
    bodies: list[dict[str, Any]] = []
    transport = make_transport(lambda body: bodies.append(json.loads(body)), batch_size=2)

    for index in range(5):
        assert transport.submit({"n": index}) is True
    assert transport.flush(timeout=5) is True

    assert [len(body["events"]) for body in bodies] == [2, 2, 1]
    assert transport.stats()["sent"] == 5
    assert transport.shutdown(timeout=5) is True


def test_full_queue_drops_new_events_and_counts_them():
    transport = make_transport(lambda body: None, max_queue_size=2, batch_size=10)

    accepted = [transport.submit({"n": index}) for index in range(3)]

    assert accepted == [True, True, False]
    assert transport.stats()["dropped"] == 1
    assert transport.flush(timeout=5) is True
    assert transport.stats()["sent"] == 2
    transport.shutdown(timeout=5)


def test_retryable_failures_are_retried_until_delivered():
    attempts: list[int] = []

    def flaky_sender(body: bytes) -> None:
        attempts.append(1)
        if len(attempts) < 3:
            raise _RetryableSendError("HTTP 503")

    transport = make_transport(flaky_sender, batch_size=1)
    transport.submit({"n": 1})

    assert transport.flush(timeout=5) is True
    assert len(attempts) == 3
    assert transport.stats()["sent"] == 1
    transport.shutdown(timeout=5)


def test_permanent_failures_are_dropped_without_retrying():
    attempts: list[int] = []

    def rejecting_sender(body: bytes) -> None:
        attempts.append(1)
        raise _PermanentSendError("HTTP 422")

    transport = make_transport(rejecting_sender, batch_size=1)
    transport.submit({"n": 1})

    assert transport.flush(timeout=5) is True
    assert len(attempts) == 1
    assert transport.stats()["failed"] == 1
    transport.shutdown(timeout=5)


def test_batches_are_abandoned_after_the_retry_limit():
    attempts: list[int] = []

    def unavailable_sender(body: bytes) -> None:
        attempts.append(1)
        raise _RetryableSendError("connection refused")

    transport = make_transport(unavailable_sender, batch_size=1, max_attempts=3)
    transport.submit({"n": 1})

    assert transport.flush(timeout=5) is True
    assert len(attempts) == 3
    assert transport.stats()["failed"] == 1
    transport.shutdown(timeout=5)


def test_submit_after_shutdown_is_refused():
    transport = make_transport(lambda body: None)

    assert transport.shutdown(timeout=5) is True
    assert transport.submit({"n": 1}) is False


def test_http_sender_posts_batches_with_the_api_key_header():
    received: list[tuple[str, str | None, dict[str, Any]]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers["Content-Length"])
            payload = json.loads(self.rfile.read(length))
            received.append((self.path, self.headers.get("X-LogLlama-Api-Key"), payload))
            self.send_response(202)
            self.end_headers()

        def log_message(self, *args: Any) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        transport = EventTransport(
            endpoint=f"http://127.0.0.1:{server.server_port}/",
            api_key="llm_test",
            timeout_seconds=2,
            max_queue_size=10,
            batch_size=2,
            flush_interval_seconds=60,
        )
        transport.submit({"external_id": "a"})
        transport.submit({"external_id": "b"})
        assert transport.flush(timeout=5) is True
        assert transport.shutdown(timeout=5) is True
    finally:
        server.shutdown()
        server.server_close()

    assert received == [
        ("/v1/events/batch", "llm_test", {"events": [{"external_id": "a"}, {"external_id": "b"}]}),
    ]
