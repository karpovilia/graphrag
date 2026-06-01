from __future__ import annotations

import pytest

from api.agents import SimilarityMergeCandidates
from api.domain.curation import SuggestionAction
from api.domain.graph import Edge, EdgeType, Layer, Node
from api.domain.types import Id, new_id
from api.strategies.state import GraphBuildState


def _node(name: str, gv: Id, *, summary: str | None = None, lemma: str | None = None) -> Node:
    attrs: dict = {}
    if lemma:
        attrs["lemma"] = lemma
    return Node(
        graph_variant_id=gv,
        layer=Layer.ENTITY,
        type="PERSON",
        granularity=1,
        name=name,
        summary=summary,
        attributes=attrs,
    )


def _rel(src: Id, tgt: Id, gv: Id) -> Edge:
    return Edge(
        graph_variant_id=gv,
        type=EdgeType.ENTITY_RELATION,
        source_node_id=src,
        target_node_id=tgt,
        weight=1.0,
    )


@pytest.mark.asyncio
async def test_similarity_merge_picks_lookalike_pair() -> None:
    gv = new_id()
    # Two near-identical names ("Иван Иванов" vs "Иванов Иван") with
    # different lemmas (entity_dedup wouldn't fire) but overlapping
    # neighbours: this is exactly what the agent should surface.
    a = _node("Иван Иванов", gv, lemma="иван")
    b = _node("Иванов Иван", gv, lemma="иванов")
    c = _node("Coworker Bob", gv, lemma="coworker")
    nodes = [a, b, c]
    edges = [_rel(a.id, c.id, gv), _rel(b.id, c.id, gv)]
    state = GraphBuildState(nodes=nodes, edges=edges, journal=[])

    suggestions = await SimilarityMergeCandidates().propose(gv, state, {})

    assert len(suggestions) >= 1
    top = suggestions[0]
    assert top.action == SuggestionAction.MERGE
    target_ids = set(top.target_node_ids)
    assert {a.id, b.id} == target_ids
    assert top.confidence > 0.55
    assert "score" in top.payload
    assert "components" in top.payload
    components = top.payload["components"]
    # Same words in different order — SequenceMatcher gives ~0.5 here;
    # the score lift comes from the perfect neighbour Jaccard.
    assert components["name_similarity"] > 0.4
    assert components["neighbor_jaccard"] == 1.0


@pytest.mark.asyncio
async def test_similarity_merge_orders_descending_by_score() -> None:
    gv = new_id()
    # Two near-identical pairs in the same first-letter bucket so both
    # survive the prefilter; the lookalike one must rank ahead.
    strong_a = _node("Apple Inc", gv, lemma="apple")
    strong_b = _node("Apple Incorporated", gv, lemma="incorporated")
    weak_a = _node("Acme", gv, lemma="acme")
    weak_b = _node("Aurora", gv, lemma="aurora")
    state = GraphBuildState(
        nodes=[strong_a, strong_b, weak_a, weak_b],
        edges=[],
        journal=[],
    )

    suggestions = await SimilarityMergeCandidates().propose(
        gv, state, {"min_score": 0.0}
    )
    assert len(suggestions) >= 2
    confidences = [s.confidence for s in suggestions]
    assert confidences == sorted(confidences, reverse=True)
    assert {strong_a.id, strong_b.id} == set(suggestions[0].target_node_ids)


@pytest.mark.asyncio
async def test_similarity_merge_skip_same_lemma_by_default() -> None:
    gv = new_id()
    # Same lemma, same type — entity_dedup territory. Default config should skip.
    a = _node("Иван", gv, lemma="иван")
    b = _node("Ивана", gv, lemma="иван")
    state = GraphBuildState(nodes=[a, b], edges=[], journal=[])
    out = await SimilarityMergeCandidates().propose(gv, state, {})
    assert out == []
    # When opting in, the pair should appear (lower min_score so the
    # neighbour-less pair survives the threshold).
    out2 = await SimilarityMergeCandidates().propose(
        gv, state, {"skip_same_lemma": False, "min_score": 0.0}
    )
    assert len(out2) == 1


@pytest.mark.asyncio
async def test_similarity_merge_caps_via_max_suggestions() -> None:
    gv = new_id()
    # Make a clique of 5 lookalike nodes — there are 10 candidate pairs;
    # cap at 3.
    nodes = [
        _node(f"Alpha{ch}", gv, lemma=f"alpha{ch}")
        for ch in "ABCDE"
    ]
    state = GraphBuildState(nodes=nodes, edges=[], journal=[])
    out = await SimilarityMergeCandidates().propose(
        gv, state, {"max_suggestions": 3, "min_score": 0.0}
    )
    assert len(out) == 3


@pytest.mark.asyncio
async def test_similarity_merge_payload_picks_longer_summary_as_survivor() -> None:
    gv = new_id()
    short = _node("Acme Co", gv, lemma="acme", summary="short")
    long = _node("Acme Company", gv, lemma="company", summary="much longer summary text")
    state = GraphBuildState(nodes=[short, long], edges=[], journal=[])
    out = await SimilarityMergeCandidates().propose(gv, state, {"min_score": 0.0})
    assert out, "expected at least one suggestion"
    survivor = out[0].payload["survivor_id"]
    assert survivor == str(long.id)
