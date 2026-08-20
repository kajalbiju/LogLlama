from __future__ import annotations

import atexit
import hashlib
import json
import os
import queue
import threading
import time
import uuid
import warnings
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from urllib import error, request

from .config import LogLlamaConfig


MAX_DELIVERY_BATCH_SIZE = 100


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


class _EventDispatcher:
    def __init__(self, config: LogLlamaConfig):
        self.config = config
        self.batch_size = min(config.delivery_batch_size, MAX_DELIVERY_BATCH_SIZE)
        self.events: queue.Queue[dict[str, Any]] = queue.Queue(
            maxsize=config.delivery_queue_size
        )
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._worker_lock = threading.Lock()
        self._spool_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._next_spool_retry_at = 0.0
        self._warned_drops = 0
        self._stats = {
            "accepted": 0,
            "delivered": 0,
            "persisted": 0,
            "dropped": 0,
            "failed_batches": 0,
        }

    def enqueue(self, event: dict[str, Any]) -> bool:
        self._ensure_worker()
        try:
            self.events.put_nowait(event)
        except queue.Full:
            if self._persist([event]):
                self._increment("accepted")
                self._increment("persisted")
                return True
            self._record_drop(1, "delivery queue is full and no spool is configured")
            return False
        self._increment("accepted")
        return True

    def flush(self, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while self.events.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)
        if not self.events.unfinished_tasks and self._spool_path():
            self._replay_spool(force=True)
        return self.events.unfinished_tasks == 0

    def shutdown(self, timeout_seconds: float) -> bool:
        drained = self.flush(timeout_seconds)
        self._stop.set()
        worker = self._worker
        if worker and worker.is_alive():
            worker.join(timeout=min(1.0, max(0.0, timeout_seconds)))
        return drained

    def snapshot(self) -> dict[str, Any]:
        with self._stats_lock:
            stats = dict(self._stats)
        stats.update(
            {
                "endpoint": self.config.endpoint.rstrip("/"),
                "queue_depth": self.events.qsize(),
                "queue_capacity": self.config.delivery_queue_size,
                "batch_size": self.batch_size,
                "spooled": self._spooled_count(),
                "worker_alive": bool(self._worker and self._worker.is_alive()),
            }
        )
        return stats

    def _ensure_worker(self) -> None:
        with self._worker_lock:
            if self._worker and self._worker.is_alive():
                return
            self._stop.clear()
            self._worker = threading.Thread(
                target=self._run,
                name="logllama-delivery",
                daemon=True,
            )
            self._worker.start()

    def _run(self) -> None:
        while not self._stop.is_set() or self.events.unfinished_tasks:
            self._replay_spool()
            try:
                first = self.events.get(
                    timeout=self.config.delivery_flush_interval_seconds
                )
            except queue.Empty:
                continue

            batch = [first]
            deadline = time.monotonic() + self.config.delivery_flush_interval_seconds
            while len(batch) < self.batch_size:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    batch.append(self.events.get(timeout=remaining))
                except queue.Empty:
                    break

            delivered = self._send_with_retries(batch)
            if delivered:
                self._increment("delivered", len(batch))
            else:
                self._increment("failed_batches")
                if self._persist(batch):
                    self._increment("persisted", len(batch))
                else:
                    self._record_drop(
                        len(batch),
                        "delivery failed after retries and no spool is configured",
                    )
            for _ in batch:
                self.events.task_done()

    def _send_with_retries(self, events: list[dict[str, Any]]) -> bool:
        for attempt in range(self.config.delivery_max_attempts):
            if _send_batch(self.config, events):
                return True
            if attempt + 1 < self.config.delivery_max_attempts:
                time.sleep(
                    self.config.delivery_retry_backoff_seconds * (2**attempt)
                )
        return False

    def _persist(self, events: list[dict[str, Any]]) -> bool:
        path = self._spool_path()
        if path is None:
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with self._spool_lock, path.open("a", encoding="utf-8") as spool:
                for event in events:
                    spool.write(json.dumps(event, default=str, separators=(",", ":")))
                    spool.write("\n")
            os.chmod(path, 0o600)
            return True
        except OSError as exc:
            warnings.warn(
                f"LogLlama could not persist undelivered events to {path}: {exc}",
                RuntimeWarning,
                stacklevel=3,
            )
            return False

    def _replay_spool(self, *, force: bool = False) -> None:
        path = self._spool_path()
        if path is None or not path.exists():
            return
        if not force and time.monotonic() < self._next_spool_retry_at:
            return

        with self._spool_lock:
            events = _read_spool(path)
            if not events:
                path.unlink(missing_ok=True)
                return
            batch = events[: self.batch_size]
            if not self._send_with_retries(batch):
                self._next_spool_retry_at = (
                    time.monotonic() + self.config.delivery_retry_backoff_seconds
                )
                return
            _rewrite_spool(path, events[len(batch) :])
        self._increment("delivered", len(batch))

    def _spool_path(self) -> Path | None:
        if not self.config.delivery_spool_path:
            return None
        return Path(self.config.delivery_spool_path).expanduser()

    def _spooled_count(self) -> int:
        path = self._spool_path()
        if path is None or not path.exists():
            return 0
        try:
            with self._spool_lock, path.open("r", encoding="utf-8") as spool:
                return sum(1 for line in spool if line.strip())
        except OSError:
            return 0

    def _record_drop(self, count: int, reason: str) -> None:
        self._increment("dropped", count)
        self._warned_drops += count
        if self._warned_drops == count or self._warned_drops % 100 == 0:
            warnings.warn(
                f"LogLlama dropped {count} event(s): {reason}. "
                "Configure LOGLLAMA_DELIVERY_SPOOL_PATH for persistent fallback.",
                RuntimeWarning,
                stacklevel=3,
            )

    def _increment(self, name: str, amount: int = 1) -> None:
        with self._stats_lock:
            self._stats[name] += amount


_dispatchers: dict[tuple[Any, ...], _EventDispatcher] = {}
_dispatchers_lock = threading.Lock()


def post_event_async(config: LogLlamaConfig, event: dict[str, Any]) -> bool:
    if not config.enabled or not config.api_key:
        return False
    return _dispatcher_for(config).enqueue(event)


def flush(timeout_seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    drained = True
    for dispatcher in _dispatcher_snapshot():
        remaining = max(0.0, deadline - time.monotonic())
        drained = dispatcher.flush(remaining) and drained
    return drained


def shutdown(timeout_seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    drained = True
    for dispatcher in _dispatcher_snapshot():
        remaining = max(0.0, deadline - time.monotonic())
        drained = dispatcher.shutdown(remaining) and drained
    return drained


def delivery_stats() -> dict[str, Any]:
    dispatchers = [dispatcher.snapshot() for dispatcher in _dispatcher_snapshot()]
    totals = {
        name: sum(int(item[name]) for item in dispatchers)
        for name in ("accepted", "delivered", "persisted", "dropped", "failed_batches")
    }
    totals["queue_depth"] = sum(int(item["queue_depth"]) for item in dispatchers)
    totals["spooled"] = sum(int(item["spooled"]) for item in dispatchers)
    return {**totals, "dispatchers": dispatchers}


def new_external_id() -> str:
    return f"llreq_{uuid.uuid4().hex}"


def _dispatcher_for(config: LogLlamaConfig) -> _EventDispatcher:
    key = (
        config.endpoint.rstrip("/"),
        hashlib.sha256((config.api_key or "").encode("utf-8")).hexdigest(),
        config.timeout_seconds,
        config.delivery_queue_size,
        config.delivery_batch_size,
        config.delivery_flush_interval_seconds,
        config.delivery_max_attempts,
        config.delivery_retry_backoff_seconds,
        config.delivery_spool_path,
    )
    with _dispatchers_lock:
        dispatcher = _dispatchers.get(key)
        if dispatcher is None:
            dispatcher = _EventDispatcher(config)
            _dispatchers[key] = dispatcher
        return dispatcher


def _dispatcher_snapshot() -> list[_EventDispatcher]:
    with _dispatchers_lock:
        return list(_dispatchers.values())


def _send_batch(config: LogLlamaConfig, events: list[dict[str, Any]]) -> bool:
    body = json.dumps({"events": events}, default=str).encode("utf-8")
    req = request.Request(
        config.endpoint.rstrip("/") + "/v1/events/batch",
        data=body,
        method="POST",
        headers=_headers(config),
    )
    try:
        with request.urlopen(req, timeout=config.timeout_seconds):
            return True
    except error.HTTPError as exc:
        if exc.code != 404:
            return False
    except Exception:
        return False
    return all(_send_single(config, event) for event in events)


def _send_single(config: LogLlamaConfig, event: dict[str, Any]) -> bool:
    req = request.Request(
        config.endpoint.rstrip("/") + "/v1/events",
        data=json.dumps(event, default=str).encode("utf-8"),
        method="POST",
        headers=_headers(config),
    )
    try:
        with request.urlopen(req, timeout=config.timeout_seconds):
            return True
    except Exception:
        return False


def _headers(config: LogLlamaConfig) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-LogLlama-Api-Key": config.api_key or "",
        "User-Agent": "logllama-python/0.2.0",
    }


def _read_spool(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return events
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            warnings.warn(
                f"LogLlama ignored a corrupt delivery spool record in {path}.",
                RuntimeWarning,
                stacklevel=3,
            )
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _rewrite_spool(path: Path, events: list[dict[str, Any]]) -> None:
    if not events:
        path.unlink(missing_ok=True)
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as spool:
        for event in events:
            spool.write(json.dumps(event, default=str, separators=(",", ":")))
            spool.write("\n")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def _reset_delivery_for_tests() -> None:
    global _dispatchers
    shutdown(1.0)
    with _dispatchers_lock:
        _dispatchers = {}


atexit.register(shutdown)
