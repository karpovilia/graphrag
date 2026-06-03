from __future__ import annotations

import pytest

from api.domain.graph import Layer, Node
from api.domain.types import Id, new_id
from api.strategies.protocols import GraphLoader
from api.strategies.reasoners import (
    KeywordSearchReasoner,
    LightRAGDualKeyword,
    MicrosoftGlobalSearch,
    MicrosoftLocalSearch,
)


class _StaticLoader(GraphLoader):
    def __init__(self, nodes_by_variant: dict[Id, list[Node]]) -> None:
        self._nodes = nodes_by_variant

    async def load_nodes(self, graph_variant_id: Id) -> list[Node]:
        return list(self._nodes.get(graph_variant_id, ()))

    async def load_edges(self, graph_variant_id):
        return []


def _node(name: str, summary: str | None = None) -> Node:
    return Node(
        graph_variant_id=new_id(),
        layer=Layer.ENTITY,
        type="PERSON",
        granularity=1,
        name=name,
        summary=summary,
    )


# ---- KeywordSearchReasoner ----


async def test_keyword_search_ranks_by_match_count() -> None:
    gv = new_id()
    nodes = [
        _node("Иванов Иван Иванович"),  # 1 match for "иван"
        _node("Петров"),  # 0 matches
        _node("Иван Грозный"),  # 1 match
        _node("Мария"),
    ]
    loader = _StaticLoader({gv: nodes})
    result = await KeywordSearchReasoner().reason(
        query="Расскажи про Иван", graph_variant_ids=[gv], params={"top_k": 10}, loader=loader
    )
    assert "Иван" in result.text
    assert len(result.evidence_node_ids) == 2  # Иванов + Иван Грозный


async def test_keyword_search_top_k_limits() -> None:
    gv = new_id()
    nodes = [_node(f"Иван {i}") for i in range(20)]
    loader = _StaticLoader({gv: nodes})
    result = await KeywordSearchReasoner().reason(
        query="Иван", graph_variant_ids=[gv], params={"top_k": 5}, loader=loader
    )
    assert len(result.evidence_node_ids) == 5


async def test_keyword_search_no_match_returns_empty_evidence() -> None:
    gv = new_id()
    loader = _StaticLoader({gv: [_node("Иванов"), _node("Петров")]})
    result = await KeywordSearchReasoner().reason(
        query="квадрокоптер", graph_variant_ids=[gv], params={}, loader=loader
    )
    assert result.evidence_node_ids == []
    assert "не найдено" in result.text
    assert result.confidence == 0.0


async def test_keyword_search_drops_stopwords_and_short_tokens() -> None:
    gv = new_id()
    nodes = [_node("Иван"), _node("в Москве")]
    loader = _StaticLoader({gv: nodes})
    result = await KeywordSearchReasoner().reason(
        query="кто в Москве",
        graph_variant_ids=[gv],
        params={},
        loader=loader,
    )
    # "кто" and "в" are stopwords; "Москве" survives.
    matched = result.metadata["matched_tokens"]
    assert "москве" in matched
    assert "кто" not in matched
    assert "в" not in matched


async def test_keyword_search_aggregates_across_variants() -> None:
    gv1, gv2 = new_id(), new_id()
    loader = _StaticLoader(
        {
            gv1: [_node("Иван А.")],
            gv2: [_node("Иван Б."), _node("Петров")],
        }
    )
    result = await KeywordSearchReasoner().reason(
        query="Иван", graph_variant_ids=[gv1, gv2], params={"top_k": 10}, loader=loader
    )
    assert len(result.evidence_node_ids) == 2


def test_keyword_search_descriptor_metadata() -> None:
    d = KeywordSearchReasoner.descriptor
    assert d.kind == "reasoner"
    assert d.name == "keyword_search"
    assert d.cost_hint == "cheap"


# ---- Stubs registered with metadata, raise on .reason() ----


@pytest.mark.parametrize(
    "cls,name,layers",
    [
        (MicrosoftGlobalSearch, "microsoft_global", (Layer.COMMUNITY, Layer.TOPIC)),
        (MicrosoftLocalSearch, "microsoft_local", (Layer.ENTITY,)),
        (LightRAGDualKeyword, "lightrag_dual_keyword", (Layer.ENTITY, Layer.COMMUNITY)),
    ],
)
def test_stub_reasoners_have_descriptors(cls, name, layers) -> None:
    d = cls.descriptor
    assert d.name == name
    assert d.kind == "reasoner"
    for layer in layers:
        assert layer in d.requires_layers


@pytest.mark.parametrize(
    "cls",
    [MicrosoftGlobalSearch, MicrosoftLocalSearch],
)
async def test_stub_reasoners_raise_not_implemented(cls) -> None:
    inst = cls()
    with pytest.raises(NotImplementedError):
        await inst.reason(
            query="x",
            graph_variant_ids=[new_id()],
            params={},
            loader=_StaticLoader({}),
        )


# ---- LightRAGDualKeyword (dual-level keyword retrieval) ----


def _community(name: str, summary: str | None = None) -> Node:
    return Node(
        graph_variant_id=new_id(),
        layer=Layer.COMMUNITY,
        type="COMMUNITY",
        granularity=2,
        name=name,
        summary=summary,
    )


async def test_lightrag_dual_splits_local_entities_and_global_themes() -> None:
    gv = new_id()
    entity = _node("Voxys")  # low-level hit on "voxys"
    other = _node("Мария")  # no hit
    theme = _community("Кластер 3", summary="Обсуждение интеграции Voxys")  # global hit
    loader = _StaticLoader({gv: [entity, other, theme]})

    result = await LightRAGDualKeyword().reason(
        query="интеграция Voxys",
        graph_variant_ids=[gv],
        params={},
        loader=loader,
    )

    assert entity.id in result.evidence_node_ids
    assert theme.id in result.evidence_node_ids
    assert other.id not in result.evidence_node_ids
    assert "сущности" in result.text.lower()
    assert "темы" in result.text.lower()
    assert result.metadata["local_count"] == 1
    assert result.metadata["global_count"] == 1


async def test_lightrag_recency_boost_reorders_recent_first() -> None:
    from datetime import datetime, timezone

    gv = new_id()
    old = Node(
        graph_variant_id=gv, layer=Layer.ENTITY, type="PERSON", granularity=1,
        name="Voxys старый", tx_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    recent = Node(
        graph_variant_id=gv, layer=Layer.ENTITY, type="PERSON", granularity=1,
        name="Voxys свежий", tx_from=datetime(2026, 3, 1, tzinfo=timezone.utc),
    )
    loader = _StaticLoader({gv: [old, recent]})

    # No boost → deterministic id order (both score 1 on "voxys").
    base = await LightRAGDualKeyword().reason(
        query="Voxys", graph_variant_ids=[gv], params={"recency_boost": 0}, loader=loader
    )
    # With boost + an as_of, the recent node must come first.
    boosted = await LightRAGDualKeyword().reason(
        query="Voxys",
        graph_variant_ids=[gv],
        params={"recency_boost": 5.0, "as_of": "2026-03-15T00:00:00Z", "half_life_days": 30},
        loader=loader,
    )
    assert set(base.evidence_node_ids) == {old.id, recent.id}
    assert boosted.evidence_node_ids[0] == recent.id


async def test_lightrag_dual_empty_when_no_match() -> None:
    gv = new_id()
    loader = _StaticLoader({gv: [_node("Мария")]})
    result = await LightRAGDualKeyword().reason(
        query="квантовая хромодинамика",
        graph_variant_ids=[gv],
        params={},
        loader=loader,
    )
    assert result.evidence_node_ids == []
    assert result.confidence == 0.0
