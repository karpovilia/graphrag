"""Tests for the canonical-alias cleaner (manual merges survive re-ingestion)."""

from __future__ import annotations

from uuid import uuid4

from api.domain.curation import JournalOp
from api.domain.graph import Edge, EdgeType, Layer, Node
from api.strategies import GraphBuildState
from api.strategies.cleaners.canonical_alias import (
    CanonicalAlias,
    canonical_aliases_from_merges,
)

VID = uuid4()


def _ent(name: str, *, summary: str | None = None) -> Node:
    return Node(
        id=uuid4(), graph_variant_id=VID, layer=Layer.ENTITY, type="PERSON",
        granularity=1, name=name, summary=summary,
    )


def _edge(src, tgt, type_=EdgeType.ENTITY_RELATION):
    return Edge(id=uuid4(), graph_variant_id=VID, type=type_,
                source_node_id=src, target_node_id=tgt)


async def test_alias_folds_dup_into_canonical_and_redirects_edges():
    ivanov = _ent("Иванов", summary="long summary here")
    ivanov_full = _ent("Иванов И.И.")
    petrov = _ent("Петров")
    other = _ent("ВШЭ", )
    # ivanov_full relates to ВШЭ; after merge that edge must point from Иванов.
    edges = [_edge(ivanov_full.id, other.id), _edge(petrov.id, other.id)]
    state = GraphBuildState(nodes=[ivanov, ivanov_full, petrov, other], edges=edges)

    out = await CanonicalAlias().clean(
        state, params={"aliases": {"Иванов И.И.": "Иванов"}}
    )

    ents = [n for n in out.nodes if n.layer == Layer.ENTITY]
    # exactly one Иванов (the full form absorbed), Петров + ВШЭ untouched
    assert sum(1 for n in ents if n.name == "Иванов") == 1
    assert "Иванов И.И." not in {n.name for n in ents}
    assert {"Петров", "ВШЭ"} <= {n.name for n in ents}
    survivor = next(n for n in ents if n.name == "Иванов")
    assert survivor.canonical_id == survivor.id
    # the absorbed node's edge now originates from the survivor
    redirected = [e for e in out.edges if e.source_node_id == survivor.id]
    assert len(redirected) == 1
    # one MERGE_NODES journalled
    merges = [j for j in out.journal if j.op == JournalOp.MERGE_NODES]
    assert len(merges) == 1
    assert "canonical alias" in merges[0].payload["reason"]


async def test_no_aliases_is_noop():
    state = GraphBuildState(nodes=[_ent("A"), _ent("B")], edges=[])
    out = await CanonicalAlias().clean(state, params={})
    assert out is state


async def test_rename_only_single_node():
    n = _ent("НИУ ВШЭ")
    state = GraphBuildState(nodes=[n], edges=[])
    out = await CanonicalAlias().clean(state, params={"aliases": {"НИУ ВШЭ": "ВШЭ"}})
    assert [e.name for e in out.nodes] == ["ВШЭ"]
    assert out.nodes[0].canonical_id == n.id


async def test_case_insensitive_match():
    a, b = _ent("apple"), _ent("APPLE", summary="s")
    state = GraphBuildState(nodes=[a, b], edges=[])
    out = await CanonicalAlias().clean(
        state, params={"aliases": {"apple": "Apple"}, "case_insensitive": True}
    )
    ents = [n for n in out.nodes if n.layer == Layer.ENTITY]
    assert len(ents) == 1
    assert ents[0].name == "Apple"


def test_aliases_from_merges_resolves_chain():
    # a→b, b→c  ⇒  a→c, b→c
    m = canonical_aliases_from_merges([("a", "b"), ("b", "c")])
    assert m["a"] == "c"
    assert m["b"] == "c"
