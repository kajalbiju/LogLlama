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


DEFAULT_MODEL = "claude-sonnet-4-20250514"
RUN_FLAG = "RUN_LOGLLAMA_ANTHROPIC_INTEGRATION"
SUCCESS_RUNS_ENV = "LOGLLAMA_ANTHROPIC_SUCCESS_RUNS"


def _require_real_anthropic() -> None:
    load_dotenv()
    if os.getenv(RUN_FLAG) != "1":
        pytest.skip(f"Set {RUN_FLAG}=1 to run Anthropic integration tests.")
    if not os.getenv("LOGLLAMA_API_KEY"):
        pytest.fail("LOGLLAMA_API_KEY is required when RUN_LOGLLAMA_ANTHROPIC_INTEGRATION=1.")
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
    deadline = time.monotonic() + 10
    query = parse.urlencode({"limit": 5, "request_id": request_id})
    while time.monotonic() < deadline:
        with request.urlopen(f"{endpoint}/api/requests?{query}", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("requests"):
            return payload["requests"][0]
        time.sleep(0.25)
    pytest.fail(f"LogLlama backend did not return request_id={request_id}.")


def _managed_anthropic(monkeypatch: pytest.MonkeyPatch, endpoint: str):
    anthropic = pytest.importorskip("anthropic")
    _require_real_anthropic()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert "ANTHROPIC_API_KEY" not in os.environ
    return logllama.LLM.from_managed(
        models={"anthropic": os.getenv("LOGLLAMA_ANTHROPIC_TEST_MODEL", DEFAULT_MODEL)},
        endpoint=endpoint,
        runtime_key=os.environ["LOGLLAMA_RUNTIME_KEY"],
        refresh_seconds=300,
        provider_factories={"anthropic": lambda api_key: anthropic.Anthropic(api_key=api_key, max_retries=0)},
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


def test_valid_anthropic_managed_credentials_capture_bounded_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_real_anthropic()
    endpoint = _require_backend()
    model = os.getenv("LOGLLAMA_ANTHROPIC_TEST_MODEL", DEFAULT_MODEL)
    client = _managed_anthropic(monkeypatch, endpoint)

    try:
        for run_index in range(_success_runs()):
            request_id = f"anthropic-managed-valid-{run_index}-{uuid.uuid4().hex}"
            response = client.generate(
                "Reply with exactly: ok",
                provider="anthropic",
                metadata={
                    "route": "/tests/anthropic-capture",
                    "request_id": request_id,
                    "tenant_id": "test_tenant_enterprise",
                    "tags": ["integration", "anthropic", "managed"],
                    "custom_metadata": {"feature": "anthropic_full_capture", "api_key": "must-be-redacted"},
                },
                max_output_tokens=16,
                temperature=0,
            )
            assert response.text
            event = _wait_for_backend_request(endpoint, request_id)
            assert event["status"] == "success"
            assert event["provider"] == "anthropic"
            assert event["model"] == model
            assert event["route"] == "/tests/anthropic-capture"
            assert event["custom_metadata"]["feature"] == "anthropic_full_capture"
            assert event["custom_metadata"]["api_key"] == "[REDACTED]"
            assert event["total_tokens"] > 0
            assert event["model_parameters"]["max_tokens"] == 16
    finally:
        client.close()
