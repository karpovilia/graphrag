from __future__ import annotations

import api.strategies.rankers  # noqa: F401  — trigger @register
import numpy as np
from api.domain.graph import Edge, EdgeType, Layer, Node
from api.domain.types import Id, new_id
from api.strategies.rankers import GATRanker, TfIdfCosineRanker
from api.strategies.rankers._gat_model import (
    GATEncoder,
    feature_dim,
    save_embeddings,
    tensorize,
)
from api.strategies.registry import rankers


def _node(
    name: str,
    summary: str | None = None,
    *,
    graph_variant_id: Id | None = None,
) -> Node:
    return Node(
        graph_variant_id=graph_variant_id or new_id(),
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


# ---- GAT model + ranker ----


def test_tensorize_produces_consistent_shapes() -> None:
    gv = new_id()
    nodes = [
        _node("Иван", graph_variant_id=gv),
        _node("Петр", graph_variant_id=gv),
        _node("ВШЭ", graph_variant_id=gv),
    ]
    edges = [
        Edge(
            graph_variant_id=gv,
            type=EdgeType.ENTITY_RELATION,
            source_node_id=nodes[0].id,
            target_node_id=nodes[1].id,
            weight=1.0,
        ),
    ]
    tg = tensorize(nodes, edges)
    assert tg.features.shape == (3, feature_dim())
    # symmetric: forward + reverse for the one edge → 2 entries.
    assert tg.edge_index.shape == (2, 2)


def test_gat_encoder_forward_smoke() -> None:
    gv = new_id()
    nodes = [_node(f"n{i}", graph_variant_id=gv) for i in range(5)]
    edges = [
        Edge(
            graph_variant_id=gv,
            type=EdgeType.ENTITY_RELATION,
            source_node_id=nodes[i].id,
            target_node_id=nodes[i + 1].id,
            weight=1.0,
        )
        for i in range(4)
    ]
    tg = tensorize(nodes, edges)
    model = GATEncoder(in_dim=feature_dim(), hidden=8, out=4, heads=2)
    emb = model(tg.features, tg.edge_index)
    assert emb.shape == (5, 4)
    # Output is L2-normalized: every row's norm ≈ 1.
    norms = emb.detach().pow(2).sum(dim=-1).sqrt()
    assert (norms - 1).abs().max().item() < 1e-3


async def test_gat_falls_back_when_embeddings_missing() -> None:
    """Without a trained .npz on disk, GATRanker degrades to
    TfIdfCosineRanker rather than raising — the wizard works without
    requiring training upfront."""

    cands = [
        _node("Иванов лаборатория"),
        _node("Петров"),
    ]
    ranked = await GATRanker().rank("Иванов", cands, {})
    # tfidf would put 'Иванов лаборатория' first.
    assert ranked[0].name == "Иванов лаборатория"


async def test_gat_uses_embeddings_when_present(tmp_path) -> None:
    """When trained embeddings exist, the ranker blends TF-IDF with
    structural centrality. We seed a deliberately misleading TF-IDF
    landscape (only one of the candidates has the query token) but
    embeddings tell us a different node is structurally central."""

    gv = new_id()
    a = _node("Иванов", graph_variant_id=gv)
    b = _node("Петров", graph_variant_id=gv)
    c = _node("Сидоров", graph_variant_id=gv)

    # Embeddings: a and b live at (1, 0); c at (0, 1). With a as the
    # only TF-IDF hit, the centroid of the top-1 anchor is (1, 0); b
    # scores high structurally even though TF-IDF gave it 0.
    emb = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    embeddings_path = tmp_path / "gat.npz"
    save_embeddings(
        embeddings_path,
        node_ids=[a.id, b.id, c.id],
        embeddings=__import__("torch").from_numpy(emb),
        feature_dim=feature_dim(),
    )

    ranked = await GATRanker().rank(
        "Иванов",
        [a, b, c],
        {
            "embeddings_path": str(embeddings_path),
            "alpha_tfidf": 0.5,
            "beta_structural": 0.5,
            "top_k_anchor": 1,
        },
    )
    # b is structurally identical to the anchor a; with equal weights
    # it should beat c (no overlap on either axis).
    assert ranked[-1].name == "Сидоров"
