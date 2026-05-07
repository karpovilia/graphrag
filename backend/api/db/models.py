from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Corpus(Base):
    __tablename__ = "corpora"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="ru")
    document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    corpus_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("corpora.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_uri: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="ru")
    char_length: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_documents_corpus_id", "corpus_id"),)


class DocumentSpan(Base):
    __tablename__ = "document_spans"

    span_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    start: Mapped[int] = mapped_column(Integer, nullable=False)
    end: Mapped[int] = mapped_column(Integer, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (Index("ix_document_spans_document_id", "document_id"),)


class GraphVariant(Base):
    __tablename__ = "graph_variants"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    corpus_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("corpora.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    builder: Mapped[str] = mapped_column(String(64), nullable=False)
    cleaner_chain: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    clusterer: Mapped[str | None] = mapped_column(String(64))
    summarizer: Mapped[str | None] = mapped_column(String(64))
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    llm_models: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    seed: Mapped[int | None] = mapped_column(BigInteger)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    layers_present: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    parent_variant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("graph_variants.id", ondelete="SET NULL"),
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column()

    __table_args__ = (
        Index("ix_graph_variants_corpus_id", "corpus_id"),
        Index("ix_graph_variants_status", "status"),
    )


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    graph_variant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("graph_variants.id", ondelete="CASCADE"),
        nullable=False,
    )
    canonical_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    layer: Mapped[str] = mapped_column(String(32), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    granularity: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    provenance: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    embedding_model: Mapped[str | None] = mapped_column(String(64))
    embedding_collection: Mapped[str | None] = mapped_column(String(255))
    embedding_vector_id: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_nodes_graph_variant_id", "graph_variant_id"),
        Index("ix_nodes_canonical_id", "canonical_id"),
        Index("ix_nodes_layer", "graph_variant_id", "layer"),
        Index("ix_nodes_type", "graph_variant_id", "type"),
    )


class Edge(Base):
    __tablename__ = "edges"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    graph_variant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("graph_variants.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_node_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_node_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    weight: Mapped[float | None] = mapped_column(Float)
    relation: Mapped[str | None] = mapped_column(String(255))
    explanation: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_edges_graph_variant_id", "graph_variant_id"),
        Index("ix_edges_source", "source_node_id"),
        Index("ix_edges_target", "target_node_id"),
    )


class Suggestion(Base):
    __tablename__ = "suggestions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    graph_variant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("graph_variants.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    target_node_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    target_edge_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    cost_estimate_tokens: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    resulting_journal_entry_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column()

    __table_args__ = (
        Index("ix_suggestions_graph_variant_id", "graph_variant_id"),
        Index("ix_suggestions_status", "graph_variant_id", "status"),
        Index("ix_suggestions_agent", "agent"),
    )


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    graph_variant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("graph_variants.id", ondelete="CASCADE"),
        nullable=False,
    )
    op: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_entry_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_journal_graph_variant_id", "graph_variant_id"),
        Index("ix_journal_actor", "actor"),
    )


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    strategy: Mapped[str] = mapped_column(String(128), nullable=False)
    corpus_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("corpora.id", ondelete="SET NULL"),
    )
    graph_variant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("graph_variants.id", ondelete="SET NULL"),
    )
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error: Mapped[str | None] = mapped_column(Text)
    cost_tokens_in: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cost_tokens_out: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cost_currency: Mapped[str | None] = mapped_column(String(8))
    cost_amount: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()

    __table_args__ = (
        Index("ix_runs_status", "status"),
        Index("ix_runs_kind", "kind"),
        Index("ix_runs_graph_variant_id", "graph_variant_id"),
    )


class ToolInvocation(Base):
    __tablename__ = "tool_invocations"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    node_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    tool: Mapped[str] = mapped_column(String(128), nullable=False)
    arguments: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    cost_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column()

    __table_args__ = (
        Index("ix_tool_invocations_node_id", "node_id"),
        Index("ix_tool_invocations_tool", "tool"),
    )


class VectorOutbox(Base):
    """Phase 2.1 outbox — records vector-affecting changes so the FAISS
    rebuilder can debounce and rebuild per-graph indexes. Sized as a
    rolling queue, not a permanent log: rows are deleted after successful
    rebuild.
    """

    __tablename__ = "vector_outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    graph_variant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("graph_variants.id", ondelete="CASCADE"),
        nullable=False,
    )
    embedding_model: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_vector_outbox_pending",
            "graph_variant_id",
            "embedding_model",
            "created_at",
        ),
    )
