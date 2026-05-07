from __future__ import annotations

from typing import Any

from api.domain.graph import Node
from api.domain.types import Id
from api.strategies.protocols import GraphLoader
from api.strategies.registry import tools


@tools.register(
    "show_neighbors",
    summary="List nodes directly connected to this one.",
    description=(
        "Universal — no type binding. Walks edges incident to the node "
        "in the variant and returns labels grouped by edge type. Cheap, "
        "deterministic; useful as a default action in the side-drawer."
    ),
    params_schema={
        "limit": {
            "type": "integer",
            "default": 50,
            "description": "Cap on neighbors per edge_type.",
        },
        "include_layers": {
            "type": "array",
            "items": {"type": "string"},
            "default": None,
            "description": "Filter neighbor layers; null means all.",
        },
    },
    cost_hint="cheap",
)
class ShowNeighbors:
    applies_to: tuple[str, ...] = ()

    async def run(
        self,
        node: Node,
        graph_variant_id: Id,
        params: dict[str, Any],
        loader: GraphLoader,
    ) -> dict[str, Any]:
        limit = int(params.get("limit", 50))
        layer_filter_raw = params.get("include_layers")
        layer_filter = (
            None if layer_filter_raw is None else {str(layer) for layer in layer_filter_raw}
        )

        nodes = await loader.load_nodes(graph_variant_id)
        edges = await loader.load_edges(graph_variant_id)
        node_index: dict[Id, Node] = {n.id: n for n in nodes}

        groups: dict[str, list[dict[str, Any]]] = {}
        for edge in edges:
            other_id: Id | None = None
            if edge.source_node_id == node.id:
                other_id = edge.target_node_id
            elif edge.target_node_id == node.id:
                other_id = edge.source_node_id
            if other_id is None:
                continue
            other = node_index.get(other_id)
            if other is None:
                continue
            if layer_filter is not None and other.layer.value not in layer_filter:
                continue
            bucket = groups.setdefault(edge.type.value, [])
            if len(bucket) >= limit:
                continue
            bucket.append(
                {
                    "id": str(other.id),
                    "name": other.name,
                    "type": other.type,
                    "layer": other.layer.value,
                    "weight": edge.weight,
                    "relation": edge.relation,
                }
            )

        total = sum(len(v) for v in groups.values())
        return {
            "neighbors_by_edge_type": groups,
            "total": total,
            "truncated_to": limit,
        }
