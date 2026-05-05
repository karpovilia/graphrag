from __future__ import annotations

from typing import Any

from api.domain.corpus import Document
from api.domain.graph import Layer
from api.domain.types import Id

from ..registry import builders
from ..state import GraphBuildState


@builders.register(
    "fastrag",
    summary="FastRAG: schema-and-script learning for semi-structured corpora.",
    description=(
        "One-shot LLM pass produces a JSON schema + Python parser; "
        "subsequent extraction runs are LLM-free. Designed for "
        "highly structured corpora (logs, configs, registries) where "
        "the same template repeats. Out of MVP scope but registered "
        "so the wizard documents the option."
    ),
    produces_layers=(Layer.CHUNK, Layer.ENTITY),
    params_schema={
        "sample_chunks": {"type": "integer", "default": 16},
    },
    cost_hint="moderate",
    references=("docs/raw/2411.13773v2.pdf",),
)
class FastRAGBuilder:
    async def build(
        self,
        graph_variant_id: Id,
        corpus_id: Id,
        documents: list[tuple[Document, str]],
        params: dict[str, Any],
    ) -> GraphBuildState:
        raise NotImplementedError(
            "FastRAGBuilder not wired yet — schema/script generation deferred (Phase 1.2.x)"
        )
