#!/usr/bin/env python3
"""Create or reuse a LogLlama account, project, and API keys for local development and CI.

The password is read from an environment variable so it never appears in shell history or process lists.
Provider secrets are read the same way, from `--credential provider=ENV_NAME` pairs.

Examples:
    LOGLLAMA_PROVISION_PASSWORD=... python3 scripts/provision_local.py --email dev@example.com
    LOGLLAMA_PROVISION_PASSWORD=... python3 scripts/provision_local.py \
        --email ci@example.com --credential openai=OPENAI_API_KEY --format env >> "$GITHUB_ENV"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from http.cookiejar import CookieJar
from urllib import error, request


CSRF_HEADER = {"X-LogLlama-Request": "1"}


class Client:
    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.opener = request.build_opener(request.HTTPCookieProcessor(CookieJar()))

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json", **({} if method == "GET" else CSRF_HEADER)}
        req = request.Request(f"{self.endpoint}{path}", data=data, method=method, headers=headers)
        try:
            with self.opener.open(req, timeout=10) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else {}
        except error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, {"detail": raw.decode("utf-8", "replace")}

    def must(self, method: str, path: str, body: dict | None = None) -> dict:
        status, payload = self.call(method, path, body)
        if status >= 400:
            raise SystemExit(f"{method} {path} failed with HTTP {status}: {payload.get('detail', payload)}")
        return payload


def parse_credentials(pairs: list[str]) -> dict[str, str]:
    credentials: dict[str, str] = {}
    for pair in pairs:
        provider, _, env_name = pair.partition("=")
        if provider not in {"openai", "anthropic", "gemini"} or not env_name:
            raise SystemExit(f"--credential must look like provider=ENV_NAME, got {pair!r}")
        value = os.environ.get(env_name, "")
        if not value:
            raise SystemExit(f"Environment variable {env_name} is empty.")
        credentials[provider] = value
    return credentials


def sign_in(client: Client, email: str, password: str, organization: str) -> None:
    status, _ = client.call(
        "POST",
        "/api/auth/signup",
        {"email": email, "password": password, "name": "Provisioned", "organization_name": organization},
    )
    if status == 201:
        return
    if status != 409:
        raise SystemExit(f"Sign-up failed with HTTP {status}.")
    client.must("POST", "/api/auth/login", {"email": email, "password": password})


def find_organization(client: Client, organization_name: str) -> dict:
    session = client.must("GET", "/api/auth/me")
    writable = [org for org in session["organizations"] if org["role"] in {"owner", "developer"}]
    for organization in writable:
        if organization["name"] == organization_name:
            return organization
    if writable:
        return writable[0]
    raise SystemExit("This account has no organization where it can create projects or keys.")


def ensure_project(client: Client, organization_id: str, project_name: str) -> str:
    projects = client.must("GET", f"/api/projects?organization_id={organization_id}")
    for project in projects:
        if project["name"] == project_name:
            return project["id"]
    return client.must("POST", "/api/projects", {"organization_id": organization_id, "name": project_name})["id"]


def create_key(client: Client, project_id: str, kind: str, label: str) -> str:
    created = client.must(
        "POST",
        f"/api/projects/{project_id}/api-keys",
        {"name": f"{label} {kind} key {int(time.time())}", "kind": kind},
    )
    return created["key"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision a LogLlama account, project, and keys.")
    parser.add_argument("--endpoint", default=os.getenv("LOGLLAMA_ENDPOINT", "http://127.0.0.1:8000"))
    parser.add_argument("--email", required=True)
    parser.add_argument("--password-env", default="LOGLLAMA_PROVISION_PASSWORD")
    parser.add_argument("--organization", default="Local Development")
    parser.add_argument("--project", default="Default")
    parser.add_argument(
        "--credential",
        action="append",
        default=[],
        metavar="PROVIDER=ENV_NAME",
        help="Store a provider key read from ENV_NAME as a managed credential. Repeatable.",
    )
    parser.add_argument("--format", choices=["env", "json"], default="env")
    args = parser.parse_args()

    password = os.environ.get(args.password_env, "")
    if len(password) < 12:
        print(f"Set {args.password_env} to a password of at least 12 characters.", file=sys.stderr)
        return 2
    credentials = parse_credentials(args.credential)

    client = Client(args.endpoint)
    sign_in(client, args.email, password, args.organization)
    organization = find_organization(client, args.organization)
    project_id = ensure_project(client, organization["id"], args.project)

    for provider, secret in credentials.items():
        status, payload = client.call(
            "POST",
            f"/api/admin/provider-credentials?project_id={project_id}",
            {"provider": provider, "name": "provisioned", "api_key": secret},
        )
        if status >= 400:
            raise SystemExit(f"Storing the {provider} credential failed with HTTP {status}: {payload.get('detail')}")

    values = {
        "LOGLLAMA_PROJECT_ID": project_id,
        "LOGLLAMA_API_KEY": create_key(client, project_id, "ingest", "provisioned"),
        "LOGLLAMA_RUNTIME_KEY": create_key(client, project_id, "runtime", "provisioned"),
        "LOGLLAMA_DASHBOARD_EMAIL": args.email,
    }
    if args.format == "json":
        print(json.dumps(values, indent=2))
    else:
        for name, value in values.items():
            print(f"{name}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
