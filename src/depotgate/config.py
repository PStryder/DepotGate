"""Configuration settings for DepotGate."""

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """DepotGate configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="DEPOTGATE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Service
    service_name: str = Field(default="depotgate", description="Service name")
    host: str = Field(default="0.0.0.0", description="Server bind address")
    port: int = Field(default=8000, description="Server port")
    debug: bool = Field(default=False, description="Enable debug mode")
    instance_id: str = Field(default="depotgate-1", description="Instance identifier")

    # Tenant (single tenant for v0, but maintain ID for future)
    tenant_id: str = Field(default="default", description="Tenant identifier")

    # PostgreSQL - Metadata database
    postgres_host: str = Field(default="localhost", description="PostgreSQL host")
    postgres_port: int = Field(default=5432, description="PostgreSQL port")
    postgres_user: str = Field(default="depotgate", description="PostgreSQL user")
    postgres_password: str = Field(default="depotgate", description="PostgreSQL password")
    postgres_metadata_db: str = Field(default="depotgate_metadata", description="Metadata database name")
    postgres_receipts_db: str = Field(default="depotgate_receipts", description="Receipts database name")

    @property
    def metadata_database_url(self) -> str:
        """Connection string for metadata database."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_metadata_db}"
        )

    @property
    def receipts_database_url(self) -> str:
        """Connection string for receipts database."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_receipts_db}"
        )

    # Storage backend
    storage_backend: Literal["filesystem"] = Field(default="filesystem", description="Storage backend type")
    storage_base_path: Path = Field(default=Path("./data/staging"), description="Base path for artifact staging")
    storage_max_artifact_size_mb: int = Field(default=100, description="Max artifact size in MB (0 = no limit)")

    @field_validator("storage_base_path", mode="before")
    @classmethod
    def parse_path(cls, v: str | Path) -> Path:
        return Path(v)

    @property
    def storage_max_artifact_bytes(self) -> int:
        """Max artifact size in bytes, 0 means no limit."""
        if self.storage_max_artifact_size_mb <= 0:
            return 0
        return self.storage_max_artifact_size_mb * 1024 * 1024

    # Outbound sinks (comma-separated list of enabled sinks)
    enabled_sinks: str = Field(default="filesystem", description="Enabled sinks (comma-separated: filesystem, http)")

    # Filesystem sink settings
    sink_filesystem_base_path: Path = Field(default=Path("./data/shipped"), description="Base path for shipped artifacts")

    @field_validator("sink_filesystem_base_path", mode="before")
    @classmethod
    def parse_sink_path(cls, v: str | Path) -> Path:
        return Path(v)

    # HTTP sink settings
    sink_http_timeout_seconds: int = Field(default=30, description="HTTP sink timeout in seconds")
    sink_http_allowed_hosts: list[str] = Field(
        default_factory=list,
        description="Allowlist of hostnames for HTTP sink destinations"
    )
    sink_http_allowed_schemes: list[str] = Field(
        default=["http", "https"],
        description="Allowed URL schemes for HTTP sink destinations"
    )

    def get_enabled_sinks(self) -> list[str]:
        """Parse comma-separated sink list."""
        return [s.strip() for s in self.enabled_sinks.split(",") if s.strip()]

    # CORS configuration (explicit allowlist for security)
    cors_allowed_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8080"],
        description="Allowed CORS origins (explicit allowlist for security)"
    )
    cors_allow_credentials: bool = Field(
        default=True,
        description="Allow credentials in CORS requests"
    )
    cors_allowed_methods: list[str] = Field(
        default=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        description="Allowed HTTP methods"
    )
    cors_allowed_headers: list[str] = Field(
        default=["Authorization", "Content-Type", "X-Tenant-ID"],
        description="Allowed request headers"
    )

    # Authentication
    api_key: str = Field(default="", description="API key for authentication")
    allow_insecure_dev: bool = Field(default=False, description="Allow unauthenticated access (dev only)")

    # Rate limiting
    rate_limit_enabled: bool = Field(default=True, description="Enable rate limiting")
    rate_limit_requests_per_minute: int = Field(default=200, description="Rate limit per minute")

    # Validators
    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Validate port number range."""
        if not 1 <= v <= 65535:
            raise ValueError(f"Port must be between 1 and 65535, got {v}")
        return v

    @field_validator("postgres_host")
    @classmethod
    def validate_postgres_host(cls, v: str) -> str:
        """Validate PostgreSQL host is not empty."""
        if not v or not v.strip():
            raise ValueError("postgres_host cannot be empty")
        return v

    @field_validator("postgres_port")
    @classmethod
    def validate_postgres_port(cls, v: int) -> int:
        """Validate PostgreSQL port range."""
        if not 1 <= v <= 65535:
            raise ValueError(f"PostgreSQL port must be between 1 and 65535, got {v}")
        return v

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str, info) -> str:
        """Validate API key is set when auth is required."""
        allow_insecure = info.data.get("allow_insecure_dev", False)
        if not v and not allow_insecure:
            raise ValueError("api_key is required when allow_insecure_dev=False")
        return v


# Global settings instance
settings = Settings()
