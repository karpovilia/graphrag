"""Conversational curation assistant route.

`POST /graphs/{variant_id}/assistant` takes a free-text instruction, asks the
LLM to plan curation ops, and applies them through the normal journal path
(journalled + undoable). Returns the assistant's reply, what it applied, and
the updated variant so the canvas can refresh.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import Field

from api.assistant import CurationAssistant
from api.assistant.curation_assistant import SchemaAction
from api.domain.curation import JournalEntry
from api.domain.graph import GraphVariant, GraphVariantStatus
from api.domain.types import DomainModel, Id, new_id
from api.llm import CompletionClient
from api.llm.registry import get_completion_client
from api.orchestrator import run_build_pipeline
from api.repository import NotFoundError, RepositoryProtocol
from api.runtime import get_repository

router = APIRouter(prefix="/api", tags=["assistant"])

# Builders that extract against the corpus schema (so a freshly-added type is
# actually picked up). ner_extraction (natasha) uses fixed types, so a schema
# rebuild switches to an LLM schema-guided builder.
_SCHEMA_AWARE_BUILDERS = {"lightrag", "microsoft", "fastrag", "tog3", "llm_extract"}


def _assistant_llm() -> CompletionClient | None:
    """Default completion provider (Deepseek in dev). None if none registered
    — surfaced as a 503 so the UI can tell the user to configure a key."""
    try:
        return get_completion_client()
    except (RuntimeError, KeyError):
        return None


class ChatMessage(DomainModel):
    role: str
    content: str


class AssistantRequest(DomainModel):
    message: str = Field(min_length=1)
    selected_node_ids: list[str] = Field(default_factory=list)
    slice_node_ids: list[str] = Field(default_factory=list)
    """Ids of the nodes currently visible (the "текущий срез") — scopes
    find/highlight. Empty = whole graph."""
    highlighted_node_ids: list[str] = Field(default_factory=list)
    """Ids the assistant highlighted on the previous turn — carried back so a
    follow-up ("слей их всех", "удали этих") resolves «их»/«эти»."""
    history: list[ChatMessage] = Field(default_factory=list)
    expected_version: int = Field(ge=0)
    actor: str = Field(default="user:ui", min_length=1)


class AppliedOp(DomainModel):
    op: str
    payload: dict
    ok: bool
    error: str | None = None


class AssistantResponse(DomainModel):
    message: str
    applied: list[AppliedOp]
    highlight: list[str] = []
    """Node ids to light up on the graph (read-only, from highlight_nodes)."""
    rebuilding: list[str] = []
    """Human notes about background rebuilds the assistant kicked off."""
    variant: GraphVariant
    recompute_ms: float = 0.0


async def _apply_schema_actions(
    repo: RepositoryProtocol,
    variant: GraphVariant,
    actions: list[SchemaAction],
    llm: CompletionClient,
) -> list[str]:
    """Add the requested types to the corpus schema and kick off ONE background
    rebuild of a new variant so the new ontology is extracted. Returns notes."""
    if not actions:
        return []
    corpus = await repo.get_corpus(variant.corpus_id)
    schema = dict(corpus.metadata.get("schema") or {})
    schema.setdefault("entity_types", [])
    schema.setdefault("relation_types", [])
    added: list[str] = []
    for a in actions:
        entry = {"name": a.name, "description": a.description}
        bucket = "entity_types" if a.op == "add_entity_type" else "relation_types"
        if a.op == "add_relation_type":
            entry.update({"domain": [], "range": []})
        if not any(t.get("name") == a.name for t in schema[bucket]):
            schema[bucket].append(entry)
            added.append(f"{a.name} ({'сущность' if bucket == 'entity_types' else 'отношение'})")
    if not added:
        return []
    corpus = corpus.model_copy(
        update={"metadata": {**corpus.metadata, "schema": schema}}
    )
    await repo.update_corpus(corpus)

    builder = variant.builder if variant.builder in _SCHEMA_AWARE_BUILDERS else "lightrag"
    asyncio.create_task(
        _background_rebuild(repo, variant, builder, schema, llm)
    )
    return [
        f"Добавлено в онтологию: {', '.join(added)}. Запущен фоновый пересчёт "
        f"(builder={builder}); новый вариант появится в списке, когда будет готов."
    ]


async def _background_rebuild(
    repo: RepositoryProtocol,
    base: GraphVariant,
    builder: str,
    schema: dict,
    llm: CompletionClient,
) -> None:
    try:
        docs = await repo.list_documents(base.corpus_id)
        docs_with_text = [
            (d, d.text or d.metadata.get("raw_text") or "")
            for d in docs
            if (d.text or d.metadata.get("raw_text"))
        ]
        if not docs_with_text:
            logger.warning("schema rebuild: corpus {} has no document text", base.corpus_id)
            return
        vid = new_id()
        _, state = await run_build_pipeline(
            corpus_id=base.corpus_id,
            documents=docs_with_text,
            builder=builder,
            cleaner_chain=base.cleaner_chain,
            clusterer=base.clusterer,
            builder_params={"schema": schema},
            graph_variant_id=vid,
            llm=llm,
        )
        variant = GraphVariant(
            id=vid,
            corpus_id=base.corpus_id,
            name=f"{base.name} +schema",
            status=GraphVariantStatus.READY,
            builder=builder,
            cleaner_chain=base.cleaner_chain,
            clusterer=base.clusterer,
            completed_at=datetime.now(tz=timezone.utc),
        )
        await repo.create_variant(variant, state)
        logger.info("schema rebuild done: new variant {} ({} nodes)", vid, len(state.nodes))
    except Exception as e:  # noqa: BLE001
        logger.error("schema rebuild failed: {}", e)


@router.post(
    "/graphs/{variant_id}/assistant",
    response_model=AssistantResponse,
)
async def assistant_chat(
    variant_id: Id,
    body: AssistantRequest,
    repo: RepositoryProtocol = Depends(get_repository),
    llm: CompletionClient | None = Depends(_assistant_llm),
) -> AssistantResponse:
    if llm is None:
        raise HTTPException(
            status_code=503,
            detail="no completion provider configured (set DEEPSEEK__API_KEY)",
        )
    try:
        variant = await repo.get_variant(variant_id)
        state = await repo.load_state(variant_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    plan = await CurationAssistant(llm).plan(
        state,
        message=body.message,
        selected_node_ids=body.selected_node_ids,
        slice_node_ids=body.slice_node_ids,
        highlighted_node_ids=body.highlighted_node_ids,
        history=[m.model_dump() for m in body.history],
    )

    applied: list[AppliedOp] = []
    version = body.expected_version
    total_ms = 0.0
    for planned in plan.ops:
        entry = JournalEntry(
            graph_variant_id=variant_id,
            op=planned.op,
            payload=planned.payload,
            actor=body.actor,
        )
        try:
            result = await repo.append_journal(
                variant_id, entry, expected_version=version, actor=body.actor
            )
            variant = result.variant
            version = variant.version
            total_ms += result.recompute_ms
            applied.append(
                AppliedOp(op=planned.op.value, payload=planned.payload, ok=True)
            )
        except Exception as e:  # noqa: BLE001
            # One bad op shouldn't sink the rest — record and move on. The
            # version isn't advanced by a failed apply, so the loop stays
            # consistent for the next op.
            applied.append(
                AppliedOp(
                    op=planned.op.value,
                    payload=planned.payload,
                    ok=False,
                    error=str(e),
                )
            )

    rebuilding = await _apply_schema_actions(repo, variant, plan.schema_actions, llm)

    return AssistantResponse(
        message=plan.message,
        applied=applied,
        highlight=plan.highlight,
        rebuilding=rebuilding,
        variant=variant,
        recompute_ms=total_ms,
    )
