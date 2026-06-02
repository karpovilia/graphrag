"""SQLAlchemy 2.0 / asyncpg implementation of RepositoryProtocol.

Production target. Untested in CI without a running PG; the gated
integration test in tests/test_repository_postgres.py exercises it
when `POSTGRES_INTEGRATION=1` is set in the environment.

The schema is the one from api.db.models (Phase 0.2). This file holds
the row-to-domain conversion + the read-modify-write transactions.
Method semantics match InMemoryRepository so route handlers and tests
stay backend-agnostic.
"""

from __future__ import annotations

import time
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.curation import affected_set, apply_journal_op
from api.curation.temporal_diff import materialize_at
from api.curation.temporal_diff import temporal_diff as _temporal_diff
from api.db import models as orm
from api.domain.corpus import Corpus, Document
from api.domain.curation import JournalEntry
from api.domain.graph import (
    Edge,
    EdgeInvalidation,
    EdgeType,
    GraphLayout,
    GraphVariant,
    GraphVariantStatus,
    Layer,
    Node,
)
from api.domain.temporal import IngestionEvent, TemporalDiff
from api.domain.types import EmbeddingRef, Id, Provenance
from api.domain.types import utcnow as _utcnow
from api.strategies.state import GraphBuildState

from .diff import diff_states
from .errors import ConcurrentEditError, NotFoundError, RepositoryError
from .protocol import (
    JournalAppendResult,
    RepositoryProtocol,
    VectorOutboxEntry,
    affected_set_to_dict,
)


class PostgresRepository(RepositoryProtocol):
    """All write methods open one transaction per call. Curation
    (`append_journal`, `revert_last`) acquires `FOR UPDATE` on the
    variant row to make optimistic-lock checking race-free even under
    multi-worker uvicorn.
    """

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    # ---- corpora ----

    async def create_corpus(self, corpus: Corpus) -> Corpus:
        async with self._sm() as session, session.begin():
            session.add(_corpus_to_row(corpus))
        return corpus

    async def get_corpus(self, corpus_id: Id) -> Corpus:
        async with self._sm() as session:
            row = await session.get(orm.Corpus, corpus_id)
            if row is None:
                raise NotFoundError(f"corpus {corpus_id} not found")
            return _row_to_corpus(row)

    async def list_corpora(self) -> list[Corpus]:
        async with self._sm() as session:
            rows = (await session.execute(select(orm.Corpus))).scalars().all()
            return [_row_to_corpus(r) for r in rows]

    async def update_corpus(self, corpus: Corpus) -> Corpus:
        async with self._sm() as session, session.begin():
            row = await session.get(orm.Corpus, corpus.id)
            if row is None:
                raise NotFoundError(f"corpus {corpus.id} not found")
            row.name = corpus.name
            row.description = corpus.description
            row.language = corpus.language
            row.metadata = corpus.metadata
        return corpus

    # ---- documents ----

    async def create_document(self, document: Document) -> Document:
        async with self._sm() as session, session.begin():
            corpus_row = await session.get(orm.Corpus, document.corpus_id)
            if corpus_row is None:
                raise NotFoundError(f"corpus {document.corpus_id} not found")
            session.add(_document_to_row(document))
            corpus_row.document_count += 1
        return document

    async def get_document(self, document_id: Id) -> Document:
        async with self._sm() as session:
            row = await session.get(orm.Document, document_id)
            if row is None:
                raise NotFoundError(f"document {document_id} not found")
            return _row_to_document(row)

    async def list_documents(self, corpus_id: Id) -> list[Document]:
        async with self._sm() as session:
            rows = (
                await session.execute(
                    select(orm.Document).where(orm.Document.corpus_id == corpus_id)
                )
            ).scalars().all()
            return [_row_to_document(r) for r in rows]

    # ---- variants ----

    async def create_variant(
        self,
        variant: GraphVariant,
        state: GraphBuildState,
    ) -> GraphVariant:
        async with self._sm() as session, session.begin():
            corpus_row = await session.get(orm.Corpus, variant.corpus_id)
            if corpus_row is None:
                raise NotFoundError(f"corpus {variant.corpus_id} not found")

            stored = variant.model_copy(
                update={
                    "node_count": len(state.nodes),
                    "edge_count": len(state.edges),
                    "layers_present": sorted({n.layer for n in state.nodes}),
                }
            )
            session.add(_variant_to_row(stored))
            for n in state.nodes:
                session.add(_node_to_row(n))
            for e in state.edges:
                session.add(_edge_to_row(e))
            for entry in state.journal:
                session.add(_journal_to_row(entry))
            # Phase 2.4 base state for undo: stored as a sibling variant
            # with a sentinel flag in metadata. Postgres doesn't get a
            # separate snapshot table in R2 — we replay against the
            # initial node/edge rows by checking journal cardinality and
            # rebuilding when necessary.
        return stored

    async def get_variant(self, variant_id: Id) -> GraphVariant:
        async with self._sm() as session:
            row = await session.get(orm.GraphVariant, variant_id)
            if row is None:
                raise NotFoundError(f"variant {variant_id} not found")
            return _row_to_variant(row)

    async def list_variants(self, corpus_id: Id) -> list[GraphVariant]:
        async with self._sm() as session:
            rows = (
                await session.execute(
                    select(orm.GraphVariant).where(
                        orm.GraphVariant.corpus_id == corpus_id
                    )
                )
            ).scalars().all()
            return [_row_to_variant(r) for r in rows]

    async def load_state(self, variant_id: Id) -> GraphBuildState:
        async with self._sm() as session:
            variant_row = await session.get(orm.GraphVariant, variant_id)
            if variant_row is None:
                raise NotFoundError(f"variant {variant_id} not found")
            node_rows = (
                await session.execute(
                    select(orm.Node).where(orm.Node.graph_variant_id == variant_id)
                )
            ).scalars().all()
            edge_rows = (
                await session.execute(
                    select(orm.Edge).where(orm.Edge.graph_variant_id == variant_id)
                )
            ).scalars().all()
            journal_rows = (
                await session.execute(
                    select(orm.JournalEntry)
                    .where(orm.JournalEntry.graph_variant_id == variant_id)
                    .order_by(orm.JournalEntry.created_at)
                )
            ).scalars().all()
            return GraphBuildState(
                nodes=[_row_to_node(r) for r in node_rows],
                edges=[_row_to_edge(r) for r in edge_rows],
                journal=[_row_to_journal(r) for r in journal_rows],
            )

    async def replace_state(
        self, variant_id: Id, state: GraphBuildState
    ) -> GraphVariant:
        async with self._sm() as session, session.begin():
            variant_row = await self._lock_variant(session, variant_id)
            before = await self._load_state_in_session(session, variant_id)
            await self._apply_diff(session, variant_id, before, state)
            variant_row.node_count = len(state.nodes)
            variant_row.edge_count = len(state.edges)
            variant_row.layers_present = sorted(
                {n.layer.value for n in state.nodes}
            )
            return _row_to_variant(variant_row)

    # ---- curation ----

    async def append_journal(
        self,
        variant_id: Id,
        entry: JournalEntry,
        expected_version: int,
        actor: str | None = None,
    ) -> JournalAppendResult:
        async with self._sm() as session, session.begin():
            variant_row = await self._lock_variant(session, variant_id)
            if variant_row.version != expected_version:
                raise ConcurrentEditError(
                    expected=expected_version, actual=variant_row.version
                )

            state = await self._load_state_in_session(session, variant_id)
            stored_entry = entry.model_copy(
                update={
                    "graph_variant_id": variant_id,
                    "actor": actor or entry.actor,
                }
            )
            _t0 = time.perf_counter()
            affected = affected_set(state, stored_entry)
            new_state = apply_journal_op(state, stored_entry)
            recompute_ms = (time.perf_counter() - _t0) * 1000.0
            await self._apply_diff(session, variant_id, state, new_state)

            session.add(_journal_to_row(stored_entry))
            variant_row.version += 1
            variant_row.node_count = len(new_state.nodes)
            variant_row.edge_count = len(new_state.edges)
            variant_row.layers_present = sorted(
                {n.layer.value for n in new_state.nodes}
            )

            await self._enqueue_outbox(session, variant_id, affected.node_ids, new_state)

            return JournalAppendResult(
                variant=_row_to_variant(variant_row),
                entry=stored_entry,
                affected=affected_set_to_dict(affected),
                recompute_ms=recompute_ms,
            )

    # ---- bi-temporal (R2 §2) ----

    async def list_ingestion_events(
        self,
        *,
        corpus_id: Id | None = None,
        variant_id: Id | None = None,
    ) -> list[IngestionEvent]:
        async with self._sm() as session:
            stmt = select(orm.IngestionEvent)
            if corpus_id is not None:
                stmt = stmt.where(orm.IngestionEvent.corpus_id == corpus_id)
            if variant_id is not None:
                stmt = stmt.where(
                    (orm.IngestionEvent.graph_variant_id == variant_id)
                    | (orm.IngestionEvent.graph_variant_id.is_(None))
                )
            rows = (await session.execute(stmt)).scalars().all()
            return [_row_to_ingestion_event(r) for r in rows]

    async def create_ingestion_event(self, event: IngestionEvent) -> IngestionEvent:
        async with self._sm() as session, session.begin():
            session.add(_ingestion_event_to_row(event))
        return event

    async def materialize_state_at(
        self,
        variant_id: Id,
        t: datetime,
        axis: str,
    ) -> GraphBuildState:
        state = await self.load_state(variant_id)
        return materialize_at(state, t, axis)  # type: ignore[arg-type]

    async def temporal_diff(
        self,
        variant_id: Id,
        t_a: datetime,
        t_b: datetime,
        axis: str,
    ) -> TemporalDiff:
        state = await self.load_state(variant_id)
        state_a = materialize_at(state, t_a, axis)  # type: ignore[arg-type]
        state_b = materialize_at(state, t_b, axis)  # type: ignore[arg-type]
        return _temporal_diff(
            state_a,
            state_b,
            axis=axis,  # type: ignore[arg-type]
            variant_id=variant_id,
            t_a=t_a,
            t_b=t_b,
        )

    async def list_journal(
        self,
        variant_id: Id,
        *,
        limit: int | None = None,
    ) -> list[JournalEntry]:
        async with self._sm() as session:
            variant_row = await session.get(orm.GraphVariant, variant_id)
            if variant_row is None:
                raise NotFoundError(f"variant {variant_id} not found")
            stmt = (
                select(orm.JournalEntry)
                .where(orm.JournalEntry.graph_variant_id == variant_id)
                .order_by(orm.JournalEntry.created_at)
            )
            rows = (await session.execute(stmt)).scalars().all()
            entries = [_row_to_journal(r) for r in rows]
            if limit is not None:
                entries = entries[-limit:]
            return entries

    async def revert_last(
        self,
        variant_id: Id,
        expected_version: int,
    ) -> JournalAppendResult:
        async with self._sm() as session, session.begin():
            variant_row = await self._lock_variant(session, variant_id)
            if variant_row.version != expected_version:
                raise ConcurrentEditError(
                    expected=expected_version, actual=variant_row.version
                )

            # Phase 2 limitation: PostgresRepository undo needs a
            # base-state snapshot to replay journal[:-1] against. The
            # snapshot table is Phase 2.x — until it lands, undo is only
            # implemented in InMemoryRepository. The variant_id /
            # expected_version arguments stay as-is on the protocol so
            # this method becomes a one-line swap once the snapshot
            # table is in place.
            del variant_id, expected_version  # silence "unused" once raise lands
            raise NotImplementedError(
                "PostgresRepository.revert_last needs a base-state "
                "snapshot table (Phase 2.x). Use InMemoryRepository for "
                "undo-driven workflows or rebuild from corpus."
            )

    # ---- outbox ----

    async def list_pending_outbox(
        self,
        *,
        graph_variant_id: Id | None = None,
        limit: int | None = None,
    ) -> list[VectorOutboxEntry]:
        async with self._sm() as session:
            stmt = select(orm.VectorOutbox).order_by(orm.VectorOutbox.created_at)
            if graph_variant_id is not None:
                stmt = stmt.where(orm.VectorOutbox.graph_variant_id == graph_variant_id)
            if limit is not None:
                stmt = stmt.limit(limit)
            rows = (await session.execute(stmt)).scalars().all()
            return [_row_to_outbox(r) for r in rows]

    async def ack_outbox(self, ids: list[int]) -> None:
        if not ids:
            return
        async with self._sm() as session, session.begin():
            await session.execute(
                delete(orm.VectorOutbox).where(orm.VectorOutbox.id.in_(ids))
            )

    # ---- graph layouts ----

    async def upsert_layout(self, layout: GraphLayout) -> GraphLayout:
        async with self._sm() as session, session.begin():
            variant_row = await session.get(orm.GraphVariant, layout.graph_variant_id)
            if variant_row is None:
                raise NotFoundError(f"variant {layout.graph_variant_id} not found")
            existing = await session.get(
                orm.GraphLayout,
                (layout.graph_variant_id, layout.user_id),
            )
            now = _utcnow()
            if existing is None:
                session.add(
                    orm.GraphLayout(
                        graph_variant_id=layout.graph_variant_id,
                        user_id=layout.user_id,
                        positions=_positions_to_json(layout.positions),
                        updated_at=now,
                    )
                )
            else:
                existing.positions = _positions_to_json(layout.positions)
                existing.updated_at = now
            return layout.model_copy(update={"updated_at": now})

    async def get_layout(
        self,
        graph_variant_id: Id,
        *,
        user_id: Id | None,
    ) -> GraphLayout | None:
        async with self._sm() as session:
            if user_id is not None:
                mine = await session.get(
                    orm.GraphLayout, (graph_variant_id, user_id)
                )
                if mine is not None:
                    return _row_to_layout(mine)
            stmt = (
                select(orm.GraphLayout)
                .where(orm.GraphLayout.graph_variant_id == graph_variant_id)
                .order_by(orm.GraphLayout.updated_at.desc())
                .limit(1)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            return _row_to_layout(row) if row is not None else None

    # ---- users (TODO: ORM table + queries — Phase 7.x. Until then, the
    # Postgres backend doesn't support the auth feature; runtime falls
    # back to SnapshotRepository whenever POSTGRES__PASSWORD is empty.) ----

    async def create_user(self, user):  # type: ignore[override]
        raise NotImplementedError("PostgresRepository.create_user — Phase 7.x")

    async def get_user(self, user_id):  # type: ignore[override]
        raise NotImplementedError("PostgresRepository.get_user — Phase 7.x")

    async def get_user_by_email(self, email):  # type: ignore[override]
        raise NotImplementedError("PostgresRepository.get_user_by_email — Phase 7.x")

    async def update_user_language(self, user_id, language):  # type: ignore[override]
        raise NotImplementedError("PostgresRepository.update_user_language — Phase 7.x")

    # ---- internals ----

    async def _lock_variant(
        self, session: AsyncSession, variant_id: Id
    ) -> orm.GraphVariant:
        stmt = (
            select(orm.GraphVariant)
            .where(orm.GraphVariant.id == variant_id)
            .with_for_update()
        )
        try:
            return (await session.execute(stmt)).scalar_one()
        except NoResultFound as e:
            raise NotFoundError(f"variant {variant_id} not found") from e

    async def _load_state_in_session(
        self, session: AsyncSession, variant_id: Id
    ) -> GraphBuildState:
        node_rows = (
            await session.execute(
                select(orm.Node).where(orm.Node.graph_variant_id == variant_id)
            )
        ).scalars().all()
        edge_rows = (
            await session.execute(
                select(orm.Edge).where(orm.Edge.graph_variant_id == variant_id)
            )
        ).scalars().all()
        return GraphBuildState(
            nodes=[_row_to_node(r) for r in node_rows],
            edges=[_row_to_edge(r) for r in edge_rows],
            journal=[],  # not needed for diff
        )

    async def _apply_diff(
        self,
        session: AsyncSession,
        variant_id: Id,
        before: GraphBuildState,
        after: GraphBuildState,
    ) -> None:
        diff = diff_states(before, after)
        if diff.nodes_removed:
            await session.execute(
                delete(orm.Node).where(orm.Node.id.in_(diff.nodes_removed))
            )
        if diff.edges_removed:
            await session.execute(
                delete(orm.Edge).where(orm.Edge.id.in_(diff.edges_removed))
            )
        for n in diff.nodes_added:
            session.add(_node_to_row(n))
        for e in diff.edges_added:
            session.add(_edge_to_row(e))
        for n in diff.nodes_changed:
            row = await session.get(orm.Node, n.id)
            if row is None:
                # Should not happen unless the diff is stale. Fail loudly.
                raise RepositoryError(f"node {n.id} disappeared mid-update")
            _update_node_row(row, n)
        for e in diff.edges_changed:
            row = await session.get(orm.Edge, e.id)
            if row is None:
                raise RepositoryError(f"edge {e.id} disappeared mid-update")
            _update_edge_row(row, e)

    async def _enqueue_outbox(
        self,
        session: AsyncSession,
        variant_id: Id,
        affected_node_ids: frozenset[Id],
        state: GraphBuildState,
    ) -> None:
        if not affected_node_ids:
            return
        models: set[str] = set()
        for n in state.nodes:
            if n.id in affected_node_ids and n.embedding is not None:
                models.add(n.embedding.model)
        for model in models:
            session.add(
                orm.VectorOutbox(
                    graph_variant_id=variant_id,
                    embedding_model=model,
                    reason="journal_append",
                )
            )


# ---- row <-> domain converters ----


def _corpus_to_row(c: Corpus) -> orm.Corpus:
    return orm.Corpus(
        id=c.id,
        name=c.name,
        description=c.description,
        language=c.language,
        document_count=c.document_count,
        metadata_json=c.metadata,
    )


def _row_to_corpus(r: orm.Corpus) -> Corpus:
    return Corpus(
        id=r.id,
        name=r.name,
        description=r.description,
        language=r.language,
        document_count=r.document_count,
        metadata=r.metadata_json or {},
        created_at=r.created_at,
    )


def _document_to_row(d: Document) -> orm.Document:
    return orm.Document(
        id=d.id,
        corpus_id=d.corpus_id,
        title=d.title,
        source_uri=d.source_uri,
        language=d.language,
        char_length=d.char_length,
        sha256=d.sha256,
        text=d.text,
        metadata_json=d.metadata,
    )


def _row_to_document(r: orm.Document) -> Document:
    return Document(
        id=r.id,
        corpus_id=r.corpus_id,
        title=r.title,
        source_uri=r.source_uri,
        language=r.language,
        char_length=r.char_length,
        sha256=r.sha256,
        text=getattr(r, "text", None),
        metadata=r.metadata_json or {},
        created_at=r.created_at,
    )


def _variant_to_row(v: GraphVariant) -> orm.GraphVariant:
    return orm.GraphVariant(
        id=v.id,
        corpus_id=v.corpus_id,
        name=v.name,
        status=v.status.value,
        builder=v.builder,
        cleaner_chain=list(v.cleaner_chain),
        clusterer=v.clusterer,
        summarizer=v.summarizer,
        config=v.config,
        llm_models=v.llm_models,
        seed=v.seed,
        node_count=v.node_count,
        edge_count=v.edge_count,
        layers_present=[layer.value for layer in v.layers_present],
        parent_variant_id=v.parent_variant_id,
        completed_at=v.completed_at,
    )


def _row_to_variant(r: orm.GraphVariant) -> GraphVariant:
    return GraphVariant(
        id=r.id,
        corpus_id=r.corpus_id,
        name=r.name,
        status=GraphVariantStatus(r.status),
        builder=r.builder,
        cleaner_chain=list(r.cleaner_chain or []),
        clusterer=r.clusterer,
        summarizer=r.summarizer,
        config=r.config or {},
        llm_models=r.llm_models or {},
        seed=r.seed,
        node_count=r.node_count,
        edge_count=r.edge_count,
        layers_present=[Layer(layer) for layer in (r.layers_present or [])],
        parent_variant_id=r.parent_variant_id,
        version=getattr(r, "version", 0),
        created_at=r.created_at,
        completed_at=r.completed_at,
    )


def _node_to_row(n: Node) -> orm.Node:
    embedding = n.embedding
    return orm.Node(
        id=n.id,
        graph_variant_id=n.graph_variant_id,
        canonical_id=n.canonical_id,
        layer=n.layer.value,
        type=n.type,
        granularity=n.granularity,
        name=n.name,
        summary=n.summary,
        attributes=n.attributes,
        provenance=[p.model_dump(mode="json") for p in n.provenance],
        embedding_model=embedding.model if embedding else None,
        embedding_collection=embedding.collection if embedding else None,
        embedding_vector_id=embedding.vector_id if embedding else None,
        valid_from=n.valid_from,
        valid_to=n.valid_to,
        tx_from=n.tx_from,
        tx_to=n.tx_to,
    )


def _row_to_node(r: orm.Node) -> Node:
    embedding: EmbeddingRef | None = None
    if r.embedding_model and r.embedding_collection and r.embedding_vector_id:
        embedding = EmbeddingRef(
            model=r.embedding_model,
            dim=0,  # dim isn't persisted; resolved at lookup time
            collection=r.embedding_collection,
            vector_id=r.embedding_vector_id,
        )
    return Node(
        id=r.id,
        graph_variant_id=r.graph_variant_id,
        canonical_id=r.canonical_id,
        layer=Layer(r.layer),
        type=r.type,
        granularity=r.granularity,
        name=r.name,
        summary=r.summary,
        attributes=r.attributes or {},
        provenance=[Provenance.model_validate(p) for p in (r.provenance or [])],
        embedding=embedding,
        valid_from=r.valid_from,
        valid_to=r.valid_to,
        tx_from=r.tx_from,
        tx_to=r.tx_to,
    )


def _update_node_row(row: orm.Node, n: Node) -> None:
    row.canonical_id = n.canonical_id
    row.layer = n.layer.value
    row.type = n.type
    row.granularity = n.granularity
    row.name = n.name
    row.summary = n.summary
    row.attributes = n.attributes
    row.provenance = [p.model_dump(mode="json") for p in n.provenance]
    row.valid_from = n.valid_from
    row.valid_to = n.valid_to
    row.tx_from = n.tx_from
    row.tx_to = n.tx_to
    if n.embedding:
        row.embedding_model = n.embedding.model
        row.embedding_collection = n.embedding.collection
        row.embedding_vector_id = n.embedding.vector_id
    else:
        row.embedding_model = None
        row.embedding_collection = None
        row.embedding_vector_id = None


def _edge_to_row(e: Edge) -> orm.Edge:
    return orm.Edge(
        id=e.id,
        graph_variant_id=e.graph_variant_id,
        type=e.type.value,
        source_node_id=e.source_node_id,
        target_node_id=e.target_node_id,
        weight=e.weight,
        relation=e.relation,
        explanation=e.explanation,
        provenance=[p.model_dump(mode="json") for p in e.provenance],
        attributes=e.attributes,
        valid_from=e.valid_from,
        valid_to=e.valid_to,
        tx_from=e.tx_from,
        tx_to=e.tx_to,
        invalidation=(
            e.invalidation.model_dump(mode="json") if e.invalidation else None
        ),
    )


def _row_to_edge(r: orm.Edge) -> Edge:
    return Edge(
        id=r.id,
        graph_variant_id=r.graph_variant_id,
        type=EdgeType(r.type),
        source_node_id=r.source_node_id,
        target_node_id=r.target_node_id,
        weight=r.weight,
        relation=r.relation,
        explanation=r.explanation,
        provenance=[Provenance.model_validate(p) for p in (r.provenance or [])],
        attributes=r.attributes or {},
        valid_from=r.valid_from,
        valid_to=r.valid_to,
        tx_from=r.tx_from,
        tx_to=r.tx_to,
        invalidation=(
            EdgeInvalidation.model_validate(r.invalidation) if r.invalidation else None
        ),
    )


def _update_edge_row(row: orm.Edge, e: Edge) -> None:
    row.type = e.type.value
    row.source_node_id = e.source_node_id
    row.target_node_id = e.target_node_id
    row.weight = e.weight
    row.relation = e.relation
    row.explanation = e.explanation
    row.provenance = [p.model_dump(mode="json") for p in e.provenance]
    row.attributes = e.attributes
    row.valid_from = e.valid_from
    row.valid_to = e.valid_to
    row.tx_from = e.tx_from
    row.tx_to = e.tx_to
    row.invalidation = e.invalidation.model_dump(mode="json") if e.invalidation else None


def _ingestion_event_to_row(e: IngestionEvent) -> orm.IngestionEvent:
    return orm.IngestionEvent(
        id=e.id,
        corpus_id=e.corpus_id,
        graph_variant_id=e.graph_variant_id,
        label=e.label,
        event_time=e.event_time,
        ingested_at=e.ingested_at,
        source_uri=e.source_uri,
        kind=e.kind,
        metadata_json=e.metadata,
    )


def _row_to_ingestion_event(r: orm.IngestionEvent) -> IngestionEvent:
    return IngestionEvent(
        id=r.id,
        corpus_id=r.corpus_id,
        graph_variant_id=r.graph_variant_id,
        label=r.label,
        event_time=r.event_time,
        ingested_at=r.ingested_at,
        source_uri=r.source_uri,
        kind=r.kind,
        metadata=r.metadata_json or {},
    )


def _journal_to_row(j: JournalEntry) -> orm.JournalEntry:
    return orm.JournalEntry(
        id=j.id,
        graph_variant_id=j.graph_variant_id,
        op=j.op.value,
        payload=j.payload,
        actor=j.actor,
        parent_entry_id=j.parent_entry_id,
    )


def _row_to_journal(r: orm.JournalEntry) -> JournalEntry:
    from api.domain.curation import JournalOp

    return JournalEntry(
        id=r.id,
        graph_variant_id=r.graph_variant_id,
        op=JournalOp(r.op),
        payload=r.payload or {},
        actor=r.actor,
        parent_entry_id=r.parent_entry_id,
        created_at=r.created_at,
    )


def _row_to_outbox(r: orm.VectorOutbox) -> VectorOutboxEntry:
    return VectorOutboxEntry(
        id=r.id,
        graph_variant_id=r.graph_variant_id,
        embedding_model=r.embedding_model,
        reason=r.reason,
        created_at=r.created_at,
    )


def _positions_to_json(positions: dict[str, tuple[float, float]]) -> dict:
    # Pydantic stores positions as (x, y) tuples; JSONB needs JSON arrays.
    return {k: [v[0], v[1]] for k, v in positions.items()}


def _row_to_layout(r: orm.GraphLayout) -> GraphLayout:
    raw = r.positions or {}
    return GraphLayout(
        graph_variant_id=r.graph_variant_id,
        user_id=r.user_id,
        positions={
            k: (float(v[0]), float(v[1])) for k, v in raw.items() if len(v) >= 2
        },
        updated_at=r.updated_at,
    )
