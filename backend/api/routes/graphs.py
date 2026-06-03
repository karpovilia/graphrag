"""POST /api/graphs/preview — synchronous, in-memory build pipeline.

Phase 1.5 (preview): no DB, no SSE. Validates registry names, runs
builder → cleaners → clusterer, returns a summary of the resulting
GraphBuildState. Real async + persistence in 1.5.x.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

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
from api.auth.dependency import optional_user
from api.domain.corpus import Document
from api.domain.curation import JournalEntry, JournalOp
from api.domain.graph import Edge as DomainEdge
from api.domain.graph import EdgeType, GraphLayout, GraphVariant, Layer
from api.domain.graph import Node as DomainNode
from api.domain.types import DomainModel, Id, new_id
from api.domain.user import User
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


class LLMOverride(DomainModel):
    """User-supplied OpenAI-compatible endpoint for this single build.

    Lives only in the request body — never persisted. The route
    instantiates a one-shot OpenAICompatClient with these values and
    discards it once the pipeline returns. Works for hosted providers
    (OpenAI / Deepseek / OpenRouter / …) and local servers exposing the
    same wire protocol (Ollama, vLLM, llama.cpp, LM Studio)."""

    api_key: str = ""
    """Optional for local servers that don't authenticate (Ollama,
    llama.cpp). Hosted providers will 401 on empty."""

    base_url: str = Field(min_length=1, max_length=512)
    model: str = Field(min_length=1, max_length=128)


class BuildVariantRequest(DomainModel):
    name: str = Field(min_length=1, max_length=255)
    builder: str
    cleaner_chain: list[str] = Field(default_factory=list)
    clusterer: str | None = None
    builder_params: dict = Field(default_factory=dict)
    cleaner_params: dict[str, dict] = Field(default_factory=dict)
    clusterer_params: dict = Field(default_factory=dict)
    projector: str | None = None
    """Optional post-clusterer stage that derives intra-layer co-occurrence
    edges (`BACKBONE` type) using cross-layer evidence + a disparity
    filter. See `/api/projectors` for available strategies."""
    projector_params: dict = Field(default_factory=dict)
    seed: int | None = None
    output_language: str = Field(
        default="ru",
        description=(
            "Language used to normalise entity names and generate "
            "summaries. Falls back to corpus.language if absent. "
            "Pipelines that don't yet honour this setting can read it "
            "from builder_params['output_language']."
        ),
    )
    llm_override: LLMOverride | None = None
    """When present, the pipeline talks to this user-supplied endpoint
    instead of the server-default LLM. Used by the wizard's
    bring-your-own-token form (incl. local OpenAI-compatible servers)."""


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

    Phase 2.3: synchronous (no SSE yet); reads document text from the
    Document.text field (preferred) and falls back to
    `metadata['raw_text']` for legacy documents created before that
    field existed.
    """

    try:
        corpus = await repo.get_corpus(corpus_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    docs = await repo.list_documents(corpus_id)
    if not docs:
        raise HTTPException(status_code=400, detail="corpus has no documents")

    docs_with_text: list[tuple[Document, str]] = []
    for d in docs:
        text = d.text or d.metadata.get("raw_text")
        if not text:
            raise HTTPException(
                status_code=409,
                detail=f"document {d.id} has no text body",
            )
        docs_with_text.append((d, text))

    variant_id = new_id()
    # Inject output_language into builder_params so strategies that wire
    # in language-aware NER / summary backends can read it without a new
    # pipeline-level argument. Caller-supplied builder_params win.
    builder_params = {
        "output_language": body.output_language,
        **body.builder_params,
    }
    # Auto-attach the corpus schema (if the user has committed one
    # via PUT /api/corpora/{id}/schema) so LightRAG/Microsoft builders
    # extract against the typed ontology. The wizard can override by
    # passing `schema` (or `entity_types`/`relation_types`) directly
    # in builder_params.
    if "schema" not in builder_params and "entity_types" not in builder_params:
        corpus_schema = corpus.metadata.get("schema")
        if corpus_schema:
            builder_params["schema"] = corpus_schema
    # Optional per-build LLM override — pasted in the wizard, never
    # persisted. Wins over the server default; falls through when the
    # field is absent (existing behavior unchanged).
    effective_llm = llm
    if body.llm_override is not None:
        from api.llm.openai_compat import OpenAICompatClient

        effective_llm = OpenAICompatClient(
            api_key=body.llm_override.api_key,
            base_url=body.llm_override.base_url,
            default_model=body.llm_override.model,
        )
    try:
        _, state = await run_build_pipeline(
            corpus_id=corpus_id,
            documents=docs_with_text,
            builder=body.builder,
            cleaner_chain=body.cleaner_chain,
            clusterer=body.clusterer,
            builder_params=builder_params,
            cleaner_params=body.cleaner_params,
            clusterer_params=body.clusterer_params,
            projector=body.projector,
            projector_params=body.projector_params,
            graph_variant_id=variant_id,
            ner=ner,
            llm=effective_llm,
        )
    except PipelineError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e

    from datetime import datetime, timezone

    from api.domain.graph import GraphVariantStatus

    variant = GraphVariant(
        id=variant_id,
        corpus_id=corpus_id,
        name=body.name,
        # The pipeline ran synchronously above; if we got here it succeeded,
        # so the variant is ready by definition. Async pipelines (Phase 1.5.x
        # SSE wiring) flip this back to BUILDING + a Run row drives status.
        status=GraphVariantStatus.READY,
        builder=body.builder,
        cleaner_chain=body.cleaner_chain,
        clusterer=body.clusterer,
        config={
            "builder_params": body.builder_params,
            "cleaner_params": body.cleaner_params,
            "clusterer_params": body.clusterer_params,
            "projector": body.projector,
            "projector_params": body.projector_params,
        },
        seed=body.seed,
        completed_at=datetime.now(tz=timezone.utc),
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


# ---- layout cache (force-directed positions) ----


class LayoutResponse(DomainModel):
    positions: dict[str, tuple[float, float]]
    owner: str
    """'self' when the row belongs to the calling user, 'global' when it
    was served from the shared fallback pool. UI uses this to decide
    whether to save back immediately (skip self-write of an identical
    payload) or treat the load as a one-time seed."""


class LayoutPutRequest(DomainModel):
    positions: dict[str, tuple[float, float]] = Field(default_factory=dict)


@router.get(
    "/graphs/{variant_id}/layout",
    response_model=LayoutResponse,
)
async def get_variant_layout(
    variant_id: Id,
    user: User | None = Depends(optional_user),
    repo: RepositoryProtocol = Depends(get_repository),
) -> LayoutResponse:
    try:
        await repo.get_variant(variant_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    layout = await repo.get_layout(
        variant_id,
        user_id=user.id if user is not None else None,
    )
    if layout is None:
        # Empty payload signals "no cached layout exists" — the UI will
        # let d3-force run from scratch and then PUT the result back.
        return LayoutResponse(positions={}, owner="global")
    owner = (
        "self"
        if user is not None and layout.user_id == user.id
        else "global"
    )
    return LayoutResponse(positions=layout.positions, owner=owner)


@router.put(
    "/graphs/{variant_id}/layout",
    response_model=LayoutResponse,
)
async def put_variant_layout(
    variant_id: Id,
    body: LayoutPutRequest,
    user: User | None = Depends(optional_user),
    repo: RepositoryProtocol = Depends(get_repository),
) -> LayoutResponse:
    try:
        await repo.get_variant(variant_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    stored = await repo.upsert_layout(
        GraphLayout(
            graph_variant_id=variant_id,
            user_id=user.id if user is not None else None,
            positions=body.positions,
        )
    )
    return LayoutResponse(
        positions=stored.positions,
        owner="self" if user is not None else "global",
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

    payload = dict(body.payload)
    # Soft DELETE_EDGE linked to an ingestion event: stamp the death
    # instant from that event's ingested_at so tx_to lands inside the
    # historical tx window (not "now"). Unknown event id → leave None,
    # the applier falls back to the entry timestamp.
    if body.op == JournalOp.DELETE_EDGE and payload.get("ingestion_event_id"):
        events = await repo.list_ingestion_events()
        event = next(
            (e for e in events if str(e.id) == str(payload["ingestion_event_id"])),
            None,
        )
        if event is not None:
            payload["superseded_at"] = event.ingested_at.isoformat()

    entry = JournalEntry(
        graph_variant_id=variant_id,
        op=body.op,
        payload=payload,
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


# ---- LLM-driven node resummarize ----


class ResummarizeResponse(DomainModel):
    summary: str
    model: str
    snippet_count: int
    """How many provenance snippets we fed the LLM. Surfaced for the
    operator so they can spot 'summarised on 0 spans' and not save."""


_RESUMMARIZE_SYSTEM = (
    "You write concise factual summaries of knowledge-graph entities. "
    "Always answer in the same language as the source excerpts. "
    "2-4 sentences, no bullet lists, no preamble like 'This entity is…'."
)


def _mentioned_chunk_ids(state, node_id: Id) -> list[str]:
    """Chunk-node ids linked to a node by a MENTIONED_IN edge (either
    direction — the builder emits entity→chunk, but accept both)."""
    nid = str(node_id)
    chunk_ids: list[str] = []
    seen: set[str] = set()
    for e in state.edges:
        if e.type != EdgeType.MENTIONED_IN:
            continue
        src, tgt = str(e.source_node_id), str(e.target_node_id)
        other = tgt if src == nid else src if tgt == nid else None
        if other is not None and other not in seen:
            seen.add(other)
            chunk_ids.append(other)
    return chunk_ids


def _snippet(text: str, start: int, end: int, pad: int = 120) -> str:
    """Carve out the span with a little context on both sides so the LLM
    sees the entity in its sentence, not just the mention."""

    lo = max(0, start - pad)
    hi = min(len(text), end + pad)
    return text[lo:hi].strip()


@router.post(
    "/graphs/{variant_id}/nodes/{node_id}/resummarize",
    response_model=ResummarizeResponse,
)
async def resummarize_node(
    variant_id: Id,
    node_id: Id,
    repo: RepositoryProtocol = Depends(get_repository),
    llm: CompletionClient | None = Depends(_maybe_llm),
) -> ResummarizeResponse:
    """Generate a new summary draft for a node using the provenance
    spans as context, WITHOUT writing to the journal — the UI shows it
    in the summary editor and the operator decides whether to persist
    via the standard set_summary curation op (one user gesture = one
    journal entry, no auto-commit)."""

    if llm is None:
        raise HTTPException(
            status_code=503,
            detail="no LLM provider configured — set DEEPSEEK__API_KEY",
        )

    try:
        variant = await repo.get_variant(variant_id)
        state = await repo.load_state(variant_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    node = next((n for n in state.nodes if str(n.id) == str(node_id)), None)
    if node is None:
        raise HTTPException(status_code=404, detail=f"node {node_id} not found")

    # Entity nodes carry no spans of their own — their evidence lives on the
    # chunk nodes they're MENTIONED_IN. Gather the node's own provenance plus
    # the provenance of every chunk it's linked to, so summaries work for
    # entities (not just chunks).
    spans = list(node.provenance)
    chunk_ids = _mentioned_chunk_ids(state, node_id)
    chunks_by_id = {str(n.id): n for n in state.nodes if str(n.id) in chunk_ids}
    for cid in chunk_ids:
        ch = chunks_by_id.get(cid)
        if ch is not None:
            spans.extend(ch.provenance)
    if not spans:
        raise HTTPException(
            status_code=409,
            detail="node has no provenance spans (no own spans, no linked chunks)",
        )

    docs = await repo.list_documents(variant.corpus_id)
    docs_by_id = {str(d.id): d for d in docs}

    snippets: list[str] = []
    for p in spans[:12]:
        doc = docs_by_id.get(str(p.document_id))
        if doc is None or not doc.text:
            continue
        snippets.append(_snippet(doc.text, p.span_start, p.span_end))
    if not snippets:
        raise HTTPException(
            status_code=409,
            detail="provenance documents have no readable text",
        )

    from api.llm.base import CompletionParams, Message

    user_text = (
        f"Entity name: {node.name}\n"
        f"Entity type: {node.type}\n"
        f"Source excerpts (separated by ---):\n\n"
        + "\n\n---\n\n".join(snippets)
        + "\n\nWrite the summary."
    )
    try:
        result = await llm.complete(
            messages=[
                Message(role="system", content=_RESUMMARIZE_SYSTEM),
                Message(role="user", content=user_text),
            ],
            params=CompletionParams(temperature=0.2, max_tokens=400),
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}") from e

    summary = (result.text or "").strip()
    if not summary:
        raise HTTPException(status_code=502, detail="LLM returned empty summary")

    return ResummarizeResponse(
        summary=summary,
        model=result.model,
        snippet_count=len(snippets),
    )


# ---- answer lineage: nodes → source chunks (paragraph-level citations) ----


class Citation(DomainModel):
    chunk_id: Id
    document_id: Id | None = None
    document_title: str | None = None
    valid_from: datetime | None = None
    snippet: str


class LineageResult(DomainModel):
    citations: list[Citation]
    chunk_node_ids: list[Id]
    """Chunk-layer node ids supporting the given nodes — highlight these on
    the graph to show the answer's lineage."""


@router.get(
    "/graphs/{variant_id}/lineage",
    response_model=LineageResult,
)
async def node_lineage(
    variant_id: Id,
    node_ids: str,
    max_chunks: int = 30,
    repo: RepositoryProtocol = Depends(get_repository),
) -> LineageResult:
    """Paragraph-level provenance for a set of nodes (e.g. a RAG answer's
    evidence): the chunk nodes they're MENTIONED_IN, each with a text snippet
    carved from its source document. `node_ids` is comma-separated."""
    try:
        variant = await repo.get_variant(variant_id)
        state = await repo.load_state(variant_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    wanted = {s.strip() for s in node_ids.split(",") if s.strip()}
    nodes_by_id = {str(n.id): n for n in state.nodes}

    chunk_ids: list[str] = []
    seen: set[str] = set()
    for nid in wanted:
        node = nodes_by_id.get(nid)
        if node is None:
            continue
        # the node itself may be a chunk; otherwise its MENTIONED_IN chunks
        candidates = (
            [nid] if node.layer == Layer.CHUNK else _mentioned_chunk_ids(state, node.id)
        )
        for cid in candidates:
            if cid not in seen and nodes_by_id.get(cid) is not None:
                seen.add(cid)
                chunk_ids.append(cid)

    docs = await repo.list_documents(variant.corpus_id)
    docs_by_id = {str(d.id): d for d in docs}

    citations: list[Citation] = []
    for cid in chunk_ids[:max_chunks]:
        ch = nodes_by_id[cid]
        prov = ch.provenance[0] if ch.provenance else None
        doc = docs_by_id.get(str(prov.document_id)) if prov else None
        snippet = ""
        if doc and doc.text and prov:
            snippet = _snippet(doc.text, prov.span_start, prov.span_end)
        citations.append(
            Citation(
                chunk_id=ch.id,
                document_id=prov.document_id if prov else None,
                document_title=doc.title if doc else None,
                valid_from=ch.valid_from,
                snippet=snippet or (ch.name or ""),
            )
        )

    return LineageResult(
        citations=citations,
        chunk_node_ids=[c.chunk_id for c in citations],
    )
