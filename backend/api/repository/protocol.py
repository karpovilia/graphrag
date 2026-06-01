from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import Field

from api.curation.applier import AffectedSet
from api.domain.corpus import Corpus, Document
from api.domain.curation import JournalEntry, Suggestion, SuggestionStatus
from api.domain.graph import GraphLayout, GraphVariant, Node
from api.domain.run import ToolInvocation
from api.domain.temporal import IngestionEvent, TemporalDiff
from api.domain.types import DomainModel, Id, utcnow
from api.domain.user import Language, User
from api.strategies.state import GraphBuildState


class VectorOutboxEntry(DomainModel):
    """Pending FAISS-rebuild trigger. Phase 2.1c writes one row per
    (variant, model) combo affected by a journal append; an async
    vector_writer (out of Phase 2 scope) consumes them with a ~1s
    debounce and rebuilds the per-graph FAISS index.
    """

    id: int | None = None
    graph_variant_id: Id
    embedding_model: str
    reason: str
    created_at: datetime = Field(default_factory=utcnow)


class JournalAppendResult(DomainModel):
    """What the repo returns after a successful journal append. Wraps
    the new variant version + the affected_set so the API handler can
    push the diff to SSE subscribers (Phase 2.x) without re-reading the
    DB.
    """

    variant: GraphVariant
    entry: JournalEntry
    affected: dict
    """AffectedSet serialized as a dict of stringified id sets — Pydantic
    can't transparently nest a dataclass with frozenset[UUID]. The
    repository fills it as
    {'node_ids': [...], 'edge_ids': [...], 'community_ids': [...]}.
    """

    recompute_ms: float = 0.0
    """Actual apply+affected_set wall time (ms) for the §2.3 latency
    badge. Always present and >= 0.0 so the badge never reads undefined."""


def affected_set_to_dict(affected: AffectedSet) -> dict:
    return {
        "node_ids": [str(i) for i in affected.node_ids],
        "edge_ids": [str(i) for i in affected.edge_ids],
        "community_ids": [str(i) for i in affected.community_ids],
    }


@runtime_checkable
class RepositoryProtocol(Protocol):
    """Contract for any storage backend that holds the R2 domain model.

    Methods are async even when the in-memory implementation could be
    sync — the protocol is shared with PostgresRepository which must be
    async.
    """

    # ---- corpora ----

    async def create_corpus(self, corpus: Corpus) -> Corpus: ...

    async def get_corpus(self, corpus_id: Id) -> Corpus: ...

    async def list_corpora(self) -> list[Corpus]: ...

    async def update_corpus(self, corpus: Corpus) -> Corpus: ...
    """Overwrite an existing corpus row (e.g. to attach a schema to
    metadata). Raises NotFoundError if the id doesn't exist."""

    # ---- documents ----

    async def create_document(self, document: Document) -> Document: ...

    async def get_document(self, document_id: Id) -> Document: ...

    async def list_documents(self, corpus_id: Id) -> list[Document]: ...

    # ---- graph variants ----

    async def create_variant(
        self,
        variant: GraphVariant,
        state: GraphBuildState,
    ) -> GraphVariant: ...

    async def get_variant(self, variant_id: Id) -> GraphVariant: ...

    async def list_variants(self, corpus_id: Id) -> list[GraphVariant]: ...

    async def load_state(self, variant_id: Id) -> GraphBuildState: ...
    """Hydrate the full nodes + edges + journal for the variant."""

    # ---- bi-temporal (R2 §2) ----

    async def list_ingestion_events(
        self,
        *,
        corpus_id: Id | None = None,
        variant_id: Id | None = None,
    ) -> list[IngestionEvent]: ...
    """Timeline scrubber axis. Filter by corpus or variant; callers sort
    ascending by ingested_at (axis=tx) or event_time (axis=valid)."""

    async def create_ingestion_event(self, event: IngestionEvent) -> IngestionEvent: ...

    async def materialize_state_at(
        self,
        variant_id: Id,
        t: datetime,
        axis: str,
    ) -> GraphBuildState: ...
    """Facts live at instant `t` under `axis` ('tx' | 'valid'). Default
    impl loads the full state then filters by the temporal predicate."""

    async def temporal_diff(
        self,
        variant_id: Id,
        t_a: datetime,
        t_b: datetime,
        axis: str,
    ) -> TemporalDiff: ...
    """Materialize at t_a and t_b, classify the delta into the §0
    grammar buckets."""

    # ---- curation ----

    async def append_journal(
        self,
        variant_id: Id,
        entry: JournalEntry,
        expected_version: int,
        actor: str | None = None,
    ) -> JournalAppendResult: ...
    """Atomic op: load state, apply entry, persist diff, append entry,
    increment version, write vector_outbox. Raises ConcurrentEditError
    if expected_version doesn't match. `actor` overrides
    `entry.actor` if supplied (route handlers usually authoritatively
    fill from auth context).
    """

    async def list_journal(
        self,
        variant_id: Id,
        *,
        limit: int | None = None,
    ) -> list[JournalEntry]: ...

    async def revert_last(
        self,
        variant_id: Id,
        expected_version: int,
    ) -> JournalAppendResult: ...
    """Pop the last journal entry and recompute state by replaying the
    remaining journal against the variant's base state. Returns the
    result with `entry` set to the entry that was removed so the UI can
    display "undid X". Phase 2.4 limitation: destructive — the popped
    entry is gone from the journal, audit-preserving undo (compensating
    op as a fresh entry) is a follow-up."""

    # ---- suggestions ----

    async def create_suggestions(
        self,
        suggestions: list[Suggestion],
    ) -> list[Suggestion]: ...
    """Bulk-insert. Returns the same list back so callers can chain."""

    async def get_suggestion(self, suggestion_id: Id) -> Suggestion: ...

    async def list_suggestions(
        self,
        graph_variant_id: Id,
        *,
        status: SuggestionStatus | None = None,
        agent: str | None = None,
        limit: int | None = None,
    ) -> list[Suggestion]: ...

    async def accept_suggestion(
        self,
        suggestion_id: Id,
        expected_variant_version: int,
        actor: str,
    ) -> "JournalAppendResult": ...
    """Atomic: load suggestion, map SuggestionAction→JournalOp, append
    journal entry, flip status to accepted, set
    resulting_journal_entry_id. Raises ConcurrentEditError on stale
    version, RepositoryError if the suggestion is already decided or
    the action has no journal mapping."""

    async def reject_suggestion(
        self,
        suggestion_id: Id,
        actor: str,
    ) -> Suggestion: ...

    # ---- node lookup (Phase 5 tools / 6 viewer) ----

    async def find_node(
        self,
        graph_variant_id: Id,
        node_id: Id,
    ) -> Node: ...
    """Convenience over load_state().nodes — Phase 5 tools and the
    side-drawer don't want to materialize the whole state for one node.
    Raises NotFoundError if the node isn't part of the variant."""

    # ---- tool invocations (Phase 5.4) ----

    async def record_tool_invocation(
        self,
        invocation: ToolInvocation,
    ) -> ToolInvocation: ...

    async def list_tool_invocations(
        self,
        node_id: Id,
        *,
        tool: str | None = None,
        limit: int | None = None,
    ) -> list[ToolInvocation]: ...

    # ---- vector outbox ----

    async def list_pending_outbox(
        self,
        *,
        graph_variant_id: Id | None = None,
        limit: int | None = None,
    ) -> list[VectorOutboxEntry]: ...

    async def ack_outbox(self, ids: list[int]) -> None: ...
    """Mark entries consumed by the rebuild worker. In-memory and
    Postgres both implement this as DELETE BY id IN (...)."""

    # ---- graph layouts (cached force-layout positions) ----

    async def upsert_layout(self, layout: GraphLayout) -> GraphLayout: ...
    """Insert or replace by (graph_variant_id, user_id). user_id NULL
    represents the shared global pool that anonymous writes feed and
    that first-time visitors fall back to."""

    async def get_layout(
        self,
        graph_variant_id: Id,
        *,
        user_id: Id | None,
    ) -> GraphLayout | None: ...
    """Returns the caller's own saved layout if present; otherwise the
    most-recently-updated layout for the variant from any user (the
    "fallback" pool). Returns None if no layout has ever been saved."""

    # ---- users ----

    async def create_user(self, user: User) -> User: ...

    async def get_user(self, user_id: Id) -> User: ...

    async def get_user_by_email(self, email: str) -> User: ...
    """Raise NotFoundError if no row matches. Email lookup is case-
    insensitive — the stored value should be lowercased on write."""

    async def update_user_language(self, user_id: Id, language: Language) -> User: ...
