from __future__ import annotations

from typing import Any

from api.domain.corpus import Document
from api.domain.graph import Layer
from api.domain.types import Id

from ..registry import builders
from ..state import GraphBuildState


@builders.register(
    "lightrag",
    summary="LightRAG: LLM-profiled entities with local + global keys.",
    description=(
        "Builder that uses an LLM to profile each entity with two key "
        "sets — local (concrete attributes) and global (abstract "
        "themes). Pairs naturally with LightRAGDualKeyword reasoner. "
        "EDA recommends this for short-document corpora with dense NER. "
        "Wiring: 1.2.x."
    ),
    produces_layers=(Layer.CHUNK, Layer.ENTITY, Layer.COMMUNITY),
    params_schema={
        "chunk_size": {"type": "integer", "default": 1500},
        "max_entities_per_chunk": {"type": "integer", "default": 20},
    },
    cost_hint="expensive",
    references=("docs/raw/2410.05779v3.pdf",),
)
class LightRAGBuilder:
    async def build(
        self,
        graph_variant_id: Id,
        corpus_id: Id,
        documents: list[tuple[Document, str]],
        params: dict[str, Any],
    ) -> GraphBuildState:
        raise NotImplementedError(
            "LightRAGBuilder not wired yet — pending LLM-profiling pass (Phase 1.2.x)"
        )
