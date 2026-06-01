from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from datetime import datetime

from api.curation import affected_set, apply_journal_op, replay_journal
from api.curation.temporal_diff import materialize_at, temporal_diff
from api.domain.corpus import Corpus, Document
from api.domain.curation import (
    JournalEntry,
    JournalOp,
    Suggestion,
    SuggestionAction,
    SuggestionStatus,
)
from api.domain.graph import GraphLayout, GraphVariant, Node
from api.domain.run import ToolInvocation
from api.domain.temporal import IngestionEvent, TemporalDiff
from api.domain.types import Id, utcnow
from api.domain.user import Language, User
from api.strategies.state import GraphBuildState

from .errors import ConcurrentEditError, NotFoundError, RepositoryError
from .protocol import (
    JournalAppendResult,
    RepositoryProtocol,
    VectorOutboxEntry,
    affected_set_to_dict,
)

_SUGGESTION_TO_JOURNAL_OP: dict[SuggestionAction, JournalOp] = {
    SuggestionAction.MERGE: JournalOp.MERGE_NODES,
    SuggestionAction.SPLIT: JournalOp.SPLIT_NODE,
    SuggestionAction.RETYPE: JournalOp.RETYPE_NODE,
    SuggestionAction.MOVE: JournalOp.MOVE_TO_COMMUNITY,
    SuggestionAction.EDIT_RELATION: JournalOp.EDIT_EDGE,
}
"""SuggestionAction → JournalOp for actions with a 1:1 mapping.

DELETE is special-cased (node vs edge target), and there's no mapping
for SET_SUMMARY-style actions yet — those land in 3.x once the
summarizer plugin can fill in the new summary text."""


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
        self._base_states: dict[Id, GraphBuildState] = {}
        """Immutable post-build snapshot — used by revert_last to replay
        a truncated journal without keeping a per-version state cache."""

        self._journals: dict[Id, list[JournalEntry]] = defaultdict(list)
        self._suggestions: dict[Id, Suggestion] = {}
        self._tool_invocations: dict[Id, list[ToolInvocation]] = defaultdict(list)
        self._outbox: list[VectorOutboxEntry] = []
        self._next_outbox_id = 1
        self._locks: dict[Id, asyncio.Lock] = {}
        self._users: dict[Id, User] = {}
        self._users_by_email: dict[str, Id] = {}
        self._layouts: dict[tuple[Id, Id | None], GraphLayout] = {}
        """Cached force-layout positions keyed by (variant_id, user_id).
        user_id=None is the shared pool used as fallback for visitors
        without a personal layout."""

        self._ingestion_events: dict[Id, IngestionEvent] = {}
        """Bi-temporal timeline units (§2.1) keyed by event id."""

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

    async def update_corpus(self, corpus: Corpus) -> Corpus:
        if corpus.id not in self._corpora:
            raise NotFoundError(f"corpus {corpus.id} not found")
        self._corpora[corpus.id] = corpus
        return corpus

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
        self._base_states[stored.id] = state
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

            _t0 = time.perf_counter()
            affected = affected_set(state, stored_entry)
            new_state = apply_journal_op(state, stored_entry)
            recompute_ms = (time.perf_counter() - _t0) * 1000.0

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
                recompute_ms=recompute_ms,
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

    async def revert_last(
        self,
        variant_id: Id,
        expected_version: int,
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

            journal = self._journals[variant_id]
            if not journal:
                raise RepositoryError("nothing to undo: journal is empty")

            # Compute affected_set against the pre-revert state so the
            # caller knows which embeddings need re-derivation in the
            # rolled-back direction.
            pre_state = self._states[variant_id]
            removed = journal[-1]

            _t0 = time.perf_counter()
            affected = affected_set(pre_state, removed)
            self._journals[variant_id] = journal[:-1]
            base = self._base_states[variant_id]
            new_state = replay_journal(base, self._journals[variant_id])
            recompute_ms = (time.perf_counter() - _t0) * 1000.0
            self._states[variant_id] = new_state

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
                entry=removed,
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
        out = list(self._ingestion_events.values())
        if corpus_id is not None:
            out = [e for e in out if e.corpus_id == corpus_id]
        if variant_id is not None:
            out = [
                e
                for e in out
                if e.graph_variant_id is None or e.graph_variant_id == variant_id
            ]
        return out

    async def create_ingestion_event(self, event: IngestionEvent) -> IngestionEvent:
        self._ingestion_events[event.id] = event
        return event

    async def materialize_state_at(
        self,
        variant_id: Id,
        t: datetime,
        axis: str,
    ) -> GraphBuildState:
        try:
            state = self._states[variant_id]
        except KeyError as e:
            raise NotFoundError(f"variant state {variant_id} not found") from e
        return materialize_at(state, t, axis)  # type: ignore[arg-type]

    async def temporal_diff(
        self,
        variant_id: Id,
        t_a: datetime,
        t_b: datetime,
        axis: str,
    ) -> TemporalDiff:
        try:
            state = self._states[variant_id]
        except KeyError as e:
            raise NotFoundError(f"variant state {variant_id} not found") from e
        state_a = materialize_at(state, t_a, axis)  # type: ignore[arg-type]
        state_b = materialize_at(state, t_b, axis)  # type: ignore[arg-type]
        return temporal_diff(
            state_a,
            state_b,
            axis=axis,  # type: ignore[arg-type]
            variant_id=variant_id,
            t_a=t_a,
            t_b=t_b,
        )

    # ---- node lookup + tool invocations (Phase 5) ----

    async def find_node(
        self,
        graph_variant_id: Id,
        node_id: Id,
    ) -> Node:
        try:
            state = self._states[graph_variant_id]
        except KeyError as e:
            raise NotFoundError(f"variant {graph_variant_id} not found") from e
        for n in state.nodes:
            if n.id == node_id:
                return n
        raise NotFoundError(
            f"node {node_id} not found in variant {graph_variant_id}"
        )

    async def record_tool_invocation(
        self,
        invocation: ToolInvocation,
    ) -> ToolInvocation:
        self._tool_invocations[invocation.node_id].append(invocation)
        return invocation

    async def list_tool_invocations(
        self,
        node_id: Id,
        *,
        tool: str | None = None,
        limit: int | None = None,
    ) -> list[ToolInvocation]:
        out = list(self._tool_invocations.get(node_id, ()))
        if tool is not None:
            out = [i for i in out if i.tool == tool]
        out.sort(key=lambda i: i.created_at, reverse=True)
        if limit is not None:
            out = out[:limit]
        return out

    # ---- suggestions ----

    async def create_suggestions(
        self,
        suggestions: list[Suggestion],
    ) -> list[Suggestion]:
        for s in suggestions:
            if s.graph_variant_id not in self._variants:
                raise NotFoundError(f"variant {s.graph_variant_id} not found")
            self._suggestions[s.id] = s
        return suggestions

    async def get_suggestion(self, suggestion_id: Id) -> Suggestion:
        try:
            return self._suggestions[suggestion_id]
        except KeyError as e:
            raise NotFoundError(f"suggestion {suggestion_id} not found") from e

    async def list_suggestions(
        self,
        graph_variant_id: Id,
        *,
        status: SuggestionStatus | None = None,
        agent: str | None = None,
        limit: int | None = None,
    ) -> list[Suggestion]:
        out = [
            s
            for s in self._suggestions.values()
            if s.graph_variant_id == graph_variant_id
            and (status is None or s.status == status)
            and (agent is None or s.agent == agent)
        ]
        out.sort(key=lambda s: s.created_at)
        if limit is not None:
            out = out[:limit]
        return out

    async def accept_suggestion(
        self,
        suggestion_id: Id,
        expected_variant_version: int,
        actor: str,
    ) -> JournalAppendResult:
        # No outer lock here — append_journal locks per-variant. We only
        # touch self._suggestions[s.id] before/after, both with simple
        # dict ops so cooperative single-writer is enough.
        try:
            suggestion = self._suggestions[suggestion_id]
        except KeyError as e:
            raise NotFoundError(f"suggestion {suggestion_id} not found") from e

        if suggestion.status != SuggestionStatus.PENDING:
            raise RepositoryError(
                f"suggestion {suggestion_id} already {suggestion.status.value}"
            )

        op, payload = _suggestion_to_journal(suggestion)
        entry = JournalEntry(
            graph_variant_id=suggestion.graph_variant_id,
            op=op,
            payload=payload,
            actor=actor,
        )
        result = await self.append_journal(
            suggestion.graph_variant_id,
            entry,
            expected_version=expected_variant_version,
            actor=actor,
        )

        self._suggestions[suggestion_id] = suggestion.model_copy(
            update={
                "status": SuggestionStatus.ACCEPTED,
                "decided_at": utcnow(),
                "resulting_journal_entry_id": result.entry.id,
            }
        )
        return result

    async def reject_suggestion(
        self,
        suggestion_id: Id,
        actor: str,
    ) -> Suggestion:
        try:
            suggestion = self._suggestions[suggestion_id]
        except KeyError as e:
            raise NotFoundError(f"suggestion {suggestion_id} not found") from e

        if suggestion.status != SuggestionStatus.PENDING:
            raise RepositoryError(
                f"suggestion {suggestion_id} already {suggestion.status.value}"
            )

        del actor  # actor is logged at the route layer; no per-suggestion field
        updated = suggestion.model_copy(
            update={
                "status": SuggestionStatus.REJECTED,
                "decided_at": utcnow(),
            }
        )
        self._suggestions[suggestion_id] = updated
        return updated

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

    # ---- graph layouts ----

    async def upsert_layout(self, layout: GraphLayout) -> GraphLayout:
        if layout.graph_variant_id not in self._variants:
            raise NotFoundError(f"variant {layout.graph_variant_id} not found")
        stored = layout.model_copy(update={"updated_at": utcnow()})
        self._layouts[(stored.graph_variant_id, stored.user_id)] = stored
        return stored

    async def get_layout(
        self,
        graph_variant_id: Id,
        *,
        user_id: Id | None,
    ) -> GraphLayout | None:
        # Per-user hit beats the fallback pool every time.
        if user_id is not None:
            mine = self._layouts.get((graph_variant_id, user_id))
            if mine is not None:
                return mine
        # Otherwise: most-recently-updated layout for this variant from
        # any user (including anon writes with user_id=None).
        candidates = [
            v for k, v in self._layouts.items() if k[0] == graph_variant_id
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda lay: lay.updated_at, reverse=True)
        return candidates[0]

    # ---- users ----

    async def create_user(self, user: User) -> User:
        email_key = user.email.lower()
        if email_key in self._users_by_email:
            raise RepositoryError(f"user with email {user.email} already exists")
        stored = user.model_copy(update={"email": email_key})
        self._users[stored.id] = stored
        self._users_by_email[email_key] = stored.id
        return stored

    async def get_user(self, user_id: Id) -> User:
        try:
            return self._users[user_id]
        except KeyError as e:
            raise NotFoundError(f"user {user_id} not found") from e

    async def get_user_by_email(self, email: str) -> User:
        uid = self._users_by_email.get(email.lower())
        if uid is None:
            raise NotFoundError(f"user with email {email} not found")
        return self._users[uid]

    async def update_user_language(self, user_id: Id, language: Language) -> User:
        try:
            u = self._users[user_id]
        except KeyError as e:
            raise NotFoundError(f"user {user_id} not found") from e
        updated = u.model_copy(update={"language": language})
        self._users[user_id] = updated
        return updated

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


def _suggestion_to_journal(suggestion: Suggestion) -> tuple[JournalOp, dict]:
    """Map a Suggestion's action + targets to a JournalOp + payload that
    api.curation.applier can apply. Raises RepositoryError if the
    suggestion needs a follow-up the orchestrator can't supply yet
    (e.g. summary refresh — needs the summarizer plugin from Phase 5).
    """

    if suggestion.action == SuggestionAction.DELETE:
        if suggestion.target_edge_ids:
            return JournalOp.DELETE_EDGE, {
                "edge_id": suggestion.payload.get(
                    "edge_id", str(suggestion.target_edge_ids[0])
                )
            }
        if suggestion.target_node_ids:
            return JournalOp.DELETE_NODE, {
                "node_id": suggestion.payload.get(
                    "node_id", str(suggestion.target_node_ids[0])
                )
            }
        raise RepositoryError(
            f"suggestion {suggestion.id} has DELETE action but no target ids"
        )

    op = _SUGGESTION_TO_JOURNAL_OP.get(suggestion.action)
    if op is None:
        raise RepositoryError(
            f"suggestion {suggestion.id} action {suggestion.action.value} "
            f"has no journal mapping yet"
        )
    return op, dict(suggestion.payload)
