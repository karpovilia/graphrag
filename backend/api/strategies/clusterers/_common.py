from __future__ import annotations

from typing import Iterable

from api.domain.graph import Edge, EdgeType, Layer, Node
from api.domain.types import new_id

from ..state import GraphBuildState


def materialize_communities(
    state: GraphBuildState,
    *,
    membership: dict,
    method_name: str,
) -> GraphBuildState:
    """Turn a {entity_node_id -> community_index} mapping into a new
    GraphBuildState whose community-layer nodes and MEMBER_OF edges
    reflect the assignment.

    Existing community-layer nodes and MEMBER_OF edges are dropped and
    replaced — clustering is not additive. Pre-existing topic-layer
    summaries that referenced old communities will be recomputed by the
    summarizer downstream; we don't try to be cute about that here.
    """

    # Drop previous community nodes and any edge that touched them.
    old_community_ids = {n.id for n in state.nodes if n.layer == Layer.COMMUNITY}
    surviving_nodes = [n for n in state.nodes if n.layer != Layer.COMMUNITY]
    surviving_edges = [
        e
        for e in state.edges
        if e.source_node_id not in old_community_ids
        and e.target_node_id not in old_community_ids
        and e.type != EdgeType.MEMBER_OF
    ]

    # Reverse mapping: community_index -> [entity_node_ids]
    by_community: dict = {}
    for node_id, comm in membership.items():
        by_community.setdefault(comm, []).append(node_id)

    # Use the first entity's graph_variant_id (they should all share one).
    if state.nodes:
        gv_id = state.nodes[0].graph_variant_id
    else:
        gv_id = new_id()

    new_community_nodes: list[Node] = []
    new_member_edges: list[Edge] = []
    for comm_index, member_ids in sorted(by_community.items(), key=lambda kv: str(kv[0])):
        community_node = Node(
            graph_variant_id=gv_id,
            layer=Layer.COMMUNITY,
            type="COMMUNITY",
            granularity=2,
            name=f"{method_name}#{comm_index}",
            attributes={"clusterer": method_name, "size": len(member_ids)},
        )
        new_community_nodes.append(community_node)
        for member_id in member_ids:
            new_member_edges.append(
                Edge(
                    graph_variant_id=gv_id,
                    type=EdgeType.MEMBER_OF,
                    source_node_id=member_id,
                    target_node_id=community_node.id,
                    attributes={"clusterer": method_name},
                )
            )

    return GraphBuildState(
        nodes=surviving_nodes + new_community_nodes,
        edges=surviving_edges + new_member_edges,
        journal=list(state.journal),
    )


def entity_subgraph(state: GraphBuildState) -> tuple[list[Node], list[Edge]]:
    """Project (nodes, edges) onto the entity layer for clustering.

    Communities/topics are dropped; MEMBER_OF, MENTIONED_IN, SUMMARY_OF
    edges (inter-layer) are dropped. Only ENTITY_RELATION edges between
    entity-layer nodes survive — that's the network the algorithms see.
    """

    entity_ids = {n.id for n in state.nodes if n.layer == Layer.ENTITY}
    entities = [n for n in state.nodes if n.layer == Layer.ENTITY]
    edges = [
        e
        for e in state.edges
        if e.type == EdgeType.ENTITY_RELATION
        and e.source_node_id in entity_ids
        and e.target_node_id in entity_ids
    ]
    return entities, edges


def _build_undirected_adjacency(
    nodes: Iterable[Node],
    edges: Iterable[Edge],
) -> tuple[list, list[tuple[int, int, float]]]:
    """List of node ids in insertion order + (i, j, w) edge triples in
    the same order. Caller picks how to feed this into the algorithm
    library."""

    node_list = list(nodes)
    idx = {n.id: i for i, n in enumerate(node_list)}
    triples: list[tuple[int, int, float]] = []
    seen: set[tuple[int, int]] = set()
    for e in edges:
        i = idx[e.source_node_id]
        j = idx[e.target_node_id]
        if i == j:
            continue
        key = (i, j) if i < j else (j, i)
        if key in seen:
            continue
        seen.add(key)
        triples.append((key[0], key[1], float(e.weight or 1.0)))
    return node_list, triples
