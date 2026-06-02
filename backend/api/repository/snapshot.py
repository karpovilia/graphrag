"""JSON-snapshot persistence wrapper around InMemoryRepository.

The pragmatic local-default for R2: full process-state survives restarts
without standing up Postgres. Every write method delegates to
`InMemoryRepository`, then dumps the relevant collections to a single
JSON file under `STORAGE__DATA_DIR`. Startup loads that file (if any)
back into the same in-memory dicts.

This is deliberately the dumbest thing that works — no SQLite, no
SQLAlchemy, no migrations. Production deploys still want
`PostgresRepository` (POSTGRES__PASSWORD set), but the dev/demo loop
("uvicorn, click stuff, kill it, come back tomorrow") doesn't lose
data anymore.

Concurrency: writes are serialized through a single asyncio.Lock so two
journal appends to different variants don't race the snapshot file.
The cost is small — snapshots are O(state size) JSON dumps (~ms for
podcast-sized graphs).
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from loguru import logger

from api.domain.corpus import Corpus, Document
from api.domain.curation import JournalEntry, Suggestion
from api.domain.graph import Edge, GraphLayout, GraphVariant, Node
from api.domain.run import ToolInvocation
from api.domain.temporal import IngestionEvent
from api.domain.types import Id
from api.domain.user import Language, User
from api.strategies.state import GraphBuildState

from .in_memory import InMemoryRepository
from .protocol import JournalAppendResult, VectorOutboxEntry


class SnapshotRepository(InMemoryRepository):
    """InMemoryRepository + atomic JSON dump on every write.

    Inherits all read/write semantics; only adds `_snapshot()` calls and
    an `_load()` that hydrates on construction. The snapshot path lives
    at `<data_dir>/state.json`.
    """

    def __init__(self, snapshot_path: Path) -> None:
        super().__init__()
        self._snapshot_path = snapshot_path
        self._snapshot_lock = asyncio.Lock()
        self._load_sync()

    # ---- corpora / documents ----

    async def create_corpus(self, corpus: Corpus) -> Corpus:
        out = await super().create_corpus(corpus)
        await self._snapshot()
        return out

    async def update_corpus(self, corpus: Corpus) -> Corpus:
        out = await super().update_corpus(corpus)
        await self._snapshot()
        return out

    async def create_document(self, document: Document) -> Document:
        out = await super().create_document(document)
        await self._snapshot()
        return out

    # ---- variants ----

    async def create_variant(
        self,
        variant: GraphVariant,
        state: GraphBuildState,
    ) -> GraphVariant:
        out = await super().create_variant(variant, state)
        await self._snapshot()
        return out

    async def replace_state(
        self, variant_id: Id, state: GraphBuildState
    ) -> GraphVariant:
        out = await super().replace_state(variant_id, state)
        await self._snapshot()
        return out

    # ---- curation ----

    async def append_journal(
        self,
        variant_id: Id,
        entry: JournalEntry,
        expected_version: int,
        actor: str | None = None,
    ) -> JournalAppendResult:
        out = await super().append_journal(variant_id, entry, expected_version, actor)
        await self._snapshot()
        return out

    async def revert_last(
        self,
        variant_id: Id,
        expected_version: int,
    ) -> JournalAppendResult:
        out = await super().revert_last(variant_id, expected_version)
        await self._snapshot()
        return out

    # ---- ingestion events ----

    async def create_ingestion_event(self, event: IngestionEvent) -> IngestionEvent:
        out = await super().create_ingestion_event(event)
        await self._snapshot()
        return out

    # ---- suggestions ----

    async def create_suggestions(
        self,
        suggestions: list[Suggestion],
    ) -> list[Suggestion]:
        out = await super().create_suggestions(suggestions)
        await self._snapshot()
        return out

    async def accept_suggestion(
        self,
        suggestion_id: Id,
        expected_variant_version: int,
        actor: str,
    ) -> JournalAppendResult:
        # super().accept_suggestion calls append_journal internally,
        # which already snapshots. One more snapshot for the suggestion
        # status flip is fine (idempotent overwrite).
        out = await super().accept_suggestion(
            suggestion_id, expected_variant_version, actor
        )
        await self._snapshot()
        return out

    async def reject_suggestion(
        self,
        suggestion_id: Id,
        actor: str,
    ) -> Suggestion:
        out = await super().reject_suggestion(suggestion_id, actor)
        await self._snapshot()
        return out

    # ---- tool invocations ----

    async def record_tool_invocation(
        self,
        invocation: ToolInvocation,
    ) -> ToolInvocation:
        out = await super().record_tool_invocation(invocation)
        await self._snapshot()
        return out

    # ---- outbox ----

    async def ack_outbox(self, ids: list[int]) -> None:
        await super().ack_outbox(ids)
        await self._snapshot()

    # ---- graph layouts ----

    async def upsert_layout(self, layout: GraphLayout) -> GraphLayout:
        out = await super().upsert_layout(layout)
        await self._snapshot()
        return out

    # ---- users ----

    async def create_user(self, user: User) -> User:
        out = await super().create_user(user)
        await self._snapshot()
        return out

    async def update_user_language(self, user_id: Id, language: Language) -> User:
        out = await super().update_user_language(user_id, language)
        await self._snapshot()
        return out

    # ---- snapshot I/O ----

    async def _snapshot(self) -> None:
        async with self._snapshot_lock:
            payload = self._dump_payload()
            await asyncio.to_thread(_atomic_write_json, self._snapshot_path, payload)

    def _dump_payload(self) -> dict[str, Any]:
        return {
            "version": 1,
            "corpora": [c.model_dump(mode="json") for c in self._corpora.values()],
            "documents": [d.model_dump(mode="json") for d in self._documents.values()],
            "variants": [v.model_dump(mode="json") for v in self._variants.values()],
            "states": {
                str(vid): _state_to_json(state)
                for vid, state in self._states.items()
            },
            "base_states": {
                str(vid): _state_to_json(state)
                for vid, state in self._base_states.items()
            },
            "journals": {
                str(vid): [e.model_dump(mode="json") for e in entries]
                for vid, entries in self._journals.items()
            },
            "suggestions": [s.model_dump(mode="json") for s in self._suggestions.values()],
            "tool_invocations": {
                str(nid): [i.model_dump(mode="json") for i in invs]
                for nid, invs in self._tool_invocations.items()
            },
            "outbox": [o.model_dump(mode="json") for o in self._outbox],
            "next_outbox_id": self._next_outbox_id,
            "users": [u.model_dump(mode="json") for u in self._users.values()],
            "layouts": [lay.model_dump(mode="json") for lay in self._layouts.values()],
            "ingestion_events": [
                e.model_dump(mode="json") for e in self._ingestion_events.values()
            ],
        }

    def _load_sync(self) -> None:
        if not self._snapshot_path.exists():
            logger.info(
                "snapshot {} not found — starting with empty state",
                self._snapshot_path,
            )
            return
        try:
            with self._snapshot_path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error(
                "failed to load snapshot {}: {} — starting empty (file kept as .corrupt)",
                self._snapshot_path,
                exc,
            )
            try:
                self._snapshot_path.rename(
                    self._snapshot_path.with_suffix(self._snapshot_path.suffix + ".corrupt")
                )
            except OSError:
                pass
            return

        for c in payload.get("corpora", []):
            corpus = Corpus.model_validate(c)
            self._corpora[corpus.id] = corpus
        for d in payload.get("documents", []):
            doc = Document.model_validate(d)
            self._documents[doc.id] = doc
        for v in payload.get("variants", []):
            variant = GraphVariant.model_validate(v)
            self._variants[variant.id] = variant
        for vid, raw in payload.get("states", {}).items():
            self._states[Id(_uuid(vid))] = _state_from_json(raw)
        for vid, raw in payload.get("base_states", {}).items():
            self._base_states[Id(_uuid(vid))] = _state_from_json(raw)
        for vid, entries in payload.get("journals", {}).items():
            self._journals[Id(_uuid(vid))] = [
                JournalEntry.model_validate(e) for e in entries
            ]
        for s in payload.get("suggestions", []):
            sug = Suggestion.model_validate(s)
            self._suggestions[sug.id] = sug
        for nid, invs in payload.get("tool_invocations", {}).items():
            self._tool_invocations[Id(_uuid(nid))] = [
                ToolInvocation.model_validate(i) for i in invs
            ]
        for o in payload.get("outbox", []):
            self._outbox.append(VectorOutboxEntry.model_validate(o))
        self._next_outbox_id = int(payload.get("next_outbox_id", 1))
        for u in payload.get("users", []):
            user = User.model_validate(u)
            self._users[user.id] = user
            self._users_by_email[user.email.lower()] = user.id
        for lay_raw in payload.get("layouts", []):
            lay = GraphLayout.model_validate(lay_raw)
            self._layouts[(lay.graph_variant_id, lay.user_id)] = lay
        for ev_raw in payload.get("ingestion_events", []):
            ev = IngestionEvent.model_validate(ev_raw)
            self._ingestion_events[ev.id] = ev
        logger.info(
            "snapshot loaded: {} corpora, {} documents, {} variants, "
            "{} suggestions, {} outbox, {} ingestion-events",
            len(self._corpora),
            len(self._documents),
            len(self._variants),
            len(self._suggestions),
            len(self._outbox),
            len(self._ingestion_events),
        )


# ---- helpers ----


def _uuid(s: str):
    from uuid import UUID

    return UUID(s)


def _state_to_json(state: GraphBuildState) -> dict[str, Any]:
    return {
        "nodes": [n.model_dump(mode="json") for n in state.nodes],
        "edges": [e.model_dump(mode="json") for e in state.edges],
        "journal": [e.model_dump(mode="json") for e in state.journal],
    }


def _state_from_json(raw: dict[str, Any]) -> GraphBuildState:
    return GraphBuildState(
        nodes=[Node.model_validate(n) for n in raw.get("nodes", [])],
        edges=[Edge.model_validate(e) for e in raw.get("edges", [])],
        journal=[JournalEntry.model_validate(j) for j in raw.get("journal", [])],
    )


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write to a sibling tmp file and rename — survives crashes mid-write."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# Silence linter: defaultdict import only used through inherited dict access.
_ = defaultdict
