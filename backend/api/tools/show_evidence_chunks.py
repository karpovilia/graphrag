from __future__ import annotations

from typing import Any

from api.domain.graph import EdgeType, Layer, Node
from api.domain.types import Id
from api.strategies.protocols import GraphLoader
from api.strategies.registry import tools


@tools.register(
    "show_evidence_chunks",
    summary="Return CHUNK-layer nodes that mention this entity.",
    description=(
        "Most useful for ENTITY/COMMUNITY nodes. Walks MENTIONED_IN and "
        "MEMBER_OF/SUMMARY_OF edges down to the chunk layer and surfaces "
        "the source spans the user can click into. Universal binding "
        "with empty applies_to so the menu shows it everywhere; the "
        "result is just empty if there are no chunks attached."
    ),
    params_schema={
        "limit": {
            "type": "integer",
            "default": 20,
            "description": "Cap on returned chunks.",
        },
    },
    cost_hint="cheap",
)
class ShowEvidenceChunks:
    applies_to: tuple[str, ...] = ()

    async def run(
        self,
        node: Node,
        graph_variant_id: Id,
        params: dict[str, Any],
        loader: GraphLoader,
    ) -> dict[str, Any]:
        limit = int(params.get("limit", 20))

        nodes = await loader.load_nodes(graph_variant_id)
        edges = await loader.load_edges(graph_variant_id)
        node_index = {n.id: n for n in nodes}

        # Direct chunks: MENTIONED_IN edges from this node to a CHUNK.
        direct_chunk_ids = {
            e.target_node_id
            for e in edges
            if e.type == EdgeType.MENTIONED_IN
            and e.source_node_id == node.id
            and node_index.get(e.target_node_id, _none_node()).layer == Layer.CHUNK
        }

        # If the node is a community/topic, expand via members.
        if node.layer in (Layer.COMMUNITY, Layer.TOPIC) and not direct_chunk_ids:
            member_entity_ids = {
                e.source_node_id
                for e in edges
                if e.type == EdgeType.MEMBER_OF and e.target_node_id == node.id
            }
            for entity_id in member_entity_ids:
                for e in edges:
                    if (
                        e.type == EdgeType.MENTIONED_IN
                        and e.source_node_id == entity_id
                        and node_index.get(e.target_node_id, _none_node()).layer
                        == Layer.CHUNK
                    ):
                        direct_chunk_ids.add(e.target_node_id)

        chunks_out: list[dict[str, Any]] = []
        for chunk_id in sorted(direct_chunk_ids, key=str):
            chunk = node_index.get(chunk_id)
            if chunk is None:
                continue
            chunks_out.append(
                {
                    "id": str(chunk.id),
                    "name": chunk.name,
                    "char_start": chunk.attributes.get("char_start"),
                    "char_end": chunk.attributes.get("char_end"),
                    "summary": chunk.summary,
                }
            )
            if len(chunks_out) >= limit:
                break

        return {
            "chunks": chunks_out,
            "total_found": len(direct_chunk_ids),
            "truncated_to": limit,
        }


def _none_node() -> Node:
    """Sentinel used in lookups to keep the type-checker happy without
    raising on missing nodes — production code paths should never hit
    this branch in practice."""

    from api.domain.types import new_id

    return Node(
        graph_variant_id=new_id(),
        layer=Layer.ENTITY,
        type="GENERIC",
        granularity=0,
        name="",
    )
