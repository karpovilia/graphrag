"""Persistence boundary.

Phase 2.1. RepositoryProtocol is the contract every storage backend
implements; the orchestrator and routes never touch SQLAlchemy or the
in-memory dict directly. Two implementations ship:
  * InMemoryRepository — for tests and in-process dev runs.
  * PostgresRepository — production. Untested in CI without docker;
    integration tests are gated on POSTGRES_INTEGRATION=1.
"""

from .diff import StateDiff, diff_states
from .errors import (
    ConcurrentEditError,
    NotFoundError,
    RepositoryError,
)
from .in_memory import InMemoryRepository
from .postgres import PostgresRepository
from .protocol import RepositoryProtocol, VectorOutboxEntry

__all__ = [
    "ConcurrentEditError",
    "InMemoryRepository",
    "NotFoundError",
    "PostgresRepository",
    "RepositoryError",
    "RepositoryProtocol",
    "StateDiff",
    "VectorOutboxEntry",
    "diff_states",
]
