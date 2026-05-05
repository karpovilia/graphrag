from __future__ import annotations

import pytest

from api.domain.curation import JournalOp
from api.domain.graph import Edge, EdgeType, Layer, Node
from api.domain.types import Id, new_id
from api.llm import CompletionClient, CompletionParams, CompletionResult, Message
from api.strategies import GraphBuildState
from api.strategies.cleaners import LLMDeduplicator, ThresholdPruner


def _node(name: str, *, type_: str = "PERSON", summary: str | None = None) -> Node:
    return Node(
        graph_variant_id=new_id(),
        layer=Layer.ENTITY,
        type=type_,
        granularity=1,
        name=name,
        summary=summary,
    )


def _edge(src: Id, tgt: Id, *, weight: float | None = None, type_: EdgeType = EdgeType.ENTITY_RELATION) -> Edge:
    return Edge(
        graph_variant_id=new_id(),
        type=type_,
        source_node_id=src,
        target_node_id=tgt,
        weight=weight,
    )


# ---- ThresholdPruner ----


async def test_threshold_keeps_edges_at_or_above() -> None:
    a, b, c = _node("A"), _node("B"), _node("C")
    edges = [
        _edge(a.id, b.id, weight=0.9),
        _edge(a.id, c.id, weight=0.4),
        _edge(b.id, c.id, weight=0.6),
    ]
    state = GraphBuildState(nodes=[a, b, c], edges=edges)

    out = await ThresholdPruner().clean(state, {"weight_threshold": 0.5})

    kept_weights = sorted(e.weight for e in out.edges)
    assert kept_weights == [0.6, 0.9]
    assert out.nodes == state.nodes  # nodes untouched


async def test_threshold_unweighted_kept_by_default() -> None:
    a, b = _node("A"), _node("B")
    state = GraphBuildState(nodes=[a, b], edges=[_edge(a.id, b.id)])

    out = await ThresholdPruner().clean(state, {"weight_threshold": 0.5})

    assert len(out.edges) == 1


async def test_threshold_unweighted_dropped_when_flagged() -> None:
    a, b = _node("A"), _node("B")
    state = GraphBuildState(nodes=[a, b], edges=[_edge(a.id, b.id)])

    out = await ThresholdPruner().clean(
        state, {"weight_threshold": 0.5, "drop_unweighted": True}
    )

    assert out.edges == []


async def test_threshold_edge_type_filter() -> None:
    a, b = _node("A"), _node("B")
    e_relation = _edge(a.id, b.id, weight=0.1, type_=EdgeType.ENTITY_RELATION)
    e_mention = _edge(a.id, b.id, weight=0.1, type_=EdgeType.MENTIONED_IN)
    state = GraphBuildState(nodes=[a, b], edges=[e_relation, e_mention])

    out = await ThresholdPruner().clean(
        state,
        {"weight_threshold": 0.5, "edge_types": ["entity_relation"]},
    )

    # Only entity_relation evaluated against threshold; mention type is bypassed.
    assert len(out.edges) == 1
    assert out.edges[0].type == EdgeType.MENTIONED_IN


def test_threshold_descriptor_metadata() -> None:
    d = ThresholdPruner.descriptor
    assert d.kind == "cleaner"
    assert d.name == "threshold_prune"
    assert d.cost_hint == "cheap"
    assert "weight_threshold" in d.params_schema


# ---- LLMDeduplicator ----


class _FakeLLM(CompletionClient):
    """Replays canned responses based on user message content. Lets us
    drive merge decisions deterministically without a real Deepseek call.
    """

    provider = "fake"
    default_model = "fake-1"

    def __init__(self, decisions: dict[str, bool]) -> None:
        self._decisions = decisions
        self.calls: list[tuple[Message, ...]] = []

    async def complete(
        self,
        messages: list[Message],
        params: CompletionParams | None = None,
    ) -> CompletionResult:
        self.calls.append(tuple(messages))
        user_msg = messages[-1].content
        merge = False
        for marker, decision in self._decisions.items():
            if marker in user_msg:
                merge = decision
                break
        text = (
            '{"merge": true, "reason": "matched"}'
            if merge
            else '{"merge": false, "reason": "different"}'
        )
        return CompletionResult(text=text, model=self.default_model)


async def test_llm_dedup_merges_confirmed_pair() -> None:
    # Naive bucketing keys on lowercase first token, so both names need
    # to start with "Иванов" — production-grade lemma bucketing (which
    # would catch Иванов/Иванова) ships in the Phase 3 dedup agent.
    survivor = _node("Иванов И.А.", summary="Глава лаборатории НЛП")
    absorbed = _node("Иванов", summary="")
    other = _node("Петров")
    a_id, b_id = survivor.id, absorbed.id
    edges = [_edge(a_id, other.id, weight=0.9), _edge(b_id, other.id, weight=0.7)]
    state = GraphBuildState(nodes=[survivor, absorbed, other], edges=edges)

    llm = _FakeLLM({"Глава лаборатории": True})
    out = await LLMDeduplicator(llm=llm).clean(state, {"max_candidate_pairs": 10})

    surviving_ids = {n.id for n in out.nodes}
    assert survivor.id in surviving_ids
    assert absorbed.id not in surviving_ids

    # After redirect, two edges to `other` collapse into one (dedup).
    assert len(out.edges) == 1
    assert out.edges[0].source_node_id == survivor.id

    journal_ops = [j.op for j in out.journal]
    assert JournalOp.MERGE_NODES in journal_ops
    merge_payload = next(j.payload for j in out.journal if j.op == JournalOp.MERGE_NODES)
    assert merge_payload["survivor_id"] == str(survivor.id)
    assert str(absorbed.id) in merge_payload["absorbed_ids"]


async def test_llm_dedup_keeps_when_llm_says_no() -> None:
    a = _node("Иванов И.А.")
    b = _node("Иванов")
    state = GraphBuildState(nodes=[a, b], edges=[])

    llm = _FakeLLM({"Иванов": False})
    out = await LLMDeduplicator(llm=llm).clean(state, {"max_candidate_pairs": 10})

    assert {n.id for n in out.nodes} == {a.id, b.id}
    assert out.journal == []


async def test_llm_dedup_only_pairs_within_same_type() -> None:
    person = _node("Иванов", type_="PERSON")
    org = _node("Иванов", type_="ORG")
    state = GraphBuildState(nodes=[person, org], edges=[])

    llm = _FakeLLM({"Иванов": True})
    out = await LLMDeduplicator(llm=llm).clean(state, {"max_candidate_pairs": 10})

    # No cross-type bucketing → no LLM call → both nodes retained.
    assert llm.calls == []
    assert {n.id for n in out.nodes} == {person.id, org.id}


async def test_llm_dedup_caps_candidate_pairs() -> None:
    nodes = [_node("Иванов") for _ in range(5)]
    state = GraphBuildState(nodes=nodes, edges=[])

    llm = _FakeLLM({"Иванов": False})
    await LLMDeduplicator(llm=llm).clean(state, {"max_candidate_pairs": 2})

    assert len(llm.calls) == 2


async def test_llm_dedup_invalid_json_treated_as_no_merge() -> None:
    class _BrokenLLM:
        provider = "broken"
        default_model = "x"

        async def complete(self, messages, params=None):  # type: ignore[no-untyped-def]
            return CompletionResult(text="not json at all", model="x")

    a, b = _node("Иванов И."), _node("Иванов")
    state = GraphBuildState(nodes=[a, b], edges=[])

    out = await LLMDeduplicator(llm=_BrokenLLM()).clean(state, {})

    assert {n.id for n in out.nodes} == {a.id, b.id}
    assert out.journal == []


async def test_llm_dedup_ignores_non_entity_layer() -> None:
    entity = _node("Иванов")
    community = Node(
        graph_variant_id=new_id(),
        layer=Layer.COMMUNITY,
        type="COMMUNITY",
        granularity=2,
        name="Иванов community",
    )
    state = GraphBuildState(nodes=[entity, community], edges=[])

    llm = _FakeLLM({"Иванов": True})
    await LLMDeduplicator(llm=llm).clean(state, {})

    # No second entity-layer node with the same first-token bucket → no
    # candidate pairs → no LLM calls. Community-layer nodes are skipped.
    assert llm.calls == []


def test_llm_dedup_descriptor_metadata() -> None:
    d = LLMDeduplicator.descriptor
    assert d.kind == "cleaner"
    assert d.name == "llm_dedup"
    assert d.cost_hint == "moderate"
    assert Layer.ENTITY in d.requires_layers


@pytest.mark.parametrize(
    "params",
    [{"weight_threshold": 0.0}, {"weight_threshold": 1.5}, {}],
)
async def test_threshold_idempotent_when_nothing_to_drop(params: dict) -> None:
    a, b = _node("A"), _node("B")
    edges = [_edge(a.id, b.id, weight=2.0)]
    state = GraphBuildState(nodes=[a, b], edges=edges)

    out = await ThresholdPruner().clean(state, params)

    # weight=2.0 ≥ any threshold here, edges survive.
    if params.get("weight_threshold", 0.0) <= 2.0:
        assert len(out.edges) == 1
