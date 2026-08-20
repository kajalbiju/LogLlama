from app.config import (
    DEFAULT_API_KEY,
    DEFAULT_DATABASE_URL,
    DEFAULT_PROJECT_NAME,
    MAX_RUNTIME_KEY_LENGTH,
    MIN_PRIVILEGED_KEY_LENGTH,
    Settings,
    is_secure_privileged_key,
)
from pydantic import ValidationError
import pytest


def test_blank_environment_values_fall_back_to_dev_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("LOGLLAMA_DEFAULT_API_KEY", "")
    monkeypatch.setenv("LOGLLAMA_DEFAULT_RUNTIME_KEY", "")
    monkeypatch.setenv("LOGLLAMA_DEFAULT_PROJECT_NAME", "")

    settings = Settings()

    assert settings.database_url == DEFAULT_DATABASE_URL
    assert settings.default_api_key == DEFAULT_API_KEY
    assert settings.default_runtime_key is None
    assert settings.default_project_name == DEFAULT_PROJECT_NAME


@pytest.mark.parametrize(
    ("environment_name", "legacy_value", "field_name"),
    [
        ("LOGLLAMA_DEFAULT_RUNTIME_KEY", "llama-runtime-key", "default_runtime_key"),
        ("LOGLLAMA_ADMIN_API_KEY", "llama-admin-key", "admin_api_key"),
    ],
)
def test_legacy_privileged_keys_disable_feature(
    monkeypatch, environment_name, legacy_value, field_name
):
    monkeypatch.setenv(environment_name, legacy_value)

    configured = Settings()

    assert getattr(configured, field_name) is None


@pytest.mark.parametrize(
    "environment_name",
    ["LOGLLAMA_DEFAULT_RUNTIME_KEY", "LOGLLAMA_ADMIN_API_KEY"],
)
def test_short_privileged_keys_are_rejected(monkeypatch, environment_name):
    monkeypatch.setenv(environment_name, "short-custom-key")

    with pytest.raises(ValidationError, match="must contain at least"):
        Settings()


def test_strong_privileged_keys_are_accepted(monkeypatch):
    runtime_key = "r" * MIN_PRIVILEGED_KEY_LENGTH
    admin_key = "a" * MIN_PRIVILEGED_KEY_LENGTH
    monkeypatch.setenv("LOGLLAMA_DEFAULT_RUNTIME_KEY", runtime_key)
    monkeypatch.setenv("LOGLLAMA_ADMIN_API_KEY", admin_key)

    configured = Settings()

    assert configured.default_runtime_key == runtime_key
    assert configured.admin_api_key == admin_key


def test_maximum_length_runtime_key_is_accepted(monkeypatch):
    runtime_key = "r" * MAX_RUNTIME_KEY_LENGTH
    monkeypatch.setenv("LOGLLAMA_DEFAULT_RUNTIME_KEY", runtime_key)

    configured = Settings()

    assert configured.default_runtime_key == runtime_key
    assert is_secure_privileged_key(runtime_key)


def test_runtime_key_longer_than_database_column_is_rejected(monkeypatch):
    runtime_key = "r" * (MAX_RUNTIME_KEY_LENGTH + 1)
    monkeypatch.setenv("LOGLLAMA_DEFAULT_RUNTIME_KEY", runtime_key)

    with pytest.raises(ValidationError, match="must contain at most 255"):
        Settings()

    assert not is_secure_privileged_key(runtime_key)


@pytest.mark.parametrize("backend", ["memory", "aws", "vault", "openbao"])
def test_supported_secret_backends(backend):
    settings = Settings(LOGLLAMA_SECRET_BACKEND=backend)

    assert settings.secret_backend == backend


def test_vault_conventional_environment_aliases(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault.internal:8200")
    monkeypatch.setenv("VAULT_TOKEN", "test-token")
    monkeypatch.delenv("LOGLLAMA_SECRET_STORE_ADDR", raising=False)
    monkeypatch.delenv("LOGLLAMA_SECRET_STORE_TOKEN", raising=False)

    settings = Settings()

    assert settings.secret_store_addr == "http://vault.internal:8200"
    assert settings.secret_store_token == "test-token"


def test_approle_file_settings(monkeypatch):
    monkeypatch.setenv("LOGLLAMA_SECRET_STORE_ROLE_ID_FILE", "/run/secrets/role-id")
    monkeypatch.setenv("LOGLLAMA_SECRET_STORE_SECRET_ID_FILE", "/run/secrets/secret-id")

    settings = Settings()

    assert settings.secret_store_role_id_file == "/run/secrets/role-id"
    assert settings.secret_store_secret_id_file == "/run/secrets/secret-id"
