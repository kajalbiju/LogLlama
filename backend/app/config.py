from typing import Any

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_DATABASE_URL = "postgresql+asyncpg://logllama:logllama@localhost:5432/logllama"
DEFAULT_API_KEY = "llama-dev-key"
DEFAULT_RUNTIME_KEY = None
DEFAULT_PROJECT_NAME = "Development"
DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173,http://127.0.0.1:5173,"
    "http://localhost:5174,http://127.0.0.1:5174,"
    "http://localhost:5175,http://127.0.0.1:5175,"
    "http://localhost:5176,http://127.0.0.1:5176"
)
MIN_PRIVILEGED_KEY_LENGTH = 32
LEGACY_RUNTIME_KEYS = frozenset({"llama-runtime-key"})


def is_secure_privileged_key(value: str | None) -> bool:
    return bool(
        value
        and len(value) >= MIN_PRIVILEGED_KEY_LENGTH
        and value not in LEGACY_RUNTIME_KEYS
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
    allow_signup: bool = Field(default=True, validation_alias="LOGLLAMA_ALLOW_SIGNUP")
    session_ttl_hours: int = Field(default=12, ge=1, le=24 * 30, validation_alias="LOGLLAMA_SESSION_TTL_HOURS")
    cookie_secure: bool = Field(default=False, validation_alias="LOGLLAMA_COOKIE_SECURE")
    cors_origins_raw: str = Field(default=DEFAULT_CORS_ORIGINS, validation_alias="LOGLLAMA_CORS_ORIGINS")
    max_batch_events: int = Field(default=500, ge=1, le=5000, validation_alias="LOGLLAMA_MAX_BATCH_EVENTS")
    max_request_bytes: int = Field(
        default=5_000_000,
        ge=1024,
        validation_alias="LOGLLAMA_MAX_REQUEST_BYTES",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

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

    @field_validator("default_runtime_key", mode="before")
    @classmethod
    def runtime_key_must_be_explicit_and_strong(cls, value: Any):
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if not normalized or normalized in LEGACY_RUNTIME_KEYS:
            return None
        if len(normalized) < MIN_PRIVILEGED_KEY_LENGTH:
            raise ValueError(
                "LOGLLAMA_DEFAULT_RUNTIME_KEY must contain at least "
                f"{MIN_PRIVILEGED_KEY_LENGTH} characters."
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
