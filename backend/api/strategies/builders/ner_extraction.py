from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

from api.domain.corpus import Document
from api.domain.graph import Edge, EdgeType, Layer, Node
from api.domain.types import Id, Provenance
from api.eda.ner import NerProtocol

from ..registry import builders
from ..state import GraphBuildState


@builders.register(
    "ner_extraction",
    summary="Russian NER over chunks → entities + co-occurrence relations.",
    description=(
        "No-LLM baseline that uses natasha to extract entity mentions "
        "from each chunk and links co-occurring entities with weighted "
        "ENTITY_RELATION edges. Produces CHUNK + ENTITY layers. Cheap, "
        "deterministic, useful as a smoke test of the build pipeline "
        "and as an MoE baseline next to LLM-driven builders."
    ),
    produces_layers=(Layer.CHUNK, Layer.ENTITY),
    params_schema={
        "chunk_size": {
            "type": "integer",
            "default": 1500,
            "description": "Hard chunk-size in characters; chunks split on byte boundary.",
        },
        "min_cooccurrence": {
            "type": "integer",
            "default": 1,
            "description": "Drop entity-relation edges seen in fewer than N chunks.",
        },
    },
    cost_hint="cheap",
)
class NerExtractionBuilder:
    """Stateful — needs a NerProtocol. Orchestrator constructs with the
    NatashaNer instance from EDA so the heavy News-embedding load is
    amortized across EDA + every NerExtractionBuilder run.
    """

    def __init__(self, ner: NerProtocol) -> None:
        self._ner = ner

    async def build(
        self,
        graph_variant_id: Id,
        corpus_id: Id,
        documents: list[tuple[Document, str]],
        params: dict[str, Any],
    ) -> GraphBuildState:
        chunk_size = int(params.get("chunk_size", 1500))
        min_cooccurrence = int(params.get("min_cooccurrence", 1))

        chunk_nodes: list[Node] = []
        # entity key (type, lemma) -> Node so duplicates collapse.
        entity_by_key: dict[tuple[str, str], Node] = {}
        mention_edges: list[Edge] = []
        # ((entity_id_low, entity_id_high)) -> count
        cooccurrence: dict[tuple[Id, Id], int] = defaultdict(int)

        for doc, text in documents:
            for chunk_start, chunk_end, chunk_text in _chunk(text, chunk_size):
                chunk_node = Node(
                    graph_variant_id=graph_variant_id,
                    layer=Layer.CHUNK,
                    type="CHUNK",
                    granularity=0,
                    name=_short_name(doc.title, chunk_start),
                    summary=None,
                    attributes={
                        "char_start": chunk_start,
                        "char_end": chunk_end,
                        "text_hash": hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
                    },
                    provenance=[
                        Provenance(
                            document_id=doc.id,
                            span_start=chunk_start,
                            span_end=chunk_end,
                        )
                    ],
                )
                chunk_nodes.append(chunk_node)

                mentions = self._ner.extract(chunk_text)
                entities_in_chunk: list[Id] = []
                for m in mentions:
                    key = (m.type, m.lemma)
                    entity = entity_by_key.get(key)
                    if entity is None:
                        entity = Node(
                            graph_variant_id=graph_variant_id,
                            layer=Layer.ENTITY,
                            type=_map_ner_type(m.type),
                            granularity=1,
                            name=m.text,
                            attributes={
                                "lemma": m.lemma,
                                "ner_type": m.type,
                            },
                        )
                        entity_by_key[key] = entity
                    entities_in_chunk.append(entity.id)

                    mention_edges.append(
                        Edge(
                            graph_variant_id=graph_variant_id,
                            type=EdgeType.MENTIONED_IN,
                            source_node_id=entity.id,
                            target_node_id=chunk_node.id,
                            provenance=[
                                Provenance(
                                    document_id=doc.id,
                                    span_start=chunk_start + m.start,
                                    span_end=chunk_start + m.end,
                                )
                            ],
                        )
                    )

                for i in range(len(entities_in_chunk)):
                    for j in range(i + 1, len(entities_in_chunk)):
                        a, b = entities_in_chunk[i], entities_in_chunk[j]
                        if a == b:
                            continue
                        key_pair = (a, b) if str(a) < str(b) else (b, a)
                        cooccurrence[key_pair] += 1

        relation_edges = [
            Edge(
                graph_variant_id=graph_variant_id,
                type=EdgeType.ENTITY_RELATION,
                source_node_id=a,
                target_node_id=b,
                weight=float(count),
                relation="co_occurrence",
            )
            for (a, b), count in cooccurrence.items()
            if count >= min_cooccurrence
        ]

        nodes = chunk_nodes + list(entity_by_key.values())
        edges = mention_edges + relation_edges
        return GraphBuildState(nodes=nodes, edges=edges)


_NER_TO_DOMAIN = {"PER": "PERSON", "LOC": "PLACE", "ORG": "ORG"}


def _map_ner_type(ner_label: str) -> str:
    return _NER_TO_DOMAIN.get(ner_label, ner_label)


def _short_name(title: str, start: int) -> str:
    base = title.strip() or "chunk"
    return f"{base}@{start}"


def _chunk(text: str, size: int):
    if not text:
        return
    if size <= 0:
        size = 1500
    pos = 0
    n = len(text)
    while pos < n:
        end = min(pos + size, n)
        yield pos, end, text[pos:end]
        pos = end
