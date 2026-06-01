"""bi-temporal: valid_*/tx_* stamps, edge invalidation, ingestion events.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-01

Strictly additive + backfill (R2 §0–§2). Adds the four bi-temporal
timestamp columns to nodes and edges, the edges.invalidation JSONB
provenance, and the ingestion_events / snapshots tables that drive the
timeline scrubber. Backfills tx_from on every pre-existing fact from its
variant's created_at so legacy data is visible on any t >= that anchor.
valid_* is left NULL (event-time unknown for legacy rows; T-mode simply
excludes them, documented).
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- nodes/edges temporal columns ----
    for table in ("nodes", "edges"):
        op.add_column(
            table, sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True)
        )
        op.add_column(
            table, sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True)
        )
        op.add_column(
            table, sa.Column("tx_from", sa.DateTime(timezone=True), nullable=True)
        )
        op.add_column(
            table, sa.Column("tx_to", sa.DateTime(timezone=True), nullable=True)
        )

    op.add_column(
        "edges",
        sa.Column("invalidation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.create_index("ix_nodes_tx", "nodes", ["graph_variant_id", "tx_from", "tx_to"])
    op.create_index("ix_edges_tx", "edges", ["graph_variant_id", "tx_from", "tx_to"])

    # ---- ingestion_events ----
    op.create_table(
        "ingestion_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "corpus_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("corpora.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "graph_variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("graph_variants.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("label", sa.String(length=512), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column(
            "kind", sa.String(length=32), nullable=False, server_default="episode"
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.create_index(
        "ix_ingestion_events_event_time", "ingestion_events", ["corpus_id", "event_time"]
    )
    op.create_index(
        "ix_ingestion_events_ingested_at",
        "ingestion_events",
        ["corpus_id", "ingested_at"],
    )

    # ---- snapshots ----
    op.create_table(
        "snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "graph_variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("graph_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=512), nullable=False),
        sa.Column("as_of_tx", sa.DateTime(timezone=True), nullable=True),
        sa.Column("as_of_valid", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "ingestion_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ingestion_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_snapshots_variant", "snapshots", ["graph_variant_id"])

    # ---- backfill tx_from from the variant's created_at ----
    # So every pre-existing fact gets a transaction-time anchor and shows
    # up in any t >= variant.created_at window. valid_* stays NULL.
    for table in ("nodes", "edges"):
        op.execute(
            f"""
            UPDATE {table} AS t
            SET tx_from = v.created_at
            FROM graph_variants AS v
            WHERE v.id = t.graph_variant_id AND t.tx_from IS NULL
            """
        )


def downgrade() -> None:
    op.drop_index("ix_snapshots_variant", table_name="snapshots")
    op.drop_table("snapshots")
    op.drop_index("ix_ingestion_events_ingested_at", table_name="ingestion_events")
    op.drop_index("ix_ingestion_events_event_time", table_name="ingestion_events")
    op.drop_table("ingestion_events")

    op.drop_index("ix_edges_tx", table_name="edges")
    op.drop_index("ix_nodes_tx", table_name="nodes")
    op.drop_column("edges", "invalidation")
    for table in ("nodes", "edges"):
        op.drop_column(table, "tx_to")
        op.drop_column(table, "tx_from")
        op.drop_column(table, "valid_to")
        op.drop_column(table, "valid_from")
