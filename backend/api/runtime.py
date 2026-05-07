"""Process-wide singletons that wire DI for strategies.

The orchestrator (and FastAPI routes) reach for these instead of
constructing heavy dependencies (natasha pipeline, LLM clients) on
every request. Lazy — first call pays the load cost, subsequent calls
reuse the same object.

Tests bypass this entirely: they instantiate strategies directly with
fake dependencies. Production startup wires the real ones via
api.__main__._wire_llm_clients and friends.
"""

from __future__ import annotations

from functools import lru_cache

from loguru import logger

from api.config import get_settings
from api.eda.ner import NatashaNer, NerProtocol
from api.llm import CompletionClient, get_completion_client
from api.repository import InMemoryRepository, RepositoryProtocol


@lru_cache(maxsize=1)
def get_ner() -> NerProtocol:
    """First call loads News embeddings + tagger. Heavy; ≈ hundreds of
    MB resident. Shared across EDA and any NER-driven builder so the
    cost is paid once per process.
    """

    return NatashaNer()


def get_llm() -> CompletionClient:
    """Whatever provider the LLM gateway has registered as default —
    Deepseek in dev, Yandex when configured. Indirection so strategy
    factories don't import api.llm.registry directly.
    """

    return get_completion_client()


@lru_cache(maxsize=1)
def get_repository() -> RepositoryProtocol:
    """Process-wide repository singleton.

    Switches between PostgresRepository and InMemoryRepository based on
    settings: a non-empty `postgres.password` means production wiring
    (the docker-compose target). Empty password = in-memory dev/test.
    """

    s = get_settings()
    if s.postgres.password:
        # Lazy import: PostgresRepository imports asyncpg+sqlalchemy, all
        # of which are dev-deps available in the production image.
        from api.repository.postgres import PostgresRepository

        logger.info(
            "wiring PostgresRepository against {}@{}:{}/{}",
            s.postgres.user,
            s.postgres.host,
            s.postgres.port,
            s.postgres.database,
        )
        return PostgresRepository(dsn=s.postgres.dsn)

    logger.info("wiring InMemoryRepository (no POSTGRES__PASSWORD set)")
    return InMemoryRepository()
