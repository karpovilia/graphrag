from __future__ import annotations

from typing import Any

from api.domain.graph import Layer

from ..registry import clusterers
from ..state import GraphBuildState
from ._common import _build_undirected_adjacency, entity_subgraph, materialize_communities


@clusterers.register(
    "bayan",
    summary="Bayan exact modularity community detection.",
    description=(
        "Exact-modularity alternative to Leiden via the bayanpy package. "
        "Slower than Leiden — recommended only for small graphs (< ~1k "
        "entities) where reproducibility matters more than throughput. "
        "Was a local fork patch in the legacy Microsoft GraphRAG copy; "
        "moved here so it lives in our plugin registry instead."
    ),
    requires_layers=(Layer.ENTITY,),
    produces_layers=(Layer.COMMUNITY,),
    params_schema={
        "threshold": {
            "type": "number",
            "default": 0.001,
            "description": "Bayan optimality gap threshold.",
        },
        "time_allowed": {
            "type": "number",
            "default": 60.0,
            "description": "Hard wall-clock cap in seconds.",
        },
    },
    cost_hint="moderate",
    references=("docs/raw/2410.05779v3.pdf",),
)
class BayanClusterer:
    """Bayan exact-modularity clustering.

    bayanpy.bayan returns (modularity, partition_indicator_matrix). We
    convert the indicator matrix to a flat membership map.
    """

    async def cluster(
        self,
        state: GraphBuildState,
        params: dict[str, Any],
    ) -> GraphBuildState:
        import networkx as nx
        from bayanpy import bayan as run_bayan

        threshold = float(params.get("threshold", 0.001))
        time_allowed = float(params.get("time_allowed", 60.0))

        entities, edges = entity_subgraph(state)
        if not entities:
            return state

        node_list, triples = _build_undirected_adjacency(entities, edges)
        graph = nx.Graph()
        graph.add_nodes_from(range(len(node_list)))
        for i, j, w in triples:
            graph.add_edge(i, j, weight=w)

        _, _, _, _, indicator = run_bayan(graph, threshold, time_allowed)

        # `indicator` is a {0,1} matrix shaped (n_nodes, n_communities).
        membership: dict = {}
        for row_idx, row in enumerate(indicator):
            for col_idx, val in enumerate(row):
                if val:
                    membership[node_list[row_idx].id] = col_idx
                    break

        return materialize_communities(state, membership=membership, method_name="bayan")
