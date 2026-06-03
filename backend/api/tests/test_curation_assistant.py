"""Tests for the conversational curation assistant planner.

A scripted fake LLM returns one JSON plan; we assert the planner grounds ops
to real ids (resolving echoed names), validates payloads, and drops bad ops.
"""

from __future__ import annotations

import json
from uuid import uuid4

from api.assistant.curation_assistant import (
    CurationAssistant,
    build_graph_context,
)
from api.domain.curation import JournalOp
from api.domain.graph import Edge, EdgeType, Layer, Node
from api.llm.base import CompletionParams, CompletionResult, Message
from api.strategies import GraphBuildState

VID = uuid4()


class OneShotLLM:
    def __init__(self, payload: dict) -> None:
        self._text = json.dumps(payload, ensure_ascii=False)
        self.calls: list[list[Message]] = []

    async def complete(
        self, messages: list[Message], params: CompletionParams | None = None
    ) -> CompletionResult:
        self.calls.append(messages)
        return CompletionResult(text=self._text, model="fake", finish_reason="stop")


def _ent(name: str, type_: str = "PERSON") -> Node:
    return Node(
        id=uuid4(), graph_variant_id=VID, layer=Layer.ENTITY,
        type=type_, granularity=1, name=name,
    )


def _state(nodes, edges=None) -> GraphBuildState:
    return GraphBuildState(nodes=nodes, edges=edges or [], journal=[])


async def test_delete_node_by_id():
    junk = _ent("Да")
    state = _state([junk, _ent("Воксисом", "PERSON")])
    llm = OneShotLLM(
        {"message": "Удаляю мусорный узел «Да».",
         "ops": [{"op": "delete_node", "node_id": str(junk.id), "reason": "мусор"}]}
    )
    plan = await CurationAssistant(llm).plan(state, message="удали узел Да")
    assert len(plan.ops) == 1
    assert plan.ops[0].op == JournalOp.DELETE_NODE
    assert plan.ops[0].payload["node_id"] == str(junk.id)
    assert "Да" in plan.message


async def test_retype_node():
    voks = _ent("Воксисом", "PERSON")
    state = _state([voks, _ent("Иван", "PERSON")])
    llm = OneShotLLM(
        {"message": "Меняю тип на ORG.",
         "ops": [{"op": "retype_node", "node_id": str(voks.id), "new_type": "ORG"}]}
    )
    plan = await CurationAssistant(llm).plan(state, message="Воксисом это организация")
    assert len(plan.ops) == 1
    assert plan.ops[0].op == JournalOp.RETYPE_NODE
    assert plan.ops[0].payload["new_type"] == "ORG"


async def test_name_echoed_instead_of_id_is_resolved():
    junk = _ent("Да")
    state = _state([junk])
    # Model echoed the NAME where an id is expected — planner must resolve it.
    llm = OneShotLLM(
        {"message": "ок", "ops": [{"op": "delete_node", "node_id": "Да", "reason": "x"}]}
    )
    plan = await CurationAssistant(llm).plan(state, message="удали Да")
    assert len(plan.ops) == 1
    assert plan.ops[0].payload["node_id"] == str(junk.id)


async def test_unknown_op_and_bad_payload_dropped():
    n = _ent("X")
    state = _state([n])
    llm = OneShotLLM(
        {"message": "…", "ops": [
            {"op": "frobnicate", "node_id": str(n.id)},          # unknown op
            {"op": "retype_node", "node_id": str(n.id)},          # missing new_type
            {"op": "delete_node", "node_id": str(n.id), "reason": "ok"},  # valid
        ]}
    )
    plan = await CurationAssistant(llm).plan(state, message="x")
    assert [o.op for o in plan.ops] == [JournalOp.DELETE_NODE]


async def test_empty_plan_when_target_missing():
    state = _state([_ent("A")])
    llm = OneShotLLM({"message": "Не нашёл такой узел, уточни.", "ops": []})
    plan = await CurationAssistant(llm).plan(state, message="удали Несуществующий")
    assert plan.ops == []
    assert "уточни" in plan.message.lower()


async def test_merge_resolves_names_in_list():
    a = _ent("Иванов Иван")
    b = _ent("Иванов И.")
    state = _state([a, b])
    llm = OneShotLLM(
        {"message": "Сливаю.", "ops": [{
            "op": "merge_nodes", "survivor_id": "Иванов Иван",
            "absorbed_ids": ["Иванов И."], "reason": "дубль",
            "survivor_name": "Иванов Иван", "absorbed_names": ["Иванов И."],
            "entity_type": "PERSON",
        }]}
    )
    plan = await CurationAssistant(llm).plan(state, message="слей Иванова")
    assert len(plan.ops) == 1
    p = plan.ops[0].payload
    assert p["survivor_id"] == str(a.id)
    assert p["absorbed_ids"] == [str(b.id)]


async def test_highlight_query_matches_all_in_slice():
    # "найди всех Миш" → highlight every name containing "Миш", no disambiguation.
    m1, m2 = _ent("Миша"), _ent("Миша Иванов")
    other = _ent("Пётр")
    state = _state([m1, m2, other])
    llm = OneShotLLM(
        {"message": "Подсветил всех Миш.",
         "ops": [{"op": "highlight_nodes", "query": "Миш"}]}
    )
    plan = await CurationAssistant(llm).plan(state, message="найди всех Миш")
    assert plan.ops == []  # view action, not a mutation
    assert set(plan.highlight) == {str(m1.id), str(m2.id)}


async def test_highlight_scoped_to_slice():
    inn, out = _ent("Миша"), _ent("Миша")
    state = _state([inn, out])
    llm = OneShotLLM(
        {"message": "ок", "ops": [{"op": "highlight_nodes", "query": "Миш"}]}
    )
    # Only `inn` is in the current slice → only it lights up.
    plan = await CurationAssistant(llm).plan(
        state, message="найди Миш", slice_node_ids=[str(inn.id)]
    )
    assert plan.highlight == [str(inn.id)]


async def test_highlight_type_filter():
    org, person = _ent("Сбер", "ORG"), _ent("Сбер", "PERSON")
    state = _state([org, person])
    llm = OneShotLLM(
        {"message": "ок", "ops": [{"op": "highlight_nodes", "query": "Сбер", "type": "ORG"}]}
    )
    plan = await CurationAssistant(llm).plan(state, message="покажи организации Сбер")
    assert plan.highlight == [str(org.id)]


def test_context_lists_selection_types_and_edges():
    a = _ent("Воксисом", "PERSON")
    b = _ent("Иван", "PERSON")
    edge = Edge(id=uuid4(), graph_variant_id=VID, type=EdgeType.ENTITY_RELATION,
                source_node_id=a.id, target_node_id=b.id)
    state = _state([a, b], [edge])
    ctx = build_graph_context(state, selected_node_ids=[str(a.id)])
    assert "Воксисом" in ctx
    assert "Существующие типы" in ctx
    assert str(edge.id) in ctx  # incident edge id is offered for delete_edge
