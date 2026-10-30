from app.config import (
    DEFAULT_API_KEY,
    DEFAULT_DATABASE_URL,
    DEFAULT_PROJECT_NAME,
    MIN_PRIVILEGED_KEY_LENGTH,
    Settings,
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


def test_legacy_runtime_key_disables_the_feature(monkeypatch):
    monkeypatch.setenv("LOGLLAMA_DEFAULT_RUNTIME_KEY", "llama-runtime-key")

    assert Settings().default_runtime_key is None


def test_short_runtime_key_is_rejected(monkeypatch):
    monkeypatch.setenv("LOGLLAMA_DEFAULT_RUNTIME_KEY", "short-custom-key")

    with pytest.raises(ValidationError, match="must contain at least"):
        Settings()


def test_strong_runtime_key_is_accepted(monkeypatch):
    runtime_key = "r" * MIN_PRIVILEGED_KEY_LENGTH
    monkeypatch.setenv("LOGLLAMA_DEFAULT_RUNTIME_KEY", runtime_key)

    assert Settings().default_runtime_key == runtime_key


def test_shared_admin_key_setting_is_no_longer_read(monkeypatch):
    monkeypatch.setenv("LOGLLAMA_ADMIN_API_KEY", "a" * MIN_PRIVILEGED_KEY_LENGTH)

    assert not hasattr(Settings(), "admin_api_key")


def test_cors_origins_are_parsed_from_a_comma_separated_list(monkeypatch):
    monkeypatch.setenv("LOGLLAMA_CORS_ORIGINS", "https://app.example.com, https://admin.example.com ,")

    assert Settings().cors_origins == ["https://app.example.com", "https://admin.example.com"]


def test_session_and_cookie_defaults(monkeypatch):
    for name in ("LOGLLAMA_SESSION_TTL_HOURS", "LOGLLAMA_COOKIE_SECURE", "LOGLLAMA_ALLOW_SIGNUP"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings()

    assert settings.session_ttl_hours == 12
    assert settings.cookie_secure is False
    assert settings.allow_signup is True


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
