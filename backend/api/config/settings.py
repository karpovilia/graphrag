from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DeepseekSettings(BaseModel):
    api_key: str = Field(default="", description="Empty disables the provider.")
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    timeout_s: float = 60.0


class YandexSettings(BaseModel):
    """Optional in R2. Kept so existing prod tokens still work for users
    who haven't switched to Deepseek.
    """

    folder_id: str = ""
    token: str = ""
    completion_model: str = "yandexgpt"
    completion_model_version: str = "latest"
    embedding_model: str = "text-search-query"
    embedding_dim: int = 256


class PostgresSettings(BaseModel):
    host: str = "localhost"
    port: int = 5432
    user: str = "graphrag"
    password: str = ""
    database: str = "graphrag"
    pool_min_size: int = 2
    pool_max_size: int = 10

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )


class StorageSettings(BaseModel):
    """Local on-disk layout. Single-instance deploy (NF9), no S3 in R2."""

    data_dir: Path = Path("./data")
    """Root for everything: corpora dumps, FAISS indexes, run logs."""

    faiss_dir_name: str = "faiss"
    """Subdirectory under data_dir/{graph_variant_id}/ for FAISS files."""

    blobs_dir_name: str = "blobs"
    """Subdirectory for large embedding-snapshot blobs and other binaries."""


class R2Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    deepseek: DeepseekSettings = DeepseekSettings()
    yandex: YandexSettings = YandexSettings()
    postgres: PostgresSettings = PostgresSettings()
    storage: StorageSettings = StorageSettings()

    default_completion_provider: str = "deepseek"
    default_embedding_provider: str = "yandex"
    """Yandex still owns embeddings until a Russian-friendly Deepseek
    embedding endpoint is wired in. EDA may also surface other choices.
    """

    cors_origins: list[str] = Field(default_factory=lambda: ["*"])
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> R2Settings:
    return R2Settings()  # type: ignore[call-arg]
