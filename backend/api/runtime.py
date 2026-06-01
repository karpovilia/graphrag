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
from api.repository import RepositoryProtocol


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

    Three modes, picked by configuration:

    * `POSTGRES__PASSWORD` set → `PostgresRepository` (production / docker
      compose). If wiring fails (asyncpg import, bad DSN) we fail loud
      rather than silently fall back — losing data on a misconfigured
      restart was the bug that triggered this fix.
    * `POSTGRES__PASSWORD` empty → `SnapshotRepository`, which is the
      in-memory repo plus a JSON snapshot under
      `<storage.data_dir>/state.json`. Survives restarts; intended for
      local dev and the demo loop.
    * Tests can still construct `InMemoryRepository` directly; they don't
      go through `get_repository()`.
    """

    s = get_settings()
    if s.postgres.password:
        # Lazy import: PostgresRepository imports asyncpg+sqlalchemy, all
        # of which are dev-deps available in the production image.
        try:
            from api.db.engine import get_sessionmaker
            from api.repository.postgres import PostgresRepository
        except ImportError as exc:  # pragma: no cover - misconfigured env
            raise RuntimeError(
                "POSTGRES__PASSWORD is set but the PG stack failed to "
                "import (asyncpg / sqlalchemy missing). Either install "
                "the production extras or unset POSTGRES__PASSWORD to "
                "fall back to the on-disk snapshot repository."
            ) from exc

        logger.info(
            "wiring PostgresRepository against {}@{}:{}/{}",
            s.postgres.user,
            s.postgres.host,
            s.postgres.port,
            s.postgres.database,
        )
        return PostgresRepository(sessionmaker=get_sessionmaker())

    # Default local persistence — JSON snapshot, no extra services.
    from api.repository.snapshot import SnapshotRepository

    snapshot_path = s.storage.data_dir / "state.json"
    logger.info(
        "wiring SnapshotRepository at {} (POSTGRES__PASSWORD empty — "
        "data persists across restarts via JSON snapshot)",
        snapshot_path,
    )
    return SnapshotRepository(snapshot_path=snapshot_path)
