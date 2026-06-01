"""LightRAG builder — LLM-profiled entities with local + global keys.

One LLM call per chunk, asks for entities (with concrete `local_keys`
and abstract `global_keys`) plus the relations visible in the chunk.
Across chunks, entities with the same case-insensitive (type, name)
collapse into one node and accumulate keys/descriptions. Pairs with
LightRAGDualKeyword reasoner — the keys are what the dual-level
keyword search retrieves on.
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


@builders.register(
    "lightrag",
    summary="LightRAG: LLM-profiled entities with local + global keys.",
    description=(
        "Builder that uses an LLM to profile each entity with two key "
        "sets — local (concrete attributes) and global (abstract "
        "themes). Pairs naturally with LightRAGDualKeyword reasoner. "
        "EDA recommends this for short-document corpora with dense NER."
    ),
    produces_layers=(Layer.CHUNK, Layer.ENTITY, Layer.COMMUNITY),
    params_schema={
        "chunk_size": {"type": "integer", "default": 1500},
        "chunk_overlap": {"type": "integer", "default": 100},
        "max_entities_per_chunk": {"type": "integer", "default": 20},
        "concurrency": {"type": "integer", "default": 6},
        "max_chunks": {
            "type": "integer",
            "default": 0,
            "description": "Hard cap on LLM calls (0 = unlimited).",
        },
    },
    cost_hint="expensive",
    references=("docs/raw/2410.05779v3.pdf",),
)
class LightRAGBuilder:
    """LLM-driven entity + relation extraction with local/global keys.

    Stateful: needs a CompletionClient. Orchestrator constructs with the
    runtime singleton; tests pass a fake client directly.
    """

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

        chunk_size = int(params.get("chunk_size", 1500))
        chunk_overlap = int(params.get("chunk_overlap", 100))
        max_entities = int(params.get("max_entities_per_chunk", 20)) or None
        concurrency = int(params.get("concurrency", 6))
        max_chunks_raw = int(params.get("max_chunks", 0))
        max_chunks = max_chunks_raw if max_chunks_raw > 0 else None
        schema = _schema_from_params(params)

        nodes, edges = await run_extraction_pipeline(
            graph_variant_id=graph_variant_id,
            documents=documents,
            llm=llm,
            style="lightrag",
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            gleanings=0,
            concurrency=concurrency,
            max_chunks=max_chunks,
            max_entities_per_chunk=max_entities,
            schema=schema,
        )
        return GraphBuildState(nodes=nodes, edges=edges)


def _schema_from_params(params: dict[str, Any]) -> CorpusSchema | None:
    """Extract `schema=` kwarg from builder_params. Accepts either a
    full CorpusSchema dict or just `entity_types`+`relation_types`
    flattened. Returns None when there's no schema info — that's the
    open-vocab path."""

    raw = params.get("schema")
    if isinstance(raw, CorpusSchema):
        return raw
    if isinstance(raw, dict):
        try:
            return CorpusSchema.model_validate(raw)
        except Exception:
            return None
    entity_types = params.get("entity_types") or []
    relation_types = params.get("relation_types") or []
    if not entity_types and not relation_types:
        return None
    try:
        return CorpusSchema.model_validate(
            {"entity_types": entity_types, "relation_types": relation_types}
        )
    except Exception:
        return None
