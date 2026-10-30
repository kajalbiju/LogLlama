from __future__ import annotations

import os
import json
import time
import uuid
from urllib import parse, request

import pytest

import logllama
from logllama.config import load_dotenv

from .dashboard_client import dashboard_get, require_dashboard_env


pytestmark = pytest.mark.integration


MODEL = os.getenv("LOGLLAMA_OPENAI_TEST_MODEL", "gpt-5-nano")
RUN_FLAG = "RUN_LOGLLAMA_OPENAI_INTEGRATION"
SUCCESS_RUNS_ENV = "LOGLLAMA_OPENAI_SUCCESS_RUNS"


REAL_TEST_METADATA = {
    "route": "/tests/openai-capture",
    "user_id": "test_user_001",
    "tenant_id": "test_tenant_enterprise",
    "session_id": "test_session_001",
    "conversation_id": "test_conversation_001",
    "request_id": "test_request_001",
    "trace_id": "00000000000000000000000000000001",
    "span_id": "0000000000000001",
    "prompt_template": "sdk_integration_smoke",
    "prompt_version": "v1",
    "tags": ["integration", "openai", "metadata"],
    "custom_metadata": {
        "feature": "sdk_metadata_capture",
        "ci_ready": True,
        "api_key": "should_be_redacted",
    },
}


def _require_real_openai() -> None:
    load_dotenv()
    if os.getenv(RUN_FLAG) != "1":
        pytest.skip(f"Set {RUN_FLAG}=1 to run OpenAI integration tests.")
    if not os.getenv("LOGLLAMA_API_KEY"):
        pytest.fail("LOGLLAMA_API_KEY is required when RUN_LOGLLAMA_OPENAI_INTEGRATION=1.")
    if not os.getenv("LOGLLAMA_RUNTIME_KEY"):
        pytest.fail("LOGLLAMA_RUNTIME_KEY is required for Provider-tab integration tests.")
    require_dashboard_env()


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
    while time.monotonic() < deadline:
        payload = dashboard_get(endpoint, "/api/requests", {"limit": 5, "request_id": request_id})
        if payload.get("requests"):
            return payload["requests"][0]
        time.sleep(0.25)
    pytest.fail(f"LogLlama backend did not return request_id={request_id}.")


def _managed_openai(monkeypatch: pytest.MonkeyPatch, endpoint: str):
    openai = pytest.importorskip("openai")
    _require_real_openai()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert "OPENAI_API_KEY" not in os.environ

    return logllama.LLM.from_managed(
        models={"openai": MODEL},
        endpoint=endpoint,
        runtime_key=os.environ["LOGLLAMA_RUNTIME_KEY"],
        refresh_seconds=300,
        provider_factories={
            "openai": lambda api_key: openai.OpenAI(api_key=api_key, max_retries=0),
        },
        instrumentation={
            "api_key": os.environ["LOGLLAMA_API_KEY"],
            "endpoint": endpoint,
            "service_name": "sdk-integration-tests",
            "environment": os.getenv("LOGLLAMA_TEST_ENVIRONMENT", "test"),
            "version": "0.1.0",
            "git_sha": "integration-test",
            "redact_keys": ["api_key"],
            "max_prompt_size": 4000,
            "max_response_size": 4000,
            "capture_errors": True,
            "sample_rate": 1,
            "capture_otel": False,
        },
    )


def test_invalid_openai_model_from_managed_credentials_posts_error_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_real_openai()
    endpoint = _require_backend()
    client = _managed_openai(monkeypatch, endpoint)

    request_id = f"managed-invalid-model-{uuid.uuid4().hex}"

    try:
        with pytest.raises(Exception):
            client.generate(
                "This request should fail because the model does not exist.",
                provider="openai",
                model="logllama-intentionally-invalid-model",
                metadata={
                    **REAL_TEST_METADATA,
                    "request_id": request_id,
                    "tags": ["integration", "openai", "managed", "invalid-model"],
                    "custom_metadata": {
                        "credential_source": "provider_tab",
                        "api_key": "must-be-redacted",
                    },
                },
                max_output_tokens=1,
            )
    finally:
        client.close()

    event = _wait_for_backend_request(endpoint, request_id)
    assert event["status"] == "error"
    assert event["provider"] == "openai"
    assert event["operation"] == "responses.create"
    assert event["service_name"] == "sdk-integration-tests"
    assert event["environment"] == os.getenv("LOGLLAMA_TEST_ENVIRONMENT", "test")
    assert event["route"] == REAL_TEST_METADATA["route"]
    assert event["tenant_id"] == REAL_TEST_METADATA["tenant_id"]
    assert event["custom_metadata"]["credential_source"] == "provider_tab"
    assert event["custom_metadata"]["api_key"] == "[REDACTED]"
    assert event["response"] is None
    assert event["error_type"]
    assert event["provider_request_id"]
    assert event["retry_count"] == 0
    assert event["model_parameters"]["max_output_tokens"] == 1


def test_valid_openai_managed_credentials_capture_bounded_billable_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_real_openai()
    endpoint = _require_backend()
    client = _managed_openai(monkeypatch, endpoint)

    try:
        for run_index in range(_success_runs()):
            request_id = f"managed-valid-{run_index}-{uuid.uuid4().hex}"
            response = client.generate(
                "ok",
                provider="openai",
                system="Reply with only: ok",
                metadata={
                    **REAL_TEST_METADATA,
                    "request_id": request_id,
                    "custom_metadata": {
                        **REAL_TEST_METADATA["custom_metadata"],
                        "credential_source": "provider_tab",
                    },
                },
                provider_options={
                    "reasoning": {"effort": "minimal"},
                    "text": {"verbosity": "low"},
                },
                max_output_tokens=16,
            )

            event = _wait_for_backend_request(endpoint, request_id)
            assert response.raw is not None
            assert event["status"] == "success"
            assert event["model"]
            assert event["service_name"] == "sdk-integration-tests"
            assert event["route"] == REAL_TEST_METADATA["route"]
            assert event["user_id"] == REAL_TEST_METADATA["user_id"]
            assert event["tenant_id"] == REAL_TEST_METADATA["tenant_id"]
            assert event["session_id"] == REAL_TEST_METADATA["session_id"]
            assert event["conversation_id"] == REAL_TEST_METADATA["conversation_id"]
            assert event["request_id"] == request_id
            assert event["trace_id"] == REAL_TEST_METADATA["trace_id"]
            assert event["span_id"] == REAL_TEST_METADATA["span_id"]
            assert event["prompt_template"] == REAL_TEST_METADATA["prompt_template"]
            assert event["prompt_version"] == REAL_TEST_METADATA["prompt_version"]
            assert set(REAL_TEST_METADATA["tags"]).issubset(set(event["tags"]))
            assert event["custom_metadata"]["feature"] == "sdk_metadata_capture"
            assert event["custom_metadata"]["credential_source"] == "provider_tab"
            assert event["custom_metadata"]["api_key"] == "[REDACTED]"
            assert event["privacy"]["sample_rate"] == 1
            assert event["provider_request_id"]
            assert event["retry_count"] == 0
            assert event["model_parameters"]["max_output_tokens"] == 16
            assert event["model_parameters"]["reasoning"] == {"effort": "minimal"}
            assert event["total_tokens"] > 0
    finally:
        client.close()
