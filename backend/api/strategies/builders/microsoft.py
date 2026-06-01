"""Microsoft GraphRAG-style builder.

LLM-driven entity + relation extraction with optional gleaning passes
(re-runs that ask the model what was missed). Output mirrors the shape
the upstream Microsoft GraphRAG produces — entity nodes carry a
description, relations carry a predicate + textual evidence — but we
build the graph in our R2 domain model rather than spinning up the
upstream `graphrag` package's parquet pipeline. Pairs with the Microsoft
local/global reasoners.
"""

from __future__ import annotations

from typing import Any

from api.domain.corpus import Document
from api.domain.graph import Layer
from api.domain.schema import CorpusSchema
from api.domain.types import Id
from api.llm import CompletionClient
from api.runtime import get_llm

from ..registry import builders
from ..state import GraphBuildState
from ._llm_extract import run_extraction_pipeline
from .lightrag import _schema_from_params


@builders.register(
    "microsoft",
    summary="Microsoft GraphRAG-style LLM extraction with gleaning passes.",
    description=(
        "Adapter mirroring the Microsoft GraphRAG extraction pipeline: "
        "LLM-driven entity + relation extraction with hierarchical "
        "community summaries (when paired with leiden + a summarizer). "
        "Heavy and LLM-intensive; EDA recommends this for long-doc "
        "corpora (median > 4k chars)."
    ),
    produces_layers=(Layer.CHUNK, Layer.ENTITY, Layer.COMMUNITY, Layer.TOPIC),
    params_schema={
        "chunk_size": {"type": "integer", "default": 1200},
        "chunk_overlap": {"type": "integer", "default": 100},
        "extraction_max_gleanings": {"type": "integer", "default": 1},
        "concurrency": {"type": "integer", "default": 6},
        "max_chunks": {
            "type": "integer",
            "default": 0,
            "description": "Hard cap on LLM calls (0 = unlimited).",
        },
    },
    cost_hint="expensive",
    references=("docs/raw/2509.21710v2.pdf",),
)
class MicrosoftBuilder:
    """LLM extraction with up to N gleaning refinement passes per chunk."""

    def __init__(self, llm: CompletionClient | None = None) -> None:
        self._llm = llm

    async def build(
        self,
        graph_variant_id: Id,
        corpus_id: Id,
        documents: list[tuple[Document, str]],
        params: dict[str, Any],
    ) -> GraphBuildState:
        llm = self._llm or get_llm()

        chunk_size = int(params.get("chunk_size", 1200))
        chunk_overlap = int(params.get("chunk_overlap", 100))
        gleanings = int(params.get("extraction_max_gleanings", 1))
        concurrency = int(params.get("concurrency", 6))
        max_chunks_raw = int(params.get("max_chunks", 0))
        max_chunks = max_chunks_raw if max_chunks_raw > 0 else None
        schema = _schema_from_params(params)

        nodes, edges = await run_extraction_pipeline(
            graph_variant_id=graph_variant_id,
            documents=documents,
            llm=llm,
            style="microsoft",
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            gleanings=gleanings,
            concurrency=concurrency,
            max_chunks=max_chunks,
            max_entities_per_chunk=None,
            schema=schema,
        )
        return GraphBuildState(nodes=nodes, edges=edges)
