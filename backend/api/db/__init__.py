"""Persistence: SQLAlchemy 2.0 (asyncpg) + Alembic migrations.

The ORM here is a thin storage shim. The domain Pydantic models in
api/domain remain the contract; SQLAlchemy classes only describe the
tables Alembic needs to maintain. No relationship() chains, no business
logic — Phase 1 strategies talk to the DB through repository functions
that round-trip through the domain models.
"""

from .engine import dispose_engine, get_engine, get_sessionmaker
from .models import Base

__all__ = ["Base", "dispose_engine", "get_engine", "get_sessionmaker"]
