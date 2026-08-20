from __future__ import annotations

import json
import os
import time
import uuid
from urllib import parse, request

import pytest

import logllama
from logllama.config import load_dotenv


pytestmark = pytest.mark.integration


DEFAULT_MODEL = "auto-smart"
RUN_FLAG = "RUN_LOGLLAMA_CURSOR_INTEGRATION"
SUCCESS_RUNS_ENV = "LOGLLAMA_CURSOR_SUCCESS_RUNS"


def _require_real_cursor() -> None:
    load_dotenv()
    if os.getenv(RUN_FLAG) != "1":
        pytest.skip(f"Set {RUN_FLAG}=1 to run Cursor SDK integration tests.")
    if not os.getenv("LOGLLAMA_API_KEY"):
        pytest.fail("LOGLLAMA_API_KEY is required when RUN_LOGLLAMA_CURSOR_INTEGRATION=1.")
    if not os.getenv("LOGLLAMA_RUNTIME_KEY"):
        pytest.fail("LOGLLAMA_RUNTIME_KEY is required for Provider-tab integration tests.")


def _success_runs() -> int:
    try:
        return min(10, max(1, int(os.getenv(SUCCESS_RUNS_ENV, "1"))))
    except ValueError:
        pytest.fail(f"{SUCCESS_RUNS_ENV} must be an integer between 1 and 10.")


def _require_backend() -> str:
    endpoint = os.getenv("LOGLLAMA_ENDPOINT", "http://localhost:8000").rstrip("/")
    try:
        with request.urlopen(f"{endpoint}/health", timeout=3) as response:
            if response.status != 200:
                pytest.fail(f"LogLlama backend health check returned HTTP {response.status}.")
    except Exception as exc:
        pytest.fail(f"LogLlama backend is not reachable at {endpoint}: {exc}")
    return endpoint


def _wait_for_backend_request(endpoint: str, request_id: str) -> dict:
    deadline = time.monotonic() + 30
    query = parse.urlencode({"limit": 5, "request_id": request_id})
    while time.monotonic() < deadline:
        with request.urlopen(f"{endpoint}/api/requests?{query}", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("requests"):
            return payload["requests"][0]
        time.sleep(0.25)
    pytest.fail(f"LogLlama backend did not return request_id={request_id}.")


def _managed_cursor(monkeypatch: pytest.MonkeyPatch, endpoint: str):
    cursor_sdk = pytest.importorskip("cursor_sdk")
    _require_real_cursor()
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    assert "CURSOR_API_KEY" not in os.environ
    model = os.getenv("LOGLLAMA_CURSOR_TEST_MODEL", DEFAULT_MODEL)

    def factory(api_key: str):
        return cursor_sdk.Agent.create(
            cursor_sdk.AgentOptions(
                model=model,
                api_key=api_key,
                local=cursor_sdk.LocalAgentOptions(cwd=os.getcwd()),
                tools=[],
            )
        )

    return logllama.LLM.from_managed(
        models={"cursor": model},
        endpoint=endpoint,
        runtime_key=os.environ["LOGLLAMA_RUNTIME_KEY"],
        refresh_seconds=300,
        provider_factories={"cursor": factory},
        instrumentation={
            "api_key": os.environ["LOGLLAMA_API_KEY"],
            "endpoint": endpoint,
            "service_name": "sdk-integration-tests",
            "environment": os.getenv("LOGLLAMA_TEST_ENVIRONMENT", "test"),
            "redact_keys": ["api_key"],
            "capture_errors": True,
            "sample_rate": 1,
            "capture_otel": False,
        },
    )


def test_valid_cursor_managed_credentials_capture_bounded_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_real_cursor()
    endpoint = _require_backend()
    model = os.getenv("LOGLLAMA_CURSOR_TEST_MODEL", DEFAULT_MODEL)
    client = _managed_cursor(monkeypatch, endpoint)

    try:
        for run_index in range(_success_runs()):
            request_id = f"cursor-managed-valid-{run_index}-{uuid.uuid4().hex}"
            response = client.generate(
                "Reply with exactly: ok. Do not use tools.",
                provider="cursor",
                metadata={
                    "route": "/tests/cursor-capture",
                    "request_id": request_id,
                    "tenant_id": "test_tenant_enterprise",
                    "tags": ["integration", "cursor", "managed"],
                    "custom_metadata": {"feature": "cursor_full_capture", "api_key": "must-be-redacted"},
                },
            )
            assert response.text
            event = _wait_for_backend_request(endpoint, request_id)
            assert event["status"] == "success"
            assert event["provider"] == "cursor"
            assert event["model"] == model
            assert event["route"] == "/tests/cursor-capture"
            assert event["custom_metadata"]["feature"] == "cursor_full_capture"
            assert event["custom_metadata"]["api_key"] == "[REDACTED]"
    finally:
        client.close()
