"""Alembic environment.

Pulls the DSN from api.config so deployments don't duplicate it. ALEMBIC_DSN
overrides for CI or one-off migration runs against a different DB.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from api.config import get_settings
from api.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _dsn() -> str:
    if env := os.environ.get("ALEMBIC_DSN"):
        return env
    s = get_settings()
    dsn = s.postgres.dsn
    if not dsn.startswith("postgresql+"):
        dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    return dsn


target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL without a live connection — `alembic upgrade head --sql`."""

    context.configure(
        url=_dsn(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_migrations_online_async() -> None:
    cfg = config.get_section(config.config_ini_section) or {}
    cfg["sqlalchemy.url"] = _dsn()
    connectable = async_engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_migrations_online_async())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
