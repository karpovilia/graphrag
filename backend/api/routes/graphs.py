"""POST /api/graphs/preview — synchronous, in-memory build pipeline.

Phase 1.5 (preview): no DB, no SSE. Validates registry names, runs
builder → cleaners → clusterer, returns a summary of the resulting
GraphBuildState. Real async + persistence in 1.5.x.
"""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from api.domain.corpus import Document
from api.domain.graph import Layer
from api.domain.types import DomainModel, Id, new_id
from api.eda.ner import NerProtocol
from api.llm import CompletionClient
from api.orchestrator import PipelineError, run_build_pipeline
from api.runtime import get_ner


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
