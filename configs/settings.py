"""
Application Settings
====================
All environment-based configuration lives here.
Never hardcode values in service or adapter code.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "Financial Intelligence Platform"
    app_version: str = "0.1.0"
    debug: bool = False

    # SQLite / PostgreSQL
    database_url: str = "sqlite+aiosqlite:///./finplatform.db"
    database_echo: bool = False

    # Storage (Phase 1: local disk)
    storage_base_path: str = "./storage"

    # ---- OpenRouter (Phase 3) ----
    # Models are tried left-to-right; next is used if one hits rate/quota limit
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_models: str = "nvidia/nemotron-3-ultra-550b-a55b:free,poolside/laguna-m.1:free"

    @property
    def openrouter_model_list(self) -> list[str]:
        """Returns ordered list of models to try (fallback chain)."""
        return [m.strip() for m in self.openrouter_models.split(",") if m.strip()]

    # Confidence thresholds
    min_acceptable_confidence: float = 0.60
    min_reliable_confidence: float = 0.80

    # Ingestion limits
    max_upload_size_mb: int = 50
    max_csv_rows: int = 100_000


@lru_cache
def get_settings() -> Settings:
    """Returns cached settings instance. Import this in all adapters."""
    return Settings()
