"""Configuration settings for DepotGate."""

from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """DepotGate configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="DEPOTGATE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Service
    service_name: str = "depotgate"
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # Tenant (single tenant for v0, but maintain ID for future)
    tenant_id: str = "default"

    # PostgreSQL - Metadata database
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "depotgate"
    postgres_password: str = "depotgate"
    postgres_metadata_db: str = "depotgate_metadata"
    postgres_receipts_db: str = "depotgate_receipts"

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
    storage_backend: Literal["filesystem"] = "filesystem"
    storage_base_path: Path = Field(default=Path("./data/staging"))
    storage_max_artifact_size_mb: int = 100  # 0 = no limit

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
    enabled_sinks: str = "filesystem"  # Options: filesystem, http

    # Filesystem sink settings
    sink_filesystem_base_path: Path = Field(default=Path("./data/shipped"))

    @field_validator("sink_filesystem_base_path", mode="before")
    @classmethod
    def parse_sink_path(cls, v: str | Path) -> Path:
        return Path(v)

    # HTTP sink settings
    sink_http_timeout_seconds: int = 30

    def get_enabled_sinks(self) -> list[str]:
        """Parse comma-separated sink list."""
        return [s.strip() for s in self.enabled_sinks.split(",") if s.strip()]


# Global settings instance
settings = Settings()
