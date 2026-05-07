from __future__ import annotations

import pytest

import api.strategies.rankers  # noqa: F401  — trigger @register
from api.domain.graph import Layer, Node
from api.domain.types import new_id
from api.strategies.rankers import GATRanker, TfIdfCosineRanker
from api.strategies.registry import rankers


def _node(name: str, summary: str | None = None) -> Node:
    return Node(
        graph_variant_id=new_id(),
        layer=Layer.ENTITY,
        type="PERSON",
        granularity=1,
        name=name,
        summary=summary,
    )


def test_rankers_registered() -> None:
    assert "tfidf_cosine" in rankers.names()
    assert "gat" in rankers.names()


def test_descriptors_metadata() -> None:
    assert TfIdfCosineRanker.descriptor.cost_hint == "cheap"
    assert GATRanker.descriptor.cost_hint == "moderate"


# ---- TfIdfCosineRanker ----


async def test_tfidf_ranks_by_token_overlap() -> None:
    cands = [
        _node("Иванов И.А.", summary="Глава лаборатории НЛП в ВШЭ"),
        _node("Петров", summary="Студент"),
        _node("Сидоров", summary="Лаборант лаборатории"),
    ]
    ranked = await TfIdfCosineRanker().rank("лаборатории НЛП", cands, {})
    assert ranked[0].name == "Иванов И.А."  # most overlap


async def test_tfidf_handles_empty_candidates() -> None:
    res = await TfIdfCosineRanker().rank("anything", [], {})
    assert res == []


async def test_tfidf_no_query_tokens_keeps_order() -> None:
    cands = [_node("X"), _node("Y"), _node("Z")]
    res = await TfIdfCosineRanker().rank("a", cands, {"min_token_length": 3})
    # query tokens are dropped (too short); ranker preserves input order
    assert [n.name for n in res] == ["X", "Y", "Z"]


async def test_tfidf_idf_downweights_common_tokens() -> None:
    """A token present in every candidate carries low IDF, so it
    contributes ~0 to the score; the discriminative token wins."""

    cands = [
        _node("Иванов лаборатория"),
        _node("Петров лаборатория"),
        _node("Иванов"),
    ]
    ranked = await TfIdfCosineRanker().rank("Иванов", cands, {})
    # Both 'Иванов' candidates float to the top
    assert ranked[0].name in {"Иванов", "Иванов лаборатория"}
    assert ranked[-1].name == "Петров лаборатория"


# ---- GATRanker stub ----


async def test_gat_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        await GATRanker().rank("q", [_node("X")], {})
