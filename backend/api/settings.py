from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import BaseModel


class GraphSettings(BaseModel):
    COMMUNITY_LEVEL: int = 2
    COMMUNITY_REPORT_TABLE: str = (
        "data/yandex5_podcast/create_final_community_reports.parquet"
    )
    ENTITY_TABLE: str = "data/yandex5_podcast/create_final_nodes.parquet"
    ENTITY_EMBEDDING_TABLE: str = "data/yandex5_podcast/create_final_entities.parquet"
    TEXT_UNIT_TABLE: str = "data/yandex5_podcast/create_final_text_units.parquet"
    COMMUNITY_TABLE: str = "data/yandex5_podcast/create_final_communities.parquet"
    RELATIONSHIP_TABLE: str = "data/yandex5_podcast/create_final_relationships.parquet"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter=".",
        extra="ignore",
        case_sensitive=False,
    )

    PODCAST: GraphSettings
    GAZETA: GraphSettings

    YANDEX_FOLDER_ID: str
    YANDEX_TOKEN: str
    YANDEX_MODEL: str
    YANDEX_MODEL_VERSION: str

    PG_HOST: str
    PG_PORT: int = 5432
    PG_USER: str
    PG_PASSWORD: str
    PG_DATABASE: str = "graphrag"


settings = Settings()  # type: ignore
