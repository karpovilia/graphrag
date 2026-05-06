from __future__ import annotations

from dataclasses import dataclass

from api.domain.graph import Edge, Node
from api.domain.types import Id
from api.strategies.state import GraphBuildState


@dataclass(frozen=True)
class StateDiff:
    """Per-id breakdown of how a curation op changed the graph.

    Used by Postgres to issue minimal INSERT/DELETE/UPDATE batches and
    by the vector-outbox writer to scope which embeddings need refresh.
    """

    nodes_added: tuple[Node, ...]
    nodes_removed: tuple[Id, ...]
    nodes_changed: tuple[Node, ...]
    edges_added: tuple[Edge, ...]
    edges_removed: tuple[Id, ...]
    edges_changed: tuple[Edge, ...]


def diff_states(before: GraphBuildState, after: GraphBuildState) -> StateDiff:
    """Compute the structural delta. Order-independent — a permutation
    in the lists is not a diff. Equality on Node/Edge is full Pydantic
    equality so attribute changes count as `changed`, not added+removed.
    """

    before_nodes = {n.id: n for n in before.nodes}
    after_nodes = {n.id: n for n in after.nodes}
    before_edges = {e.id: e for e in before.edges}
    after_edges = {e.id: e for e in after.edges}

    return StateDiff(
        nodes_added=tuple(
            after_nodes[i] for i in after_nodes.keys() - before_nodes.keys()
        ),
        nodes_removed=tuple(before_nodes.keys() - after_nodes.keys()),
        nodes_changed=tuple(
            after_nodes[i]
            for i in after_nodes.keys() & before_nodes.keys()
            if after_nodes[i] != before_nodes[i]
        ),
        edges_added=tuple(
            after_edges[i] for i in after_edges.keys() - before_edges.keys()
        ),
        edges_removed=tuple(before_edges.keys() - after_edges.keys()),
        edges_changed=tuple(
            after_edges[i]
            for i in after_edges.keys() & before_edges.keys()
            if after_edges[i] != before_edges[i]
        ),
    )
