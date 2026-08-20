from typing import Any

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_DATABASE_URL = "postgresql+asyncpg://logllama:logllama@localhost:5432/logllama"
DEFAULT_API_KEY = "llama-dev-key"
DEFAULT_RUNTIME_KEY = None
DEFAULT_PROJECT_NAME = "Development"
MIN_PRIVILEGED_KEY_LENGTH = 32
MAX_RUNTIME_KEY_LENGTH = 255
LEGACY_RUNTIME_KEYS = frozenset({"llama-runtime-key"})
LEGACY_ADMIN_KEYS = frozenset({"llama-admin-key"})


def is_secure_privileged_key(value: str | None) -> bool:
    return bool(
        value
        and len(value) >= MIN_PRIVILEGED_KEY_LENGTH
        and len(value) <= MAX_RUNTIME_KEY_LENGTH
        and value not in LEGACY_RUNTIME_KEYS
        and value not in LEGACY_ADMIN_KEYS
    )


class Settings(BaseSettings):
    database_url: str = Field(
        default=DEFAULT_DATABASE_URL,
        validation_alias="DATABASE_URL",
    )
    default_api_key: str = Field(default=DEFAULT_API_KEY, validation_alias="LOGLLAMA_DEFAULT_API_KEY")
    default_runtime_key: str | None = Field(
        default=DEFAULT_RUNTIME_KEY, validation_alias="LOGLLAMA_DEFAULT_RUNTIME_KEY"
    )
    default_project_name: str = Field(default=DEFAULT_PROJECT_NAME, validation_alias="LOGLLAMA_DEFAULT_PROJECT_NAME")
    admin_api_key: str | None = Field(default=None, validation_alias="LOGLLAMA_ADMIN_API_KEY")
    secret_backend: str = Field(default="memory", validation_alias="LOGLLAMA_SECRET_BACKEND")
    allow_ephemeral_secrets: bool = Field(
        default=False,
        validation_alias="LOGLLAMA_ALLOW_EPHEMERAL_SECRETS",
    )
    secret_prefix: str = Field(default="logllama", validation_alias="LOGLLAMA_SECRET_PREFIX")
    aws_region: str | None = Field(default=None, validation_alias="AWS_REGION")
    secret_store_addr: str = Field(
        default="http://127.0.0.1:8200",
        validation_alias=AliasChoices(
            "LOGLLAMA_SECRET_STORE_ADDR",
            "VAULT_ADDR",
            "BAO_ADDR",
        ),
    )
    secret_store_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "LOGLLAMA_SECRET_STORE_TOKEN",
            "VAULT_TOKEN",
            "BAO_TOKEN",
        ),
    )
    secret_store_token_file: str | None = Field(
        default=None,
        validation_alias="LOGLLAMA_SECRET_STORE_TOKEN_FILE",
    )
    secret_store_role_id: str | None = Field(
        default=None,
        validation_alias="LOGLLAMA_SECRET_STORE_ROLE_ID",
    )
    secret_store_role_id_file: str | None = Field(
        default=None,
        validation_alias="LOGLLAMA_SECRET_STORE_ROLE_ID_FILE",
    )
    secret_store_secret_id: str | None = Field(
        default=None,
        validation_alias="LOGLLAMA_SECRET_STORE_SECRET_ID",
    )
    secret_store_secret_id_file: str | None = Field(
        default=None,
        validation_alias="LOGLLAMA_SECRET_STORE_SECRET_ID_FILE",
    )
    secret_store_mount: str = Field(
        default="secret",
        validation_alias="LOGLLAMA_SECRET_STORE_MOUNT",
    )
    secret_store_namespace: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "LOGLLAMA_SECRET_STORE_NAMESPACE",
            "VAULT_NAMESPACE",
        ),
    )
    secret_store_timeout_seconds: float = Field(
        default=2.0,
        gt=0,
        validation_alias="LOGLLAMA_SECRET_STORE_TIMEOUT_SECONDS",
    )
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
        "http://localhost:5176",
        "http://127.0.0.1:5176",
    ]

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    @field_validator(
        "database_url",
        "default_api_key",
        "default_project_name",
        mode="before",
    )
    @classmethod
    def blank_string_uses_default(cls, value: Any, info):
        if not isinstance(value, str) or value.strip():
            return value
        defaults = {
            "database_url": DEFAULT_DATABASE_URL,
            "default_api_key": DEFAULT_API_KEY,
            "default_project_name": DEFAULT_PROJECT_NAME,
        }
        return defaults[info.field_name]

    @field_validator("default_runtime_key", "admin_api_key", mode="before")
    @classmethod
    def privileged_keys_must_be_explicit_and_strong(cls, value: Any, info):
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        legacy_values = (
            LEGACY_RUNTIME_KEYS
            if info.field_name == "default_runtime_key"
            else LEGACY_ADMIN_KEYS
        )
        if not normalized or normalized in legacy_values:
            return None
        if len(normalized) < MIN_PRIVILEGED_KEY_LENGTH:
            environment_name = (
                "LOGLLAMA_DEFAULT_RUNTIME_KEY"
                if info.field_name == "default_runtime_key"
                else "LOGLLAMA_ADMIN_API_KEY"
            )
            raise ValueError(
                f"{environment_name} must contain at least "
                f"{MIN_PRIVILEGED_KEY_LENGTH} characters."
            )
        if (
            info.field_name == "default_runtime_key"
            and len(normalized) > MAX_RUNTIME_KEY_LENGTH
        ):
            raise ValueError(
                "LOGLLAMA_DEFAULT_RUNTIME_KEY must contain at most "
                f"{MAX_RUNTIME_KEY_LENGTH} characters."
            )
        return normalized

    @field_validator("secret_backend")
    @classmethod
    def valid_secret_backend(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"memory", "aws", "vault", "openbao"}:
            raise ValueError(
                "LOGLLAMA_SECRET_BACKEND must be 'memory', 'aws', 'vault', or 'openbao'."
            )
        return normalized


settings = Settings()
