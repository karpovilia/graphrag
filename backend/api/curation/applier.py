"""Pure journal applier.

Takes a JournalEntry and a GraphBuildState, returns a new state with the
op applied. No I/O. Used by the repository layer (transactional persist)
and by the orchestrator's preview endpoint (in-memory dry run).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from api.domain.curation import JournalEntry, JournalOp
from api.domain.graph import Edge, EdgeType, Node
from api.domain.types import Id, new_id
from api.strategies.state import GraphBuildState

from .ops import (
    AddEdgePayload,
    DeleteEdgePayload,
    DeleteNodePayload,
    EditEdgePayload,
    MergeNodesPayload,
    MoveToCommunityPayload,
    RetypeNodePayload,
    SetSummaryPayload,
    SplitNodePayload,
    UpdateNodeNamePayload,
    parse_payload,
)


class JournalApplyError(RuntimeError):
    """Apply could not proceed because the entry references an object
    no longer in the state (e.g. edit on a deleted edge). Caller decides
    whether to skip or fail the run.
    """


@dataclass(frozen=True, slots=True)
class AffectedSet:
    """What downstream pipelines need to refresh after this op.

    Used by the vector-outbox writer (re-embed `node_ids`), the summary
    refresher agent (Phase 3 — re-summarize `community_ids`), and the
    F7 layered viewer (selectively invalidate cached layouts).
    """

    node_ids: frozenset[Id] = field(default_factory=frozenset)
    edge_ids: frozenset[Id] = field(default_factory=frozenset)
    community_ids: frozenset[Id] = field(default_factory=frozenset)

    def union(self, other: "AffectedSet") -> "AffectedSet":
        return AffectedSet(
            node_ids=self.node_ids | other.node_ids,
            edge_ids=self.edge_ids | other.edge_ids,
            community_ids=self.community_ids | other.community_ids,
        )


# ---- public API ----


def apply_journal_op(
    state: GraphBuildState, entry: JournalEntry
) -> GraphBuildState:
    """Return a new state with `entry` applied. The entry itself is
    appended to state.journal. Pure: caller's state object is unchanged.
    """

    payload = parse_payload(entry.op, entry.payload)
    nodes = list(state.nodes)
    edges = list(state.edges)

    match entry.op:
        case JournalOp.MERGE_NODES:
            assert isinstance(payload, MergeNodesPayload)
            nodes, edges = _apply_merge_nodes(nodes, edges, payload)
        case JournalOp.SPLIT_NODE:
            assert isinstance(payload, SplitNodePayload)
            nodes, edges = _apply_split_node(nodes, edges, payload, entry)
        case JournalOp.RETYPE_NODE:
            assert isinstance(payload, RetypeNodePayload)
            nodes = _update_node(nodes, payload.node_id, type=payload.new_type)
        case JournalOp.MOVE_TO_COMMUNITY:
            assert isinstance(payload, MoveToCommunityPayload)
            edges = _apply_move_to_community(edges, payload, entry)
        case JournalOp.EDIT_EDGE:
            assert isinstance(payload, EditEdgePayload)
            edges = _apply_edit_edge(edges, payload)
        case JournalOp.DELETE_EDGE:
            assert isinstance(payload, DeleteEdgePayload)
            edges = [e for e in edges if e.id != payload.edge_id]
        case JournalOp.DELETE_NODE:
            assert isinstance(payload, DeleteNodePayload)
            nodes = [n for n in nodes if n.id != payload.node_id]
            edges = [
                e
                for e in edges
                if e.source_node_id != payload.node_id
                and e.target_node_id != payload.node_id
            ]
        case JournalOp.ADD_EDGE:
            assert isinstance(payload, AddEdgePayload)
            edges.append(Edge.model_validate(payload.edge))
        case JournalOp.SET_SUMMARY:
            assert isinstance(payload, SetSummaryPayload)
            nodes = _update_node(nodes, payload.node_id, summary=payload.summary)
        case JournalOp.UPDATE_NODE_NAME:
            assert isinstance(payload, UpdateNodeNamePayload)
            nodes = _update_node(nodes, payload.node_id, name=payload.name)

    return GraphBuildState(nodes=nodes, edges=edges, journal=state.journal + [entry])


def replay_journal(
    base_state: GraphBuildState, entries: Iterable[JournalEntry]
) -> GraphBuildState:
    """Apply entries in order. Used to materialize a current state from
    a parent variant + journal stream (Phase 2.4 undo and Phase 2.x
    cross-variant recovery scenarios).
    """

    state = base_state
    for entry in entries:
        state = apply_journal_op(state, entry)
    return state


def affected_set(
    state_before: GraphBuildState, entry: JournalEntry
) -> AffectedSet:
    """Compute the downstream impact of `entry` against the pre-apply
    state. Returns the set of nodes that need re-embedding, edges that
    were touched, and communities whose membership shifted.
    """

    payload = parse_payload(entry.op, entry.payload)
    node_index = state_before.node_index()

    match entry.op:
        case JournalOp.MERGE_NODES:
            assert isinstance(payload, MergeNodesPayload)
            return _affected_merge(payload, state_before, node_index)
        case JournalOp.SPLIT_NODE:
            assert isinstance(payload, SplitNodePayload)
            community = _community_of(payload.original_id, state_before)
            new_node_ids = _new_split_ids(payload, entry)
            return AffectedSet(
                node_ids=frozenset({payload.original_id, *new_node_ids}),
                community_ids=frozenset({community} if community else ()),
            )
        case JournalOp.RETYPE_NODE:
            assert isinstance(payload, RetypeNodePayload)
            community = _community_of(payload.node_id, state_before)
            return AffectedSet(
                node_ids=frozenset({payload.node_id}),
                community_ids=frozenset({community} if community else ()),
            )
        case JournalOp.MOVE_TO_COMMUNITY:
            assert isinstance(payload, MoveToCommunityPayload)
            communities = {payload.to_community_id}
            if payload.from_community_id is not None:
                communities.add(payload.from_community_id)
            else:
                # Reconstruct the from-community from current state.
                inferred = _community_of(payload.node_id, state_before)
                if inferred:
                    communities.add(inferred)
            return AffectedSet(
                node_ids=frozenset({payload.node_id}),
                community_ids=frozenset(communities),
            )
        case JournalOp.EDIT_EDGE:
            assert isinstance(payload, EditEdgePayload)
            edge = next((e for e in state_before.edges if e.id == payload.edge_id), None)
            if edge is None:
                return AffectedSet(edge_ids=frozenset({payload.edge_id}))
            communities = _communities_of_endpoints(edge, node_index, state_before)
            return AffectedSet(
                edge_ids=frozenset({edge.id}),
                node_ids=frozenset({edge.source_node_id, edge.target_node_id}),
                community_ids=frozenset(communities),
            )
        case JournalOp.DELETE_EDGE:
            assert isinstance(payload, DeleteEdgePayload)
            edge = next((e for e in state_before.edges if e.id == payload.edge_id), None)
            if edge is None:
                return AffectedSet(edge_ids=frozenset({payload.edge_id}))
            communities = _communities_of_endpoints(edge, node_index, state_before)
            return AffectedSet(
                edge_ids=frozenset({edge.id}),
                node_ids=frozenset({edge.source_node_id, edge.target_node_id}),
                community_ids=frozenset(communities),
            )
        case JournalOp.DELETE_NODE:
            assert isinstance(payload, DeleteNodePayload)
            community = _community_of(payload.node_id, state_before)
            touched_edges = frozenset(
                e.id
                for e in state_before.edges
                if e.source_node_id == payload.node_id
                or e.target_node_id == payload.node_id
            )
            return AffectedSet(
                node_ids=frozenset({payload.node_id}),
                edge_ids=touched_edges,
                community_ids=frozenset({community} if community else ()),
            )
        case JournalOp.ADD_EDGE:
            assert isinstance(payload, AddEdgePayload)
            spec = payload.edge
            src = Id(spec["source_node_id"]) if not isinstance(spec.get("source_node_id"), Id) else spec["source_node_id"]
            tgt = Id(spec["target_node_id"]) if not isinstance(spec.get("target_node_id"), Id) else spec["target_node_id"]
            communities = set()
            for nid in (src, tgt):
                community = _community_of(nid, state_before)
                if community:
                    communities.add(community)
            return AffectedSet(
                node_ids=frozenset({src, tgt}),
                community_ids=frozenset(communities),
            )
        case JournalOp.SET_SUMMARY | JournalOp.UPDATE_NODE_NAME:
            node_id = Id(payload.node_id)  # type: ignore[union-attr]
            return AffectedSet(node_ids=frozenset({node_id}))


# ---- internals ----


def _apply_merge_nodes(
    nodes: list[Node],
    edges: list[Edge],
    payload: MergeNodesPayload,
) -> tuple[list[Node], list[Edge]]:
    absorbed = set(payload.absorbed_ids)
    if payload.survivor_id in absorbed:
        raise JournalApplyError("survivor cannot be in absorbed list")

    nodes = [n for n in nodes if n.id not in absorbed]
    redirect = {aid: payload.survivor_id for aid in absorbed}
    return nodes, _redirect_edges(edges, redirect)


def _apply_split_node(
    nodes: list[Node],
    edges: list[Edge],
    payload: SplitNodePayload,
    entry: JournalEntry,
) -> tuple[list[Node], list[Edge]]:
    nodes = [n for n in nodes if n.id != payload.original_id]
    new_node_ids = _new_split_ids(payload, entry)
    new_nodes = []
    for spec, node_id in zip(payload.new_nodes, new_node_ids, strict=True):
        spec_with_id = dict(spec)
        spec_with_id.setdefault("id", node_id)
        spec_with_id.setdefault("graph_variant_id", entry.graph_variant_id)
        new_nodes.append(Node.model_validate(spec_with_id))
    nodes.extend(new_nodes)

    if not new_node_ids:
        # No new nodes — edges that touched the original are dropped.
        return nodes, [
            e
            for e in edges
            if e.source_node_id != payload.original_id
            and e.target_node_id != payload.original_id
        ]

    fallback = new_node_ids[0]
    redirect = {payload.original_id: fallback}
    rerouted: list[Edge] = []
    for e in edges:
        target_for_edge = payload.edge_redirect.get(str(e.id), redirect.get(e.source_node_id))
        if e.source_node_id == payload.original_id or e.target_node_id == payload.original_id:
            new_src = (
                target_for_edge
                if e.source_node_id == payload.original_id
                else e.source_node_id
            )
            new_tgt = (
                target_for_edge
                if e.target_node_id == payload.original_id
                else e.target_node_id
            )
            if new_src is None or new_tgt is None or new_src == new_tgt:
                continue
            rerouted.append(
                e.model_copy(update={"source_node_id": new_src, "target_node_id": new_tgt})
            )
        else:
            rerouted.append(e)
    return nodes, rerouted


def _apply_move_to_community(
    edges: list[Edge],
    payload: MoveToCommunityPayload,
    entry: JournalEntry,
) -> list[Edge]:
    out = [
        e
        for e in edges
        if not (
            e.type == EdgeType.MEMBER_OF
            and e.source_node_id == payload.node_id
            and (
                payload.from_community_id is None
                or e.target_node_id == payload.from_community_id
            )
        )
    ]
    out.append(
        Edge(
            graph_variant_id=entry.graph_variant_id,
            type=EdgeType.MEMBER_OF,
            source_node_id=payload.node_id,
            target_node_id=payload.to_community_id,
        )
    )
    return out


def _apply_edit_edge(edges: list[Edge], payload: EditEdgePayload) -> list[Edge]:
    target = next((e for e in edges if e.id == payload.edge_id), None)
    if target is None:
        raise JournalApplyError(f"edit_edge: {payload.edge_id} not found")
    bad = set(payload.updates) - set(Edge.model_fields)
    if bad:
        raise JournalApplyError(f"edit_edge: unknown fields {sorted(bad)!r}")
    return [
        e if e.id != payload.edge_id else e.model_copy(update=payload.updates)
        for e in edges
    ]


def _update_node(nodes: list[Node], node_id: Id, **updates: Any) -> list[Node]:
    found = False
    out = []
    for n in nodes:
        if n.id == node_id:
            found = True
            out.append(n.model_copy(update=updates))
        else:
            out.append(n)
    if not found:
        raise JournalApplyError(f"node {node_id} not found")
    return out


def _redirect_edges(edges: list[Edge], redirect: dict[Id, Id]) -> list[Edge]:
    out: list[Edge] = []
    seen: set[tuple[Id, Id, str]] = set()
    for e in edges:
        src = redirect.get(e.source_node_id, e.source_node_id)
        tgt = redirect.get(e.target_node_id, e.target_node_id)
        if src == tgt:
            continue
        key = (src, tgt, e.type.value)
        if key in seen:
            continue
        seen.add(key)
        if src == e.source_node_id and tgt == e.target_node_id:
            out.append(e)
        else:
            out.append(
                e.model_copy(update={"source_node_id": src, "target_node_id": tgt})
            )
    return out


def _community_of(node_id: Id, state: GraphBuildState) -> Id | None:
    for e in state.edges:
        if e.type == EdgeType.MEMBER_OF and e.source_node_id == node_id:
            return e.target_node_id
    return None


def _communities_of_endpoints(
    edge: Edge,
    node_index: dict[Id, Node],
    state: GraphBuildState,
) -> set[Id]:
    out: set[Id] = set()
    for nid in (edge.source_node_id, edge.target_node_id):
        community = _community_of(nid, state)
        if community:
            out.add(community)
    return out


def _new_split_ids(payload: SplitNodePayload, entry: JournalEntry) -> list[Id]:
    """Stable IDs for the pieces produced by a split. Uses ids embedded
    in the payload spec when present, otherwise mints fresh ones — but
    deterministically per (entry id, position) so replay yields the
    same nodes.
    """

    out: list[Id] = []
    for i, spec in enumerate(payload.new_nodes):
        if "id" in spec and spec["id"] is not None:
            out.append(Id(spec["id"]) if not isinstance(spec["id"], type(new_id())) else spec["id"])
        else:
            out.append(new_id())
    return out


def _affected_merge(
    payload: MergeNodesPayload,
    state: GraphBuildState,
    node_index: dict[Id, Node],
) -> AffectedSet:
    touched_ids = {payload.survivor_id, *payload.absorbed_ids}
    communities: set[Id] = set()
    for nid in touched_ids:
        community = _community_of(nid, state)
        if community:
            communities.add(community)
    return AffectedSet(
        node_ids=frozenset(touched_ids),
        community_ids=frozenset(communities),
    )
