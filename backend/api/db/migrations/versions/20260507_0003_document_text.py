"""document text: move raw_text out of metadata into a dedicated column.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-07

Earlier the ingest route stashed the document body in
`documents.metadata['raw_text']`, which bloated the JSONB column for
every read of the build pipeline. This adds a nullable `text` column
and copies any pre-existing raw_text into it; the metadata key is left
behind for one release as a backwards-compat shim (the route reads
`text` first, falls back to `metadata['raw_text']`).
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("text", sa.Text(), nullable=True),
    )
    # Best-effort backfill from the legacy metadata field. Safe to skip
    # on fresh databases where the key never existed.
    op.execute(
        """
        UPDATE documents
        SET text = metadata ->> 'raw_text'
        WHERE text IS NULL AND metadata ? 'raw_text'
        """
    )


def downgrade() -> None:
    op.drop_column("documents", "text")
