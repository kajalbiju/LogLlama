from __future__ import annotations

import json
import os
import time
import uuid
from urllib import parse, request

import pytest

import logllama
from logllama.config import load_dotenv

from .dashboard_client import dashboard_get, require_dashboard_env


pytestmark = pytest.mark.integration


DEFAULT_MODEL = "gemini-3.5-flash-lite"
RUN_FLAG = "RUN_LOGLLAMA_GEMINI_INTEGRATION"
SUCCESS_RUNS_ENV = "LOGLLAMA_GEMINI_SUCCESS_RUNS"


def _require_real_gemini() -> None:
    load_dotenv()
    if os.getenv(RUN_FLAG) != "1":
        pytest.skip(f"Set {RUN_FLAG}=1 to run Gemini integration tests.")
    if not os.getenv("LOGLLAMA_API_KEY"):
        pytest.fail("LOGLLAMA_API_KEY is required when RUN_LOGLLAMA_GEMINI_INTEGRATION=1.")
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


def _managed_gemini(monkeypatch: pytest.MonkeyPatch, endpoint: str):
    genai = pytest.importorskip("google.genai")
    _require_real_gemini()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert "GEMINI_API_KEY" not in os.environ
    assert "GOOGLE_API_KEY" not in os.environ

    return logllama.LLM.from_managed(
        models={"gemini": os.getenv("LOGLLAMA_GEMINI_TEST_MODEL", DEFAULT_MODEL)},
        endpoint=endpoint,
        runtime_key=os.environ["LOGLLAMA_RUNTIME_KEY"],
        refresh_seconds=300,
        provider_factories={"gemini": lambda api_key: genai.Client(api_key=api_key)},
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


def test_invalid_gemini_model_from_managed_credentials_posts_error_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_real_gemini()
    endpoint = _require_backend()
    client = _managed_gemini(monkeypatch, endpoint)
    request_id = f"gemini-managed-invalid-model-{uuid.uuid4().hex}"

    try:
        with pytest.raises(Exception):
            client.generate(
                "This request should fail because the model does not exist.",
                provider="gemini",
                model="logllama-intentionally-invalid-model",
                metadata={
                    "route": "/tests/gemini-capture",
                    "request_id": request_id,
                    "tags": ["integration", "gemini", "managed", "invalid-model"],
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
    assert event["provider"] == "gemini"
    assert event["operation"] in {"interactions.create", "models.generate_content"}
    assert event["custom_metadata"]["credential_source"] == "provider_tab"
    assert event["custom_metadata"]["api_key"] == "[REDACTED]"
    assert event["response"] is None
    assert event["error_type"]
    assert event["retry_count"] == 0
    assert event["model_parameters"]["max_output_tokens"] == 1


def test_valid_gemini_managed_credentials_capture_bounded_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_real_gemini()
    endpoint = _require_backend()
    model = os.getenv("LOGLLAMA_GEMINI_TEST_MODEL", DEFAULT_MODEL)
    client = _managed_gemini(monkeypatch, endpoint)

    try:
        for run_index in range(_success_runs()):
            request_id = f"gemini-managed-valid-{run_index}-{uuid.uuid4().hex}"
            response = client.generate(
                "Reply with exactly: ok",
                provider="gemini",
                metadata={
                    "route": "/tests/gemini-capture",
                    "request_id": request_id,
                    "tenant_id": "test_tenant_enterprise",
                    "tags": ["integration", "gemini", "instrumentation", "managed"],
                    "custom_metadata": {
                        "feature": "gemini_full_capture",
                        "credential_source": "provider_tab",
                        "api_key": "must-be-redacted",
                    },
                },
                provider_options={"thinking_config": {"thinking_level": "minimal"}},
                max_output_tokens=16,
            )

            event = _wait_for_backend_request(endpoint, request_id)
            assert response.text.strip().lower() == "ok"
            assert event["status"] == "success"
            assert event["provider"] == "gemini"
            assert event["operation"] in {"interactions.create", "models.generate_content"}
            provider_request_id = (
                getattr(response.raw, "response_id", None)
                or getattr(response.raw, "id", None)
            )
            assert provider_request_id
            assert event["provider_request_id"] == provider_request_id
            assert event["retry_count"] >= 0
            assert event["model_parameters"]["max_output_tokens"] == 16
            assert (
                event["model_parameters"]["thinking_config"]["thinking_level"].lower()
                == "minimal"
            )
            assert event["request_id"] == request_id
            assert event["route"] == "/tests/gemini-capture"
            assert event["tenant_id"] == "test_tenant_enterprise"
            assert event["custom_metadata"]["feature"] == "gemini_full_capture"
            assert event["custom_metadata"]["credential_source"] == "provider_tab"
            assert event["custom_metadata"]["api_key"] == "[REDACTED]"
            assert event["total_tokens"] > 0
    finally:
        client.close()
