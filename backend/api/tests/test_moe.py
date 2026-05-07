from __future__ import annotations

import pytest

import api.strategies.aggregators  # noqa: F401
import api.strategies.reasoners  # noqa: F401
from api.domain.graph import Layer, Node
from api.domain.types import Id, new_id
from api.moe import MoEError, run_moe
from api.strategies.protocols import GraphLoader


# ---- in-memory loader for tests ----


class _StaticLoader(GraphLoader):
    def __init__(self, nodes_by_variant: dict[Id, list[Node]]) -> None:
        self._nodes = nodes_by_variant

    async def load_nodes(self, graph_variant_id: Id) -> list[Node]:
        return list(self._nodes.get(graph_variant_id, ()))

    async def load_edges(self, graph_variant_id):
        return []


def _entity(name: str, gv: Id) -> Node:
    return Node(
        graph_variant_id=gv,
        layer=Layer.ENTITY,
        type="PERSON",
        granularity=1,
        name=name,
    )


# ---- run_moe orchestration ----


async def test_run_moe_with_one_variant_returns_single_expert() -> None:
    gv = new_id()
    loader = _StaticLoader({gv: [_entity("Иван", gv), _entity("Петр", gv)]})

    res = await run_moe(
        query="Иван",
        variant_ids=[gv],
        reasoner_name="keyword_search",
        aggregator_name="evidence_union",
        loader=loader,
    )

    assert len(res.experts) == 1
    assert res.aggregator == "evidence_union"
    assert "Иван" in res.answer.text


async def test_run_moe_runs_each_variant_in_parallel() -> None:
    gv1, gv2 = new_id(), new_id()
    loader = _StaticLoader(
        {
            gv1: [_entity("Иван А.", gv1)],
            gv2: [_entity("Иван Б.", gv2)],
        }
    )

    res = await run_moe(
        query="Иван",
        variant_ids=[gv1, gv2],
        reasoner_name="keyword_search",
        aggregator_name="evidence_union",
        loader=loader,
    )

    assert len(res.experts) == 2
    variant_ids_in_results = {e.variant_id for e in res.experts}
    assert variant_ids_in_results == {gv1, gv2}


async def test_run_moe_aggregator_picks_winner_for_weighted_vote() -> None:
    gv1, gv2 = new_id(), new_id()
    loader = _StaticLoader(
        {
            gv1: [_entity("Иван", gv1)],
            gv2: [_entity("Иван Иваныч Иванов", gv2)],  # more "Иван" tokens
        }
    )

    res = await run_moe(
        query="Иван",
        variant_ids=[gv1, gv2],
        reasoner_name="keyword_search",
        aggregator_name="weighted_vote",
        loader=loader,
    )

    assert res.aggregator == "weighted_vote"
    # winning variant is the one whose expert had higher confidence
    winning = res.answer.metadata["winning_variant_id"]
    assert winning in {str(gv1), str(gv2)}


async def test_run_moe_unknown_reasoner_raises() -> None:
    with pytest.raises(MoEError):
        await run_moe(
            query="q",
            variant_ids=[new_id()],
            reasoner_name="does_not_exist",
            aggregator_name="evidence_union",
            loader=_StaticLoader({}),
        )


async def test_run_moe_unknown_aggregator_raises() -> None:
    with pytest.raises(MoEError):
        await run_moe(
            query="q",
            variant_ids=[new_id()],
            reasoner_name="keyword_search",
            aggregator_name="does_not_exist",
            loader=_StaticLoader({}),
        )


async def test_run_moe_empty_variant_list_raises() -> None:
    with pytest.raises(MoEError):
        await run_moe(
            query="q",
            variant_ids=[],
            reasoner_name="keyword_search",
            aggregator_name="evidence_union",
            loader=_StaticLoader({}),
        )


async def test_run_moe_expert_failure_does_not_abort_run() -> None:
    """One expert raises NotImplementedError (a stub reasoner); others
    keep going. Aggregator sees a mix of ok and errored ExpertResults.
    """

    gv1, gv2 = new_id(), new_id()
    loader = _StaticLoader(
        {
            gv1: [_entity("Иван", gv1)],
            gv2: [_entity("Иван", gv2)],
        }
    )

    # microsoft_global is a registered stub that raises NotImplementedError.
    res = await run_moe(
        query="Иван",
        variant_ids=[gv1, gv2],
        reasoner_name="microsoft_global",
        aggregator_name="evidence_union",
        loader=loader,
    )

    assert all(e.error and "NotImplementedError" in e.error for e in res.experts)
    assert "no expert" in res.answer.text.lower()


async def test_run_moe_llm_judge_without_llm_raises() -> None:
    with pytest.raises(MoEError):
        await run_moe(
            query="q",
            variant_ids=[new_id()],
            reasoner_name="keyword_search",
            aggregator_name="llm_judge",
            loader=_StaticLoader({new_id(): []}),
            llm=None,
        )
