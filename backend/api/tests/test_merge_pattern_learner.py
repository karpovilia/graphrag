"""Tests for the GLM-backed merge-pattern learning agent.

A scripted fake CompletionClient stands in for GLM: it returns one JSON
blob per call in order (form-rule → build-shortlist → verify), so the
three-step skill is exercised end-to-end without the network.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from api.domain.curation import (
    JournalEntry,
    JournalOp,
    SuggestionAction,
)
from api.domain.graph import Layer, Node
from api.llm.base import CompletionParams, CompletionResult, Message
from api.strategies import GraphBuildState
from api.agents.merge_pattern_learner import MergePatternLearner, _extract_json

VID = uuid4()


class ScriptedLLM:
    """Returns the next canned response per complete() call; records prompts."""

    def __init__(self, responses: list[dict]) -> None:
        self._responses = [json.dumps(r, ensure_ascii=False) for r in responses]
        self.calls: list[list[Message]] = []

    async def complete(
        self, messages: list[Message], params: CompletionParams | None = None
    ) -> CompletionResult:
        self.calls.append(messages)
        text = self._responses.pop(0) if self._responses else "{}"
        return CompletionResult(text=text, model="fake-glm", finish_reason="stop")


def _ent(name: str, type_: str = "PERSON") -> Node:
    return Node(
        id=uuid4(), graph_variant_id=VID, layer=Layer.ENTITY,
        type=type_, granularity=1, name=name,
    )


def _merge_entry(survivor: str, absorbed: str, type_: str = "PERSON") -> JournalEntry:
    return JournalEntry(
        id=uuid4(), graph_variant_id=VID, op=JournalOp.MERGE_NODES,
        payload={
            "survivor_id": str(uuid4()),
            "absorbed_ids": [str(uuid4())],
            "survivor_name": survivor,
            "absorbed_names": [absorbed],
            "entity_type": type_,
        },
        actor="user:test",
    )


def _history_state(extra_nodes: list[Node]) -> GraphBuildState:
    journal = [
        _merge_entry("Иванов Иван", "Иванов И.И."),
        _merge_entry("Петров Пётр", "Петров П."),
        _merge_entry("ВШЭ", "НИУ ВШЭ", type_="ORG"),
    ]
    return GraphBuildState(nodes=extra_nodes, edges=[], journal=journal)


async def test_full_skill_proposes_grounded_merge():
    # Two entities still separate that the verify step blesses.
    survivor = _ent("Сидоров Семён")
    absorbed = _ent("Сидоров С.")
    state = _history_state([survivor, absorbed])

    llm = ScriptedLLM(
        [
            {"rule": "Объединяй полное ФИО с его инициальной формой.",
             "signals": ["та же фамилия", "инициалы"]},
            {"pairs": [{"survivor": "Сидоров Семён", "absorbed": "Сидоров С.",
                        "why": "инициалы"}]},
            {"pairs": [{"survivor": "Сидоров Семён", "absorbed": "Сидоров С.",
                        "confidence": 0.9}]},
        ]
    )
    agent = MergePatternLearner(llm=llm)
    out = await agent.propose(VID, state, {})

    assert len(out) == 1
    s = out[0]
    assert s.action == SuggestionAction.MERGE
    assert s.payload["survivor_id"] == str(survivor.id)
    assert s.payload["absorbed_ids"] == [str(absorbed.id)]
    assert s.payload["survivor_name"] == "Сидоров Семён"
    assert s.payload["absorbed_names"] == ["Сидоров С."]
    assert s.confidence == pytest.approx(0.9)
    assert set(s.target_node_ids) == {survivor.id, absorbed.id}
    assert len(llm.calls) == 3  # form-rule, shortlist, verify


async def test_too_few_merges_is_noop():
    state = GraphBuildState(
        nodes=[_ent("A"), _ent("B")], edges=[],
        journal=[_merge_entry("A full", "A")],  # only 1 < min_merges=3
    )
    llm = ScriptedLLM([])
    out = await MergePatternLearner(llm=llm).propose(VID, state, {})
    assert out == []
    assert llm.calls == []  # bailed before any LLM call


async def test_hallucinated_pair_is_dropped():
    # verify returns a name that doesn't exist among current entities.
    state = _history_state([_ent("Сидоров Семён"), _ent("Сидоров С.")])
    llm = ScriptedLLM(
        [
            {"rule": "r", "signals": []},
            {"pairs": [{"survivor": "Призрак", "absorbed": "Несуществующий"}]},
            {"pairs": [{"survivor": "Призрак", "absorbed": "Несуществующий",
                        "confidence": 0.99}]},
        ]
    )
    out = await MergePatternLearner(llm=llm).propose(VID, state, {})
    assert out == []


async def test_low_confidence_filtered():
    state = _history_state([_ent("Сидоров Семён"), _ent("Сидоров С.")])
    llm = ScriptedLLM(
        [
            {"rule": "r", "signals": []},
            {"pairs": [{"survivor": "Сидоров Семён", "absorbed": "Сидоров С."}]},
            {"pairs": [{"survivor": "Сидоров Семён", "absorbed": "Сидоров С.",
                        "confidence": 0.2}]},
        ]
    )
    out = await MergePatternLearner(llm=llm).propose(VID, state, {"min_confidence": 0.5})
    assert out == []


async def test_self_pair_dropped():
    # survivor and absorbed resolve to the SAME node — not a real merge.
    state = _history_state([_ent("Сидоров Семён")])
    llm = ScriptedLLM(
        [
            {"rule": "r", "signals": []},
            {"pairs": [{"survivor": "Сидоров Семён", "absorbed": "сидоров семён"}]},
            {"pairs": [{"survivor": "Сидоров Семён", "absorbed": "сидоров семён",
                        "confidence": 0.9}]},
        ]
    )
    out = await MergePatternLearner(llm=llm).propose(VID, state, {})
    assert out == []


def test_extract_json_strips_fences():
    assert _extract_json('```json\n{"rule": "x"}\n```') == {"rule": "x"}
    assert _extract_json('prose before {"a": 1} trailing') == {"a": 1}
    assert _extract_json("not json at all") is None
    assert _extract_json("") is None
