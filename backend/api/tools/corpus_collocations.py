from __future__ import annotations

from collections import Counter
from typing import Any

from api.domain.graph import EdgeType, Layer, Node
from api.domain.types import Id
from api.strategies.protocols import GraphLoader
from api.strategies.registry import tools


@tools.register(
    "corpus_collocations",
    summary="Top entities co-mentioned with this one in the same chunks.",
    description=(
        "PERSON / ORG / PLACE — surfaces the top other entities sharing "
        "a CHUNK with the focus node. Counts how many chunks each "
        "co-mention spans, returns the top-K by frequency. Useful "
        "alternative to wikidata_lookup when external lookups are off."
    ),
    params_schema={
        "top_k": {
            "type": "integer",
            "default": 10,
        },
        "include_layers": {
            "type": "array",
            "items": {"type": "string"},
            "default": ["entity"],
            "description": "Restrict co-mentioned candidates to these layers.",
        },
    },
    cost_hint="cheap",
)
class CorpusCollocations:
    applies_to: tuple[str, ...] = ("PERSON", "ORG", "PLACE")

    async def run(
        self,
        node: Node,
        graph_variant_id: Id,
        params: dict[str, Any],
        loader: GraphLoader,
    ) -> dict[str, Any]:
        top_k = int(params.get("top_k", 10))
        layer_filter = {str(s) for s in params.get("include_layers", ["entity"])}

        nodes = await loader.load_nodes(graph_variant_id)
        edges = await loader.load_edges(graph_variant_id)
        node_index = {n.id: n for n in nodes}

        # Chunks that mention the focus node.
        my_chunk_ids: set[Id] = {
            e.target_node_id
            for e in edges
            if e.type == EdgeType.MENTIONED_IN
            and e.source_node_id == node.id
            and node_index.get(e.target_node_id, _none()).layer == Layer.CHUNK
        }
        if not my_chunk_ids:
            return {"co_mentions": [], "shared_chunk_count": 0}

        # Other entities mentioned in those chunks.
        cooc: Counter[Id] = Counter()
        for e in edges:
            if e.type != EdgeType.MENTIONED_IN:
                continue
            if e.target_node_id not in my_chunk_ids:
                continue
            other_id = e.source_node_id
            if other_id == node.id:
                continue
            other = node_index.get(other_id)
            if other is None or other.layer.value not in layer_filter:
                continue
            cooc[other_id] += 1

        results = [
            {
                "id": str(other_id),
                "name": node_index[other_id].name,
                "type": node_index[other_id].type,
                "shared_chunks": count,
            }
            for other_id, count in cooc.most_common(top_k)
        ]
        return {
            "co_mentions": results,
            "shared_chunk_count": len(my_chunk_ids),
        }


def _none() -> Node:
    from api.domain.types import new_id

    return Node(
        graph_variant_id=new_id(),
        layer=Layer.ENTITY,
        type="GENERIC",
        granularity=0,
        name="",
    )
