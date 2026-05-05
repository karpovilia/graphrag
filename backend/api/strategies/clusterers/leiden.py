from __future__ import annotations

from typing import Any

from api.domain.graph import Layer

from ..registry import clusterers
from ..state import GraphBuildState
from ._common import _build_undirected_adjacency, entity_subgraph, materialize_communities


@clusterers.register(
    "leiden",
    summary="Leiden community detection over entity-relation edges.",
    description=(
        "Default clusterer used by Microsoft GraphRAG. Modularity-based, "
        "well-behaved, and hierarchical (via igraph + leidenalg). Random "
        "seed exposed for reproducibility — note that Leiden output can "
        "still drift across runs even with a fixed seed when the input "
        "graph changes; CommunityStabilityScout (Phase 3) flags those."
    ),
    requires_layers=(Layer.ENTITY,),
    produces_layers=(Layer.COMMUNITY,),
    params_schema={
        "resolution": {
            "type": "number",
            "default": 1.0,
            "description": "Resolution parameter; higher → more, smaller communities.",
        },
        "seed": {
            "type": "integer",
            "default": 42,
            "description": "RNG seed for the Leiden algorithm.",
        },
        "n_iterations": {
            "type": "integer",
            "default": 10,
            "description": "Number of Leiden refinement passes.",
        },
    },
    cost_hint="cheap",
    references=("docs/raw/2410.05779v3.pdf",),
)
class LeidenClusterer:
    """Leiden over entity-layer ENTITY_RELATION edges via igraph + leidenalg.

    Both libraries are dev-deps already; no extra cost to import. We
    deliberately don't use graspologic's hierarchical_leiden here because
    we want a single flat partition per run — hierarchy in our domain
    model lives in `granularity`, not nested communities. Multi-level
    can come back as a separate clusterer plugin if EDA recommends it.
    """

    async def cluster(
        self,
        state: GraphBuildState,
        params: dict[str, Any],
    ) -> GraphBuildState:
        import igraph
        import leidenalg

        resolution = float(params.get("resolution", 1.0))
        seed = int(params.get("seed", 42))
        n_iterations = int(params.get("n_iterations", 10))

        entities, edges = entity_subgraph(state)
        if not entities:
            return state

        node_list, triples = _build_undirected_adjacency(entities, edges)
        graph = igraph.Graph(n=len(node_list), edges=[(i, j) for i, j, _ in triples])
        graph.es["weight"] = [w for _, _, w in triples] if triples else []

        partition = leidenalg.find_partition(
            graph,
            leidenalg.RBConfigurationVertexPartition,
            weights="weight" if triples else None,
            resolution_parameter=resolution,
            seed=seed,
            n_iterations=n_iterations,
        )

        membership = {
            node_list[i].id: int(partition.membership[i]) for i in range(len(node_list))
        }
        return materialize_communities(state, membership=membership, method_name="leiden")
