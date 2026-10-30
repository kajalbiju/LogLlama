from __future__ import annotations

import atexit
import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable
from urllib import error, request

from .config import LogLlamaConfig


logger = logging.getLogger("logllama")

MAX_SEND_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 0.25
USER_AGENT = "logllama-python/0.1.0"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def monotonic_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))


def safe_json(value: Any) -> Any:
    if isinstance(value, Enum):
        return safe_json(value.value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [safe_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): safe_json(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        return safe_json(value.model_dump())
    if hasattr(value, "dict"):
        return safe_json(value.dict())
    return repr(value)


class _RetryableSendError(Exception):
    """Network errors, timeouts, 429, and 5xx responses. The batch is retried."""


class _PermanentSendError(Exception):
    """4xx responses other than 429. Retrying the same batch cannot succeed, so it is dropped."""


SendFunction = Callable[[bytes], None]


def _http_sender(endpoint: str, api_key: str, timeout_seconds: float) -> SendFunction:
    url = endpoint.rstrip("/") + "/v1/events/batch"

    def send(body: bytes) -> None:
        req = request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-LogLlama-Api-Key": api_key,
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:
                response.read()
        except error.HTTPError as exc:
            if exc.code == 429 or exc.code >= 500:
                raise _RetryableSendError(f"HTTP {exc.code}") from exc
            raise _PermanentSendError(f"HTTP {exc.code}") from exc
        except (error.URLError, OSError) as exc:
            raise _RetryableSendError(str(exc)) from exc

    return send


class EventTransport:
    """Bounded in-memory queue drained by one background thread, which sends events in batches."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        timeout_seconds: float,
        max_queue_size: int,
        batch_size: int,
        flush_interval_seconds: float,
        sender: SendFunction | None = None,
        max_attempts: int = MAX_SEND_ATTEMPTS,
        retry_backoff_seconds: float = RETRY_BACKOFF_SECONDS,
    ) -> None:
        self._max_queue_size = max(1, max_queue_size)
        self._batch_size = max(1, batch_size)
        self._flush_interval = max(0.0, flush_interval_seconds)
        self._max_attempts = max(1, max_attempts)
        self._retry_backoff = max(0.0, retry_backoff_seconds)
        self._send = sender or _http_sender(endpoint, api_key, timeout_seconds)

        self._condition = threading.Condition()
        self._queue: deque[dict[str, Any]] = deque()
        self._in_flight = 0
        self._flush_requested = False
        self._closed = False
        self._counts = {"queued": 0, "sent": 0, "dropped": 0, "failed": 0}
        self._thread = threading.Thread(target=self._run, name="logllama-transport", daemon=True)
        self._thread.start()

    def submit(self, event: dict[str, Any]) -> bool:
        with self._condition:
            if self._closed:
                return False
            if len(self._queue) >= self._max_queue_size:
                self._counts["dropped"] += 1
                return False
            self._queue.append(event)
            self._counts["queued"] += 1
            self._condition.notify_all()
            return True

    def flush(self, timeout: float = 5.0) -> bool:
        """Block until everything queued before the call has been delivered or dropped, or the timeout expires."""
        deadline = time.monotonic() + timeout
        with self._condition:
            if not self._queue and not self._in_flight:
                return True
            self._flush_requested = True
            self._condition.notify_all()
            while self._queue or self._in_flight:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            self._flush_requested = False
            return True

    def shutdown(self, timeout: float = 5.0) -> bool:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def stats(self) -> dict[str, int]:
        with self._condition:
            return {**self._counts, "pending": len(self._queue) + self._in_flight}

    def _run(self) -> None:
        while True:
            batch = self._next_batch()
            if batch is None:
                return
            self._deliver(batch)

    def _next_batch(self) -> list[dict[str, Any]] | None:
        with self._condition:
            while not self._queue:
                if self._closed:
                    return None
                self._condition.wait()

            deadline = time.monotonic() + self._flush_interval
            while len(self._queue) < self._batch_size and not self._flush_requested and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)

            count = min(len(self._queue), self._batch_size)
            batch = [self._queue.popleft() for _ in range(count)]
            self._in_flight = len(batch)
            if not self._queue:
                self._flush_requested = False
            return batch

    def _deliver(self, batch: list[dict[str, Any]]) -> None:
        delivered = False
        try:
            body = json.dumps({"events": batch}, default=str).encode("utf-8")
        except (TypeError, ValueError) as exc:
            logger.warning("LogLlama dropped a batch of %d events that could not be serialized: %s", len(batch), exc)
        else:
            delivered = self._send_with_retries(body, len(batch))

        with self._condition:
            self._counts["sent" if delivered else "failed"] += len(batch)
            self._in_flight = 0
            self._condition.notify_all()

    def _send_with_retries(self, body: bytes, event_count: int) -> bool:
        for attempt in range(self._max_attempts):
            try:
                self._send(body)
                return True
            except _PermanentSendError as exc:
                logger.warning("LogLlama could not deliver %d events: %s", event_count, exc)
                return False
            except _RetryableSendError as exc:
                if attempt + 1 < self._max_attempts and self._retry_backoff:
                    time.sleep(self._retry_backoff * (2**attempt))
                last_error = exc
        logger.warning("LogLlama could not deliver %d events after %d attempts: %s", event_count, self._max_attempts, last_error)
        return False


_registry_lock = threading.Lock()
_transports: dict[tuple[int, str, str], EventTransport] = {}


def _transport_for(config: LogLlamaConfig) -> EventTransport:
    # Keyed by process ID so that forked children never reuse a transport whose thread did not survive the fork.
    key = (os.getpid(), config.endpoint.rstrip("/"), config.api_key or "")
    with _registry_lock:
        transport = _transports.get(key)
        if transport is None:
            transport = EventTransport(
                endpoint=config.endpoint,
                api_key=config.api_key or "",
                timeout_seconds=config.timeout_seconds,
                max_queue_size=config.max_queue_size,
                batch_size=config.batch_size,
                flush_interval_seconds=config.flush_interval_seconds,
            )
            _transports[key] = transport
        return transport


def _current_process_transports() -> list[EventTransport]:
    pid = os.getpid()
    with _registry_lock:
        return [transport for (owner_pid, _, _), transport in _transports.items() if owner_pid == pid]


def post_event_async(config: LogLlamaConfig, event: dict[str, Any]) -> None:
    if not config.enabled or not config.api_key:
        return
    _transport_for(config).submit(event)


def flush(timeout: float = 5.0) -> bool:
    """Deliver queued events. Returns False if anything was still pending when the timeout expired."""
    deadline = time.monotonic() + timeout
    delivered = True
    for transport in _current_process_transports():
        delivered = transport.flush(max(0.0, deadline - time.monotonic())) and delivered
    return delivered


def shutdown(timeout: float = 5.0) -> bool:
    """Stop the background senders after draining the queue. Later events are dropped."""
    deadline = time.monotonic() + timeout
    stopped = True
    for transport in _current_process_transports():
        stopped = transport.shutdown(max(0.0, deadline - time.monotonic())) and stopped
    return stopped


def transport_stats() -> dict[str, int]:
    totals = {"queued": 0, "sent": 0, "dropped": 0, "failed": 0, "pending": 0}
    for transport in _current_process_transports():
        for name, value in transport.stats().items():
            totals[name] = totals.get(name, 0) + value
    return totals


@atexit.register
def _flush_at_exit() -> None:
    flush(timeout=5.0)


def new_external_id() -> str:
    return f"llreq_{uuid.uuid4().hex}"
