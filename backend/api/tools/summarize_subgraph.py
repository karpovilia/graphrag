from __future__ import annotations

from collections import Counter
from typing import Any

from api.domain.graph import EdgeType, Node
from api.domain.types import Id
from api.strategies.protocols import GraphLoader
from api.strategies.registry import tools


@tools.register(
    "summarize_subgraph",
    summary="Stats over the N-hop neighborhood of a node.",
    description=(
        "Universal. BFS to depth N from the focus node, then surfaces "
        "node-count by layer + by type + top edge_types touched + a "
        "sampled list of names. Cheap text-only fallback when the node "
        "doesn't have a precomputed `summary` yet — useful in §4 of the "
        "paper for showing what a freshly-clustered community covers."
    ),
    params_schema={
        "depth": {
            "type": "integer",
            "default": 1,
            "description": "BFS depth; 1 = immediate neighbors.",
        },
        "max_sample_names": {
            "type": "integer",
            "default": 10,
        },
    },
    cost_hint="cheap",
)
class SummarizeSubgraph:
    applies_to: tuple[str, ...] = ()

    async def run(
        self,
        node: Node,
        graph_variant_id: Id,
        params: dict[str, Any],
        loader: GraphLoader,
    ) -> dict[str, Any]:
        depth = max(0, int(params.get("depth", 1)))
        sample_size = int(params.get("max_sample_names", 10))

        nodes = await loader.load_nodes(graph_variant_id)
        edges = await loader.load_edges(graph_variant_id)
        node_index = {n.id: n for n in nodes}

        adjacency: dict[Id, list[tuple[Id, EdgeType]]] = {}
        for e in edges:
            adjacency.setdefault(e.source_node_id, []).append((e.target_node_id, e.type))
            adjacency.setdefault(e.target_node_id, []).append((e.source_node_id, e.type))

        visited: set[Id] = {node.id}
        edge_types_seen: Counter[str] = Counter()
        frontier: set[Id] = {node.id}
        for _ in range(depth):
            next_frontier: set[Id] = set()
            for nid in frontier:
                for neighbor_id, etype in adjacency.get(nid, ()):
                    edge_types_seen[etype.value] += 1
                    if neighbor_id in visited:
                        continue
                    next_frontier.add(neighbor_id)
            visited.update(next_frontier)
            frontier = next_frontier
            if not frontier:
                break

        layer_counts = Counter(
            node_index[nid].layer.value
            for nid in visited
            if nid in node_index
        )
        type_counts = Counter(
            node_index[nid].type
            for nid in visited
            if nid in node_index
        )
        sample_names = [
            node_index[nid].name
            for nid in sorted(visited, key=str)[:sample_size]
            if nid in node_index
        ]

        return {
            "focus_node_id": str(node.id),
            "depth": depth,
            "node_count": len(visited),
            "by_layer": dict(layer_counts),
            "by_type": dict(type_counts),
            "edge_types_seen": dict(edge_types_seen),
            "sample_names": sample_names,
        }
