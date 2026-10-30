from __future__ import annotations

import json
import os
from http.cookiejar import CookieJar
from urllib import parse, request

import pytest


_DASHBOARD_ENV = ("LOGLLAMA_DASHBOARD_EMAIL", "LOGLLAMA_DASHBOARD_PASSWORD", "LOGLLAMA_PROJECT_ID")
_sessions: dict[str, request.OpenerDirector] = {}


def require_dashboard_env() -> None:
    """Captured events are read back through the dashboard API, which needs an account and a project."""
    missing = [name for name in _DASHBOARD_ENV if not os.getenv(name)]
    if missing:
        pytest.fail(f"{', '.join(missing)} required to read captured events back from the backend.")


def _session_opener(endpoint: str) -> request.OpenerDirector:
    if endpoint not in _sessions:
        opener = request.build_opener(request.HTTPCookieProcessor(CookieJar()))
        body = json.dumps(
            {
                "email": os.environ["LOGLLAMA_DASHBOARD_EMAIL"],
                "password": os.environ["LOGLLAMA_DASHBOARD_PASSWORD"],
            }
        ).encode("utf-8")
        login = request.Request(
            f"{endpoint}/api/auth/login",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "X-LogLlama-Request": "1"},
        )
        with opener.open(login, timeout=5):
            pass
        _sessions[endpoint] = opener
    return _sessions[endpoint]


def dashboard_get(endpoint: str, path: str, params: dict[str, object]) -> dict:
    query = parse.urlencode({"project_id": os.environ["LOGLLAMA_PROJECT_ID"], **params})
    with _session_opener(endpoint).open(f"{endpoint}{path}?{query}", timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))
