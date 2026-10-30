import asyncio

import pytest
from fastapi import HTTPException

from app.deps import ROLE_PERMISSIONS, role_allows, runtime_project
from app.routes.admin import require_persistent_secret_store
from app import config


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.mark.parametrize(
    ("role", "permission", "allowed"),
    [
        ("viewer", "data:read", True),
        ("viewer", "keys:manage", False),
        ("developer", "keys:manage", True),
        ("developer", "tests:approve", False),
        ("test_approver", "tests:approve", True),
        ("test_approver", "credentials:manage", False),
        ("credential_admin", "credentials:manage", True),
        ("credential_admin", "members:manage", False),
        ("owner", "members:manage", True),
        ("owner", "credentials:manage", True),
        ("unknown-role", "data:read", False),
    ],
)
def test_role_permissions(role, permission, allowed):
    assert role_allows(role, permission) is allowed


def test_owner_has_every_permission_defined_for_any_role():
    every_permission = set().union(*ROLE_PERMISSIONS.values())
    assert set(ROLE_PERMISSIONS["owner"]) == every_permission


@pytest.mark.parametrize("runtime_key", ["llama-runtime-key", "short-custom-key"])
def test_insecure_runtime_keys_are_rejected_before_database_lookup(runtime_key):
    with pytest.raises(HTTPException) as error:
        run(runtime_project(runtime_key, object()))

    assert error.value.status_code == 401


def test_provider_credential_writes_reject_ephemeral_store(monkeypatch):
    monkeypatch.setattr(config.settings, "secret_backend", "memory")
    monkeypatch.setattr(config.settings, "allow_ephemeral_secrets", False)

    with pytest.raises(HTTPException) as error:
        require_persistent_secret_store()

    assert error.value.status_code == 503
    assert "persistent secret backend" in error.value.detail


def test_provider_credential_writes_allow_openbao(monkeypatch):
    monkeypatch.setattr(config.settings, "secret_backend", "openbao")
    monkeypatch.setattr(config.settings, "allow_ephemeral_secrets", False)

    assert require_persistent_secret_store() is None
