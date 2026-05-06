from __future__ import annotations

import asyncio
from collections import defaultdict

from api.curation import affected_set, apply_journal_op
from api.domain.corpus import Corpus, Document
from api.domain.curation import JournalEntry
from api.domain.graph import GraphVariant, Node
from api.domain.types import Id
from api.strategies.state import GraphBuildState

from .errors import ConcurrentEditError, NotFoundError
from .protocol import (
    JournalAppendResult,
    RepositoryProtocol,
    VectorOutboxEntry,
    affected_set_to_dict,
)


class InMemoryRepository(RepositoryProtocol):
    """Dict-backed repository.

    Suitable for tests and small dev runs. Not concurrency-safe across
    tasks unless callers go through `append_journal` (which holds an
    asyncio lock). All other writes assume cooperative single-writer.
    """

    def __init__(self) -> None:
        self._corpora: dict[Id, Corpus] = {}
        self._documents: dict[Id, Document] = {}
        self._variants: dict[Id, GraphVariant] = {}
        self._states: dict[Id, GraphBuildState] = {}
        self._journals: dict[Id, list[JournalEntry]] = defaultdict(list)
        self._outbox: list[VectorOutboxEntry] = []
        self._next_outbox_id = 1
        self._locks: dict[Id, asyncio.Lock] = {}

    # ---- corpora ----

    async def create_corpus(self, corpus: Corpus) -> Corpus:
        self._corpora[corpus.id] = corpus
        return corpus

    async def get_corpus(self, corpus_id: Id) -> Corpus:
        try:
            return self._corpora[corpus_id]
        except KeyError as e:
            raise NotFoundError(f"corpus {corpus_id} not found") from e

    async def list_corpora(self) -> list[Corpus]:
        return list(self._corpora.values())

    # ---- documents ----

    async def create_document(self, document: Document) -> Document:
        if document.corpus_id not in self._corpora:
            raise NotFoundError(f"corpus {document.corpus_id} not found")
        self._documents[document.id] = document
        # Keep the corpus document_count in sync.
        c = self._corpora[document.corpus_id]
        self._corpora[document.corpus_id] = c.model_copy(
            update={"document_count": c.document_count + 1}
        )
        return document

    async def get_document(self, document_id: Id) -> Document:
        try:
            return self._documents[document_id]
        except KeyError as e:
            raise NotFoundError(f"document {document_id} not found") from e

    async def list_documents(self, corpus_id: Id) -> list[Document]:
        return [d for d in self._documents.values() if d.corpus_id == corpus_id]

    # ---- variants ----

    async def create_variant(
        self,
        variant: GraphVariant,
        state: GraphBuildState,
    ) -> GraphVariant:
        if variant.corpus_id not in self._corpora:
            raise NotFoundError(f"corpus {variant.corpus_id} not found")
        # Pin counts from the build state on the variant record.
        layers_present = sorted({n.layer for n in state.nodes})
        stored = variant.model_copy(
            update={
                "node_count": len(state.nodes),
                "edge_count": len(state.edges),
                "layers_present": layers_present,
            }
        )
        self._variants[stored.id] = stored
        self._states[stored.id] = state
        return stored

    async def get_variant(self, variant_id: Id) -> GraphVariant:
        try:
            return self._variants[variant_id]
        except KeyError as e:
            raise NotFoundError(f"variant {variant_id} not found") from e

    async def list_variants(self, corpus_id: Id) -> list[GraphVariant]:
        return [v for v in self._variants.values() if v.corpus_id == corpus_id]

    async def load_state(self, variant_id: Id) -> GraphBuildState:
        try:
            return self._states[variant_id]
        except KeyError as e:
            raise NotFoundError(f"variant state {variant_id} not found") from e

    # ---- curation ----

    async def append_journal(
        self,
        variant_id: Id,
        entry: JournalEntry,
        expected_version: int,
        actor: str | None = None,
    ) -> JournalAppendResult:
        async with self._lock_for(variant_id):
            try:
                variant = self._variants[variant_id]
            except KeyError as e:
                raise NotFoundError(f"variant {variant_id} not found") from e

            if variant.version != expected_version:
                raise ConcurrentEditError(
                    expected=expected_version, actual=variant.version
                )

            state = self._states[variant_id]
            stored_entry = entry.model_copy(
                update={
                    "graph_variant_id": variant_id,
                    "actor": actor or entry.actor,
                }
            )

            affected = affected_set(state, stored_entry)
            new_state = apply_journal_op(state, stored_entry)

            self._states[variant_id] = new_state
            self._journals[variant_id].append(stored_entry)

            new_variant = variant.model_copy(
                update={
                    "version": variant.version + 1,
                    "node_count": len(new_state.nodes),
                    "edge_count": len(new_state.edges),
                    "layers_present": sorted({n.layer for n in new_state.nodes}),
                }
            )
            self._variants[variant_id] = new_variant

            self._enqueue_outbox(variant_id, affected.node_ids, new_state)

            return JournalAppendResult(
                variant=new_variant,
                entry=stored_entry,
                affected=affected_set_to_dict(affected),
            )

    async def list_journal(
        self,
        variant_id: Id,
        *,
        limit: int | None = None,
    ) -> list[JournalEntry]:
        if variant_id not in self._variants:
            raise NotFoundError(f"variant {variant_id} not found")
        entries = list(self._journals[variant_id])
        if limit is not None:
            entries = entries[-limit:]
        return entries

    # ---- outbox ----

    async def list_pending_outbox(
        self,
        *,
        graph_variant_id: Id | None = None,
        limit: int | None = None,
    ) -> list[VectorOutboxEntry]:
        out = self._outbox
        if graph_variant_id is not None:
            out = [o for o in out if o.graph_variant_id == graph_variant_id]
        if limit is not None:
            out = out[:limit]
        return list(out)

    async def ack_outbox(self, ids: list[int]) -> None:
        ack = set(ids)
        self._outbox = [o for o in self._outbox if o.id not in ack]

    # ---- internals ----

    def _lock_for(self, variant_id: Id) -> asyncio.Lock:
        lock = self._locks.get(variant_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[variant_id] = lock
        return lock

    def _enqueue_outbox(
        self,
        variant_id: Id,
        affected_node_ids: frozenset[Id],
        state: GraphBuildState,
    ) -> None:
        if not affected_node_ids:
            return
        models = _models_for(affected_node_ids, state.nodes)
        for model in models:
            entry = VectorOutboxEntry(
                id=self._next_outbox_id,
                graph_variant_id=variant_id,
                embedding_model=model,
                reason="journal_append",
            )
            self._next_outbox_id += 1
            self._outbox.append(entry)


def _models_for(node_ids: frozenset[Id], nodes: list[Node]) -> set[str]:
    out: set[str] = set()
    for n in nodes:
        if n.id in node_ids and n.embedding is not None:
            out.add(n.embedding.model)
    return out
