"""POST /api/graphs/preview — synchronous, in-memory build pipeline.

Phase 1.5 (preview): no DB, no SSE. Validates registry names, runs
builder → cleaners → clusterer, returns a summary of the resulting
GraphBuildState. Real async + persistence in 1.5.x.
"""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from api.curation.ops import (
    AddEdgePayload,
    DeleteEdgePayload,
    EditEdgePayload,
    MergeNodesPayload,
    MoveToCommunityPayload,
    RetypeNodePayload,
    SetSummaryPayload,
    SplitNodePayload,
    UpdateNodeNamePayload,
)
from api.domain.corpus import Document
from api.domain.curation import JournalEntry, JournalOp
from api.domain.graph import Edge as DomainEdge
from api.domain.graph import GraphVariant, Layer
from api.domain.graph import Node as DomainNode
from api.domain.types import DomainModel, Id, new_id
from api.eda.ner import NerProtocol
from api.llm import CompletionClient
from api.orchestrator import PipelineError, run_build_pipeline
from api.repository import (
    ConcurrentEditError,
    NotFoundError,
    RepositoryError,
    RepositoryProtocol,
)
from api.repository.protocol import JournalAppendResult
from api.runtime import get_ner, get_repository


def _maybe_llm() -> CompletionClient | None:
    """Optional dependency. Returning None means cleaners that require
    an LLM (e.g. llm_dedup) will fail at the orchestrator boundary with
    a clear error rather than at module import.
    """

    try:
        from api.llm import get_completion_client

        return get_completion_client()
    except RuntimeError:
        return None

router = APIRouter(prefix="/api", tags=["graphs"])


class PreviewDocument(DomainModel):
    title: str
    text: str = Field(min_length=1)
    language: str = "ru"


class PreviewRequest(DomainModel):
    corpus_id: Id = Field(default_factory=new_id)
    documents: list[PreviewDocument]
    builder: str
    cleaner_chain: list[str] = Field(default_factory=list)
    clusterer: str | None = None
    builder_params: dict = Field(default_factory=dict)
    cleaner_params: dict[str, dict] = Field(default_factory=dict)
    clusterer_params: dict = Field(default_factory=dict)


class PreviewResponse(DomainModel):
    graph_variant_id: Id
    node_count: int
    edge_count: int
    nodes_by_layer: dict[str, int]
    edges_by_type: dict[str, int]
    journal_size: int
    sample_node_names: list[str]
    """First 10 node names, ordered by layer then alphabetically. Useful
    for a wizard preview without dumping the whole graph."""


@router.post("/graphs/preview", response_model=PreviewResponse)
async def preview_build(
    request: PreviewRequest,
    ner: NerProtocol = Depends(get_ner),
    llm: CompletionClient | None = Depends(_maybe_llm),
) -> PreviewResponse:
    if not request.documents:
        raise HTTPException(status_code=400, detail="documents must be non-empty")

    docs_with_text: list[tuple[Document, str]] = []
    for d in request.documents:
        doc = Document(
            corpus_id=request.corpus_id,
            title=d.title,
            language=d.language,
            char_length=len(d.text),
            sha256="0" * 64,  # stub — real ingest computes this
        )
        docs_with_text.append((doc, d.text))

    try:
        variant_id, state = await run_build_pipeline(
            corpus_id=request.corpus_id,
            documents=docs_with_text,
            builder=request.builder,
            cleaner_chain=request.cleaner_chain,
            clusterer=request.clusterer,
            builder_params=request.builder_params,
            cleaner_params=request.cleaner_params,
            clusterer_params=request.clusterer_params,
            ner=ner,
            llm=llm,
        )
    except PipelineError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e

    nodes_by_layer = Counter(n.layer.value for n in state.nodes)
    edges_by_type = Counter(e.type.value for e in state.edges)

    sorted_nodes = sorted(
        state.nodes, key=lambda n: (_layer_order(n.layer), n.name.lower())
    )
    sample_names = [n.name for n in sorted_nodes[:10]]

    return PreviewResponse(
        graph_variant_id=variant_id,
        node_count=len(state.nodes),
        edge_count=len(state.edges),
        nodes_by_layer=dict(nodes_by_layer),
        edges_by_type=dict(edges_by_type),
        journal_size=len(state.journal),
        sample_node_names=sample_names,
    )


_LAYER_ORDER = {Layer.CHUNK: 0, Layer.ENTITY: 1, Layer.COMMUNITY: 2, Layer.TOPIC: 3}


def _layer_order(layer: Layer) -> int:
    return _LAYER_ORDER.get(layer, 99)


# ---- persisted build + variant CRUD ----


class BuildVariantRequest(DomainModel):
    name: str = Field(min_length=1, max_length=255)
    builder: str
    cleaner_chain: list[str] = Field(default_factory=list)
    clusterer: str | None = None
    builder_params: dict = Field(default_factory=dict)
    cleaner_params: dict[str, dict] = Field(default_factory=dict)
    clusterer_params: dict = Field(default_factory=dict)
    seed: int | None = None


@router.post(
    "/corpora/{corpus_id}/graphs",
    response_model=GraphVariant,
    status_code=201,
)
async def build_variant(
    corpus_id: Id,
    body: BuildVariantRequest,
    repo: RepositoryProtocol = Depends(get_repository),
    ner: NerProtocol = Depends(get_ner),
    llm: CompletionClient | None = Depends(_maybe_llm),
) -> GraphVariant:
    """Build + persist a GraphVariant from documents already in the corpus.

    Phase 2.3: synchronous (no SSE yet); reads document text from
    `metadata['raw_text']` set by POST /corpora/{id}/documents. Phase
    2.x replaces metadata-stashed text with proper blob storage.
    """

    try:
        await repo.get_corpus(corpus_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    docs = await repo.list_documents(corpus_id)
    if not docs:
        raise HTTPException(status_code=400, detail="corpus has no documents")

    docs_with_text: list[tuple[Document, str]] = []
    for d in docs:
        text = d.metadata.get("raw_text")
        if not text:
            raise HTTPException(
                status_code=409,
                detail=f"document {d.id} has no raw_text in metadata",
            )
        docs_with_text.append((d, text))

    variant_id = new_id()
    try:
        _, state = await run_build_pipeline(
            corpus_id=corpus_id,
            documents=docs_with_text,
            builder=body.builder,
            cleaner_chain=body.cleaner_chain,
            clusterer=body.clusterer,
            builder_params=body.builder_params,
            cleaner_params=body.cleaner_params,
            clusterer_params=body.clusterer_params,
            graph_variant_id=variant_id,
            ner=ner,
            llm=llm,
        )
    except PipelineError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e

    variant = GraphVariant(
        id=variant_id,
        corpus_id=corpus_id,
        name=body.name,
        builder=body.builder,
        cleaner_chain=body.cleaner_chain,
        clusterer=body.clusterer,
        config={
            "builder_params": body.builder_params,
            "cleaner_params": body.cleaner_params,
            "clusterer_params": body.clusterer_params,
        },
        seed=body.seed,
    )
    return await repo.create_variant(variant, state)


@router.get("/graphs", response_model=list[GraphVariant])
async def list_variants(
    corpus_id: Id | None = None,
    repo: RepositoryProtocol = Depends(get_repository),
) -> list[GraphVariant]:
    if corpus_id is not None:
        return await repo.list_variants(corpus_id)
    out: list[GraphVariant] = []
    for c in await repo.list_corpora():
        out.extend(await repo.list_variants(c.id))
    return out


@router.get("/graphs/{variant_id}", response_model=GraphVariant)
async def get_variant(
    variant_id: Id,
    repo: RepositoryProtocol = Depends(get_repository),
) -> GraphVariant:
    try:
        return await repo.get_variant(variant_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


class VariantStateResponse(DomainModel):
    variant_id: Id
    version: int
    node_count: int
    edge_count: int
    nodes_by_layer: dict[str, int]
    edges_by_type: dict[str, int]


@router.get("/graphs/{variant_id}/state", response_model=VariantStateResponse)
async def get_variant_state(
    variant_id: Id,
    repo: RepositoryProtocol = Depends(get_repository),
) -> VariantStateResponse:
    try:
        variant = await repo.get_variant(variant_id)
        state = await repo.load_state(variant_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return VariantStateResponse(
        variant_id=variant.id,
        version=variant.version,
        node_count=len(state.nodes),
        edge_count=len(state.edges),
        nodes_by_layer=dict(Counter(n.layer.value for n in state.nodes)),
        edges_by_type=dict(Counter(e.type.value for e in state.edges)),
    )


@router.get("/graphs/{variant_id}/nodes", response_model=list[DomainNode])
async def get_variant_nodes(
    variant_id: Id,
    layer: str | None = None,
    limit: int | None = None,
    repo: RepositoryProtocol = Depends(get_repository),
) -> list[DomainNode]:
    """Materialize the variant's nodes for the layered viewer.

    Phase 6.6.1 — front-end LayeredGraph wraps these and decorates by
    `layer`. `?layer=entity` filters server-side; `?limit=N` caps to N
    so the wizard preview can pull a sample without flooding.
    """

    try:
        state = await repo.load_state(variant_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    nodes = state.nodes
    if layer is not None:
        nodes = [n for n in nodes if n.layer.value == layer]
    if limit is not None:
        nodes = nodes[:limit]
    return nodes


@router.get("/graphs/{variant_id}/edges", response_model=list[DomainEdge])
async def get_variant_edges(
    variant_id: Id,
    type: str | None = None,
    limit: int | None = None,
    repo: RepositoryProtocol = Depends(get_repository),
) -> list[DomainEdge]:
    try:
        state = await repo.load_state(variant_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    edges = state.edges
    if type is not None:
        edges = [e for e in edges if e.type.value == type]
    if limit is not None:
        edges = edges[:limit]
    return edges


# ---- curation ----


_OP_PAYLOAD_MODELS = {
    JournalOp.MERGE_NODES: MergeNodesPayload,
    JournalOp.SPLIT_NODE: SplitNodePayload,
    JournalOp.RETYPE_NODE: RetypeNodePayload,
    JournalOp.MOVE_TO_COMMUNITY: MoveToCommunityPayload,
    JournalOp.EDIT_EDGE: EditEdgePayload,
    JournalOp.DELETE_EDGE: DeleteEdgePayload,
    JournalOp.ADD_EDGE: AddEdgePayload,
    JournalOp.SET_SUMMARY: SetSummaryPayload,
    JournalOp.UPDATE_NODE_NAME: UpdateNodeNamePayload,
}


class JournalAppendRequest(DomainModel):
    op: JournalOp
    payload: dict
    """Op-specific fields. Validated against the model in
    api.curation.ops on the server before any state mutation."""

    expected_version: int = Field(ge=0)
    actor: str = Field(min_length=1)


@router.post(
    "/graphs/{variant_id}/journal",
    response_model=JournalAppendResult,
)
async def append_journal(
    variant_id: Id,
    body: JournalAppendRequest,
    repo: RepositoryProtocol = Depends(get_repository),
) -> JournalAppendResult:
    # Validate the payload schema before reaching the repo so a 422
    # surfaces as a route-level error and the variant version isn't
    # touched on bad input.
    model = _OP_PAYLOAD_MODELS.get(body.op)
    if model is None:
        raise HTTPException(status_code=400, detail=f"unsupported op {body.op}")
    try:
        model.model_validate(body.payload)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"invalid payload: {e}") from e

    entry = JournalEntry(
        graph_variant_id=variant_id,
        op=body.op,
        payload=body.payload,
        actor=body.actor,
    )
    try:
        return await repo.append_journal(
            variant_id, entry, expected_version=body.expected_version, actor=body.actor
        )
    except ConcurrentEditError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(e),
                "expected": e.expected,
                "actual": e.actual,
            },
        ) from e
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get(
    "/graphs/{variant_id}/journal",
    response_model=list[JournalEntry],
)
async def list_journal(
    variant_id: Id,
    limit: int | None = None,
    repo: RepositoryProtocol = Depends(get_repository),
) -> list[JournalEntry]:
    try:
        return await repo.list_journal(variant_id, limit=limit)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


class UndoRequest(DomainModel):
    expected_version: int = Field(ge=0)


@router.post(
    "/graphs/{variant_id}/undo",
    response_model=JournalAppendResult,
)
async def undo_last(
    variant_id: Id,
    body: UndoRequest,
    repo: RepositoryProtocol = Depends(get_repository),
) -> JournalAppendResult:
    try:
        return await repo.revert_last(variant_id, expected_version=body.expected_version)
    except ConcurrentEditError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(e),
                "expected": e.expected,
                "actual": e.actual,
            },
        ) from e
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except RepositoryError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
