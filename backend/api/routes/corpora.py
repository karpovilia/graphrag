from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from api.domain.corpus import Corpus, Document
from api.domain.schema import CorpusSchema
from api.domain.temporal import IngestionEvent
from api.domain.types import DomainModel, Id, new_id
from api.eda.schema_proposer import propose_corpus_schema
from api.llm import CompletionClient
from api.repository import NotFoundError, RepositoryProtocol
from api.runtime import get_repository

router = APIRouter(prefix="/api", tags=["corpora"])


def _maybe_llm() -> CompletionClient | None:
    """Optional dep — schema endpoints fail loud with 503 when no LLM
    provider is registered; routes that don't need an LLM still work."""

    try:
        from api.llm import get_completion_client

        return get_completion_client()
    except RuntimeError:
        return None


class CreateCorpusRequest(DomainModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    language: str = "ru"


class CreateDocumentRequest(DomainModel):
    title: str = Field(min_length=1, max_length=1024)
    text: str = Field(min_length=1)
    """Plain text body. The repo records sha256 + char_length; raw text
    is held by callers for now (Phase 0.4 storage layout).
    """

    source_uri: str | None = None
    language: str = "ru"


# ---- corpora ----


@router.post("/corpora", response_model=Corpus, status_code=201)
async def create_corpus(
    body: CreateCorpusRequest,
    repo: RepositoryProtocol = Depends(get_repository),
) -> Corpus:
    corpus = Corpus(
        name=body.name,
        description=body.description,
        language=body.language,
    )
    return await repo.create_corpus(corpus)


@router.get("/corpora", response_model=list[Corpus])
async def list_corpora(
    repo: RepositoryProtocol = Depends(get_repository),
) -> list[Corpus]:
    return await repo.list_corpora()


@router.get("/corpora/{corpus_id}", response_model=Corpus)
async def get_corpus(
    corpus_id: Id,
    repo: RepositoryProtocol = Depends(get_repository),
) -> Corpus:
    try:
        return await repo.get_corpus(corpus_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# ---- documents ----


@router.post(
    "/corpora/{corpus_id}/documents",
    response_model=Document,
    status_code=201,
)
async def create_document(
    corpus_id: Id,
    body: CreateDocumentRequest,
    repo: RepositoryProtocol = Depends(get_repository),
) -> Document:
    try:
        await repo.get_corpus(corpus_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    import hashlib

    sha256 = hashlib.sha256(body.text.encode("utf-8")).hexdigest()
    doc = Document(
        id=new_id(),
        corpus_id=corpus_id,
        title=body.title,
        source_uri=body.source_uri,
        language=body.language,
        char_length=len(body.text),
        sha256=sha256,
        text=body.text,
    )
    return await repo.create_document(doc)


@router.get(
    "/corpora/{corpus_id}/documents",
    response_model=list[Document],
)
async def list_documents(
    corpus_id: Id,
    repo: RepositoryProtocol = Depends(get_repository),
) -> list[Document]:
    try:
        await repo.get_corpus(corpus_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return await repo.list_documents(corpus_id)


@router.get(
    "/corpora/{corpus_id}/documents/{document_id}",
    response_model=Document,
)
async def get_document(
    corpus_id: Id,
    document_id: Id,
    repo: RepositoryProtocol = Depends(get_repository),
) -> Document:
    try:
        doc = await repo.get_document(document_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if doc.corpus_id != corpus_id:
        raise HTTPException(status_code=404, detail="document not found in corpus")
    return doc


# ---- ingestion events (bi-temporal timeline, R2 §2) ----


class CreateIngestionEventRequest(DomainModel):
    label: str = Field(min_length=1)
    event_time: datetime
    """T — episode/publication date (when the fact became true)."""

    ingested_at: datetime
    """T' — build/ingest time (when we learned the fact)."""

    graph_variant_id: Id
    kind: str = "episode"
    source_uri: str | None = None


@router.post(
    "/corpora/{corpus_id}/ingestion-events",
    response_model=IngestionEvent,
    status_code=201,
)
async def create_ingestion_event(
    corpus_id: Id,
    body: CreateIngestionEventRequest,
    repo: RepositoryProtocol = Depends(get_repository),
) -> IngestionEvent:
    """Record one timeline unit (§2.1) and staggered-backfill the linked
    variant's bi-temporal stamps.

    Seed/demo-friendly: no LLM, no build. After creating the event we
    distribute the variant's nodes/edges across N buckets (N = number of
    ingestion events for the variant, sorted by ingested_at) by index;
    each previously-unstamped node/edge gets `tx_from = bucket.ingested_at`
    and `valid_from = bucket.event_time`. Idempotent — only fills NULLs —
    so re-runs and incremental episodes monotonically reveal more of the
    graph as `t` advances on the tx axis.
    """

    try:
        await repo.get_corpus(corpus_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    try:
        variant = await repo.get_variant(body.graph_variant_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if variant.corpus_id != corpus_id:
        raise HTTPException(
            status_code=404,
            detail=f"variant {body.graph_variant_id} not found in corpus {corpus_id}",
        )

    event = IngestionEvent(
        corpus_id=corpus_id,
        graph_variant_id=body.graph_variant_id,
        label=body.label,
        event_time=body.event_time,
        ingested_at=body.ingested_at,
        kind=body.kind,
        source_uri=body.source_uri,
    )
    created = await repo.create_ingestion_event(event)

    # Staggered backfill across all events of this variant.
    events = await repo.list_ingestion_events(
        corpus_id=corpus_id, variant_id=body.graph_variant_id
    )
    events = sorted(events, key=lambda e: e.ingested_at)
    n_buckets = len(events)
    if n_buckets > 0:
        state = await repo.load_state(body.graph_variant_id)

        def _bucket_for(index: int, total: int) -> IngestionEvent:
            # bucket = index * n_buckets // total
            b = (index * n_buckets) // total if total > 0 else 0
            return events[min(b, n_buckets - 1)]

        new_nodes = []
        for i, node in enumerate(state.nodes):
            if node.tx_from is None:
                bucket = _bucket_for(i, len(state.nodes))
                new_nodes.append(
                    node.model_copy(
                        update={
                            "tx_from": bucket.ingested_at,
                            "valid_from": bucket.event_time,
                        }
                    )
                )
            else:
                new_nodes.append(node)

        new_edges = []
        for i, edge in enumerate(state.edges):
            if edge.tx_from is None:
                bucket = _bucket_for(i, len(state.edges))
                new_edges.append(
                    edge.model_copy(
                        update={
                            "tx_from": bucket.ingested_at,
                            "valid_from": bucket.event_time,
                        }
                    )
                )
            else:
                new_edges.append(edge)

        from api.strategies.state import GraphBuildState

        await repo.replace_state(
            body.graph_variant_id,
            GraphBuildState(
                nodes=new_nodes, edges=new_edges, journal=list(state.journal)
            ),
        )

    return created


# ---- schema (entity / relation ontology) ----


class ProposeSchemaRequest(DomainModel):
    sample_size: int = Field(default=20, ge=1, le=100)
    sample_chunk_size: int = Field(default=3000, ge=500, le=8000)
    seed: int = 42


@router.post(
    "/corpora/{corpus_id}/schema/propose",
    response_model=CorpusSchema,
)
async def propose_schema(
    corpus_id: Id,
    body: ProposeSchemaRequest | None = None,
    repo: RepositoryProtocol = Depends(get_repository),
    llm: CompletionClient | None = Depends(_maybe_llm),
) -> CorpusSchema:
    """One-LLM-call ontology proposal. Reads `sample_size` random chunks
    of `sample_chunk_size` chars across the corpus, asks the LLM for a
    draft schema (entity_types + relation_types with domain/range).
    The result is NOT persisted — the wizard shows it for review and
    the user commits via PUT /api/corpora/{id}/schema.
    """

    if llm is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "schema proposal needs an LLM provider — set DEEPSEEK__API_KEY "
                "or YANDEX__* in the backend env"
            ),
        )
    try:
        await repo.get_corpus(corpus_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    docs = await repo.list_documents(corpus_id)
    docs_with_text: list[tuple[Document, str]] = []
    for d in docs:
        text = d.text or d.metadata.get("raw_text")
        if text:
            docs_with_text.append((d, text))
    if not docs_with_text:
        raise HTTPException(
            status_code=400,
            detail="corpus has no documents with text — nothing to sample",
        )

    params = body or ProposeSchemaRequest()
    return await propose_corpus_schema(
        documents=docs_with_text,
        llm=llm,
        sample_size=params.sample_size,
        sample_chunk_size=params.sample_chunk_size,
        seed=params.seed,
    )


@router.get(
    "/corpora/{corpus_id}/schema",
    response_model=CorpusSchema,
)
async def get_schema(
    corpus_id: Id,
    repo: RepositoryProtocol = Depends(get_repository),
) -> CorpusSchema:
    """Return the persisted schema or an empty one (200 + empty arrays)
    if the user hasn't committed one yet. 404 only if the corpus
    itself doesn't exist."""

    try:
        corpus = await repo.get_corpus(corpus_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    raw = corpus.metadata.get("schema")
    if not raw:
        return CorpusSchema()
    return CorpusSchema.model_validate(raw)


@router.put(
    "/corpora/{corpus_id}/schema",
    response_model=CorpusSchema,
)
async def put_schema(
    corpus_id: Id,
    body: CorpusSchema,
    repo: RepositoryProtocol = Depends(get_repository),
) -> CorpusSchema:
    """Commit the user-edited schema. We bump `version` ourselves so the
    client can't accidentally race; the value the client sent is
    discarded. Persistence: rewrite Corpus.metadata.schema and return
    the stored version."""

    try:
        corpus = await repo.get_corpus(corpus_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    existing_raw = corpus.metadata.get("schema") or {}
    existing_version = int(existing_raw.get("version", 0)) if isinstance(existing_raw, dict) else 0
    body_stored = body.model_copy(
        update={
            "version": existing_version + 1,
            "proposed_by": body.proposed_by or "user",
        }
    )
    new_metadata = {**corpus.metadata, "schema": body_stored.model_dump(mode="json")}
    updated = corpus.model_copy(update={"metadata": new_metadata})
    saved = await repo.update_corpus(updated)
    return CorpusSchema.model_validate(saved.metadata["schema"])
