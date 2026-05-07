from __future__ import annotations

import pytest

import api.tools  # noqa: F401  — trigger @register
from api.domain.graph import Edge, EdgeType, Layer, Node
from api.domain.types import Id, new_id
from api.strategies.protocols import GraphLoader
from api.strategies.registry import tools as tools_registry
from api.tools import (
    CorpusCollocations,
    ShowEvidenceChunks,
    ShowNeighbors,
    SummarizeSubgraph,
    WikidataLookup,
)


# ---- registry ----


def test_tools_registered() -> None:
    names = set(tools_registry.names())
    assert {
        "show_neighbors",
        "show_evidence_chunks",
        "summarize_subgraph",
        "corpus_collocations",
        "wikidata_lookup",
    }.issubset(names)


@pytest.mark.parametrize(
    "cls,applies",
    [
        (ShowNeighbors, ()),
        (ShowEvidenceChunks, ()),
        (SummarizeSubgraph, ()),
        (CorpusCollocations, ("PERSON", "ORG", "PLACE")),
        (WikidataLookup, ("PERSON", "ORG", "PLACE")),
    ],
)
def test_tools_applies_to_metadata(cls, applies) -> None:
    assert cls.applies_to == applies
    assert cls.descriptor.kind == "tool"


# ---- helpers ----


class _StaticLoader(GraphLoader):
    def __init__(self, nodes: list[Node], edges: list[Edge]) -> None:
        self._nodes = nodes
        self._edges = edges

    async def load_nodes(self, graph_variant_id: Id) -> list[Node]:
        return list(self._nodes)

    async def load_edges(self, graph_variant_id: Id) -> list[Edge]:
        return list(self._edges)


def _entity(name: str, gv: Id, type_: str = "PERSON") -> Node:
    return Node(
        graph_variant_id=gv,
        layer=Layer.ENTITY,
        type=type_,
        granularity=1,
        name=name,
    )


def _chunk(name: str, gv: Id, *, start: int = 0, end: int = 100) -> Node:
    return Node(
        graph_variant_id=gv,
        layer=Layer.CHUNK,
        type="CHUNK",
        granularity=0,
        name=name,
        attributes={"char_start": start, "char_end": end},
    )


def _community(name: str, gv: Id) -> Node:
    return Node(
        graph_variant_id=gv,
        layer=Layer.COMMUNITY,
        type="COMMUNITY",
        granularity=2,
        name=name,
    )


# ---- ShowNeighbors ----


async def test_show_neighbors_groups_by_edge_type() -> None:
    gv = new_id()
    a, b, c, ch = _entity("A", gv), _entity("B", gv), _entity("C", gv), _chunk("c1", gv)
    edges = [
        Edge(graph_variant_id=gv, type=EdgeType.ENTITY_RELATION, source_node_id=a.id, target_node_id=b.id, weight=1.0),
        Edge(graph_variant_id=gv, type=EdgeType.ENTITY_RELATION, source_node_id=a.id, target_node_id=c.id, weight=2.0),
        Edge(graph_variant_id=gv, type=EdgeType.MENTIONED_IN, source_node_id=a.id, target_node_id=ch.id),
    ]
    loader = _StaticLoader([a, b, c, ch], edges)
    res = await ShowNeighbors().run(a, gv, {}, loader)

    assert set(res["neighbors_by_edge_type"]) == {"entity_relation", "mentioned_in"}
    rel = res["neighbors_by_edge_type"]["entity_relation"]
    assert {n["name"] for n in rel} == {"B", "C"}
    assert res["total"] == 3


async def test_show_neighbors_layer_filter() -> None:
    gv = new_id()
    a, b, ch = _entity("A", gv), _entity("B", gv), _chunk("c1", gv)
    edges = [
        Edge(graph_variant_id=gv, type=EdgeType.ENTITY_RELATION, source_node_id=a.id, target_node_id=b.id),
        Edge(graph_variant_id=gv, type=EdgeType.MENTIONED_IN, source_node_id=a.id, target_node_id=ch.id),
    ]
    res = await ShowNeighbors().run(
        a, gv, {"include_layers": ["entity"]}, _StaticLoader([a, b, ch], edges)
    )
    flat = [n for group in res["neighbors_by_edge_type"].values() for n in group]
    assert all(n["layer"] == "entity" for n in flat)


# ---- ShowEvidenceChunks ----


async def test_show_evidence_chunks_for_entity() -> None:
    gv = new_id()
    a, c1, c2 = _entity("A", gv), _chunk("c1", gv), _chunk("c2", gv)
    edges = [
        Edge(graph_variant_id=gv, type=EdgeType.MENTIONED_IN, source_node_id=a.id, target_node_id=c1.id),
        Edge(graph_variant_id=gv, type=EdgeType.MENTIONED_IN, source_node_id=a.id, target_node_id=c2.id),
    ]
    res = await ShowEvidenceChunks().run(a, gv, {}, _StaticLoader([a, c1, c2], edges))
    assert res["total_found"] == 2
    assert {ch["name"] for ch in res["chunks"]} == {"c1", "c2"}


async def test_show_evidence_chunks_for_community_via_members() -> None:
    gv = new_id()
    comm = _community("comm-0", gv)
    member = _entity("M", gv)
    chunk = _chunk("c1", gv)
    edges = [
        Edge(graph_variant_id=gv, type=EdgeType.MEMBER_OF, source_node_id=member.id, target_node_id=comm.id),
        Edge(graph_variant_id=gv, type=EdgeType.MENTIONED_IN, source_node_id=member.id, target_node_id=chunk.id),
    ]
    res = await ShowEvidenceChunks().run(comm, gv, {}, _StaticLoader([comm, member, chunk], edges))
    assert res["total_found"] == 1


# ---- SummarizeSubgraph ----


async def test_summarize_subgraph_depth_one() -> None:
    gv = new_id()
    a, b, c = _entity("A", gv), _entity("B", gv), _entity("C", gv, type_="ORG")
    edges = [
        Edge(graph_variant_id=gv, type=EdgeType.ENTITY_RELATION, source_node_id=a.id, target_node_id=b.id),
        Edge(graph_variant_id=gv, type=EdgeType.ENTITY_RELATION, source_node_id=a.id, target_node_id=c.id),
    ]
    res = await SummarizeSubgraph().run(
        a, gv, {"depth": 1}, _StaticLoader([a, b, c], edges)
    )
    assert res["node_count"] == 3
    assert res["by_type"]["PERSON"] == 2
    assert res["by_type"]["ORG"] == 1


async def test_summarize_subgraph_depth_zero_only_self() -> None:
    gv = new_id()
    a = _entity("A", gv)
    res = await SummarizeSubgraph().run(a, gv, {"depth": 0}, _StaticLoader([a], []))
    assert res["node_count"] == 1


# ---- CorpusCollocations ----


async def test_corpus_collocations_counts_shared_chunks() -> None:
    gv = new_id()
    focus = _entity("Иванов", gv)
    other_a = _entity("ВШЭ", gv, type_="ORG")
    other_b = _entity("Петров", gv)
    c1, c2 = _chunk("c1", gv), _chunk("c2", gv)
    edges = [
        # focus mentioned in c1, c2
        Edge(graph_variant_id=gv, type=EdgeType.MENTIONED_IN, source_node_id=focus.id, target_node_id=c1.id),
        Edge(graph_variant_id=gv, type=EdgeType.MENTIONED_IN, source_node_id=focus.id, target_node_id=c2.id),
        # ВШЭ also in c1 and c2 → 2 shared
        Edge(graph_variant_id=gv, type=EdgeType.MENTIONED_IN, source_node_id=other_a.id, target_node_id=c1.id),
        Edge(graph_variant_id=gv, type=EdgeType.MENTIONED_IN, source_node_id=other_a.id, target_node_id=c2.id),
        # Петров only in c1 → 1 shared
        Edge(graph_variant_id=gv, type=EdgeType.MENTIONED_IN, source_node_id=other_b.id, target_node_id=c1.id),
    ]
    res = await CorpusCollocations().run(
        focus, gv, {}, _StaticLoader([focus, other_a, other_b, c1, c2], edges)
    )
    assert res["shared_chunk_count"] == 2
    names_by_count = {co["name"]: co["shared_chunks"] for co in res["co_mentions"]}
    assert names_by_count["ВШЭ"] == 2
    assert names_by_count["Петров"] == 1


async def test_corpus_collocations_no_chunks_returns_empty() -> None:
    gv = new_id()
    focus = _entity("Иванов", gv)
    res = await CorpusCollocations().run(
        focus, gv, {}, _StaticLoader([focus], [])
    )
    assert res["shared_chunk_count"] == 0
    assert res["co_mentions"] == []


# ---- WikidataLookup stub ----


async def test_wikidata_lookup_stub_returns_not_implemented_marker() -> None:
    gv = new_id()
    focus = _entity("Иванов", gv)
    res = await WikidataLookup().run(focus, gv, {}, _StaticLoader([focus], []))
    assert res["status"] == "not_implemented"
    assert res["node_name"] == "Иванов"
