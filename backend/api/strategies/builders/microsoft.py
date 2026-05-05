from __future__ import annotations

from typing import Any

from api.domain.corpus import Document
from api.domain.graph import Layer
from api.domain.types import Id

from ..registry import builders
from ..state import GraphBuildState


@builders.register(
    "microsoft",
    summary="Microsoft GraphRAG via the PyPI graphrag package.",
    description=(
        "Adapter over the upstream graphrag package: LLM-driven entity "
        "+ relation extraction with hierarchical community summaries. "
        "Heavy and LLM-intensive; EDA recommends this for long-doc "
        "corpora (median > 4k chars). Wiring lands once the orchestrator "
        "ingestion path can hand graphrag the artifact directory it "
        "expects (Phase 1.2.x)."
    ),
    produces_layers=(Layer.CHUNK, Layer.ENTITY, Layer.COMMUNITY, Layer.TOPIC),
    params_schema={
        "chunk_size": {"type": "integer", "default": 1200},
        "chunk_overlap": {"type": "integer", "default": 100},
        "extraction_max_gleanings": {"type": "integer", "default": 1},
    },
    cost_hint="expensive",
    references=("docs/raw/2509.21710v2.pdf",),
)
class MicrosoftBuilder:
    """Stub. The PyPI graphrag package owns the heavy lifting; this
    adapter just translates our (Document, text) pairs into its expected
    artifact directory and returns a GraphBuildState filled with the
    parquet outputs.
    """

    async def build(
        self,
        graph_variant_id: Id,
        corpus_id: Id,
        documents: list[tuple[Document, str]],
        params: dict[str, Any],
    ) -> GraphBuildState:
        raise NotImplementedError(
            "MicrosoftBuilder not wired yet — pending graphrag artifact bridge (Phase 1.2.x)"
        )
