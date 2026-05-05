"""initial: domain tables for R2 (Phase 0.2).

Creates the eleven tables backing the domain model in api/domain plus the
vector_outbox queue from Phase 2.1. No data migration — this is the first
schema; the legacy prompt_histories cache is gone with the legacy app.

Revision ID: 0001
Revises:
Create Date: 2026-05-04
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "corpora",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("language", sa.String(length=8), nullable=False, server_default="ru"),
        sa.Column("document_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "corpus_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("corpora.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("source_uri", sa.Text()),
        sa.Column("language", sa.String(length=8), nullable=False, server_default="ru"),
        sa.Column("char_length", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_documents_corpus_id", "documents", ["corpus_id"])

    op.create_table(
        "document_spans",
        sa.Column("span_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
    )
    op.create_index(
        "ix_document_spans_document_id", "document_spans", ["document_id"]
    )

    op.create_table(
        "graph_variants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "corpus_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("corpora.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("builder", sa.String(length=64), nullable=False),
        sa.Column(
            "cleaner_chain",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("clusterer", sa.String(length=64)),
        sa.Column("summarizer", sa.String(length=64)),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "llm_models",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("seed", sa.BigInteger()),
        sa.Column("node_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("edge_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "layers_present",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "parent_variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("graph_variants.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime()),
    )
    op.create_index("ix_graph_variants_corpus_id", "graph_variants", ["corpus_id"])
    op.create_index("ix_graph_variants_status", "graph_variants", ["status"])

    op.create_table(
        "nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "graph_variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("graph_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("canonical_id", postgresql.UUID(as_uuid=True)),
        sa.Column("layer", sa.String(length=32), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("granularity", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("embedding_model", sa.String(length=64)),
        sa.Column("embedding_collection", sa.String(length=255)),
        sa.Column("embedding_vector_id", sa.String(length=64)),
    )
    op.create_index("ix_nodes_graph_variant_id", "nodes", ["graph_variant_id"])
    op.create_index("ix_nodes_canonical_id", "nodes", ["canonical_id"])
    op.create_index("ix_nodes_layer", "nodes", ["graph_variant_id", "layer"])
    op.create_index("ix_nodes_type", "nodes", ["graph_variant_id", "type"])

    op.create_table(
        "edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "graph_variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("graph_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column(
            "source_node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("weight", sa.Float()),
        sa.Column("relation", sa.String(length=255)),
        sa.Column("explanation", sa.Text()),
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_edges_graph_variant_id", "edges", ["graph_variant_id"])
    op.create_index("ix_edges_source", "edges", ["source_node_id"])
    op.create_index("ix_edges_target", "edges", ["target_node_id"])

    op.create_table(
        "suggestions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "graph_variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("graph_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column(
            "target_node_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "target_edge_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("cost_estimate_tokens", sa.Integer()),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("resulting_journal_entry_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("decided_at", sa.DateTime()),
    )
    op.create_index(
        "ix_suggestions_graph_variant_id", "suggestions", ["graph_variant_id"]
    )
    op.create_index(
        "ix_suggestions_status", "suggestions", ["graph_variant_id", "status"]
    )
    op.create_index("ix_suggestions_agent", "suggestions", ["agent"])

    op.create_table(
        "journal_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "graph_variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("graph_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("op", sa.String(length=64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column(
            "parent_entry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("journal_entries.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_journal_graph_variant_id", "journal_entries", ["graph_variant_id"]
    )
    op.create_index("ix_journal_actor", "journal_entries", ["actor"])

    op.create_table(
        "runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("strategy", sa.String(length=128), nullable=False),
        sa.Column(
            "corpus_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("corpora.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "graph_variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("graph_variants.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("cost_tokens_in", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cost_tokens_out", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cost_currency", sa.String(length=8)),
        sa.Column("cost_amount", sa.Float()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("completed_at", sa.DateTime()),
    )
    op.create_index("ix_runs_status", "runs", ["status"])
    op.create_index("ix_runs_kind", "runs", ["kind"])
    op.create_index("ix_runs_graph_variant_id", "runs", ["graph_variant_id"])

    op.create_table(
        "tool_invocations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool", sa.String(length=128), nullable=False),
        sa.Column(
            "arguments",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("cost_tokens", sa.Integer()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime()),
    )
    op.create_index("ix_tool_invocations_node_id", "tool_invocations", ["node_id"])
    op.create_index("ix_tool_invocations_tool", "tool_invocations", ["tool"])

    op.create_table(
        "vector_outbox",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "graph_variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("graph_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("embedding_model", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_vector_outbox_pending",
        "vector_outbox",
        ["graph_variant_id", "embedding_model", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_vector_outbox_pending", table_name="vector_outbox")
    op.drop_table("vector_outbox")

    op.drop_index("ix_tool_invocations_tool", table_name="tool_invocations")
    op.drop_index("ix_tool_invocations_node_id", table_name="tool_invocations")
    op.drop_table("tool_invocations")

    op.drop_index("ix_runs_graph_variant_id", table_name="runs")
    op.drop_index("ix_runs_kind", table_name="runs")
    op.drop_index("ix_runs_status", table_name="runs")
    op.drop_table("runs")

    op.drop_index("ix_journal_actor", table_name="journal_entries")
    op.drop_index("ix_journal_graph_variant_id", table_name="journal_entries")
    op.drop_table("journal_entries")

    op.drop_index("ix_suggestions_agent", table_name="suggestions")
    op.drop_index("ix_suggestions_status", table_name="suggestions")
    op.drop_index("ix_suggestions_graph_variant_id", table_name="suggestions")
    op.drop_table("suggestions")

    op.drop_index("ix_edges_target", table_name="edges")
    op.drop_index("ix_edges_source", table_name="edges")
    op.drop_index("ix_edges_graph_variant_id", table_name="edges")
    op.drop_table("edges")

    op.drop_index("ix_nodes_type", table_name="nodes")
    op.drop_index("ix_nodes_layer", table_name="nodes")
    op.drop_index("ix_nodes_canonical_id", table_name="nodes")
    op.drop_index("ix_nodes_graph_variant_id", table_name="nodes")
    op.drop_table("nodes")

    op.drop_index("ix_graph_variants_status", table_name="graph_variants")
    op.drop_index("ix_graph_variants_corpus_id", table_name="graph_variants")
    op.drop_table("graph_variants")

    op.drop_index("ix_document_spans_document_id", table_name="document_spans")
    op.drop_table("document_spans")

    op.drop_index("ix_documents_corpus_id", table_name="documents")
    op.drop_table("documents")

    op.drop_table("corpora")
