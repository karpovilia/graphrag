from __future__ import annotations

import json

import pytest

from api.domain import (
    Corpus,
    Edge,
    EdgeType,
    GraphVariant,
    JournalEntry,
    JournalOp,
    Layer,
    Node,
    Run,
    RunKind,
    Suggestion,
    SuggestionAction,
    ToolInvocation,
)
from api.domain.types import new_id


def test_graph_variant_round_trip_through_json() -> None:
    variant = GraphVariant(
        corpus_id=new_id(),
        name="podcast/lightrag",
        builder="lightrag",
        cleaner_chain=["llm_dedup", "threshold_prune"],
        clusterer="leiden",
        config={"k": 5},
        seed=42,
        layers_present=[Layer.ENTITY, Layer.COMMUNITY],
    )
    blob = variant.model_dump_json()
    restored = GraphVariant.model_validate_json(blob)
    assert restored == variant


def test_node_and_edge_link_by_graph_variant() -> None:
    variant_id = new_id()
    node_a = Node(
        graph_variant_id=variant_id,
        layer=Layer.ENTITY,
        type="PERSON",
        granularity=1,
        name="Иванов",
    )
    node_b = Node(
        graph_variant_id=variant_id,
        layer=Layer.ENTITY,
        type="ORG",
        granularity=1,
        name="ВШЭ",
    )
    edge = Edge(
        graph_variant_id=variant_id,
        type=EdgeType.ENTITY_RELATION,
        source_node_id=node_a.id,
        target_node_id=node_b.id,
        relation="works_at",
    )
    assert edge.source_node_id == node_a.id
    assert edge.target_node_id == node_b.id


def test_suggestion_starts_pending() -> None:
    s = Suggestion(
        graph_variant_id=new_id(),
        agent="entity_dedup",
        action=SuggestionAction.MERGE,
        payload={"survivor_id": str(new_id())},
        confidence=0.91,
        rationale="exact name match modulo morphology",
    )
    assert s.status.value == "pending"
    assert s.decided_at is None


def test_journal_entry_records_actor() -> None:
    j = JournalEntry(
        graph_variant_id=new_id(),
        op=JournalOp.MOVE_TO_COMMUNITY,
        payload={"node_id": str(new_id())},
        actor="user:karpov@hse.ru",
    )
    assert j.actor.startswith("user:")


def test_run_progress_bounded() -> None:
    r = Run(kind=RunKind.BUILD, strategy="builder:lightrag")
    r.progress = 0.5
    with pytest.raises(Exception):
        r.progress = 1.5


def test_corpus_minimal() -> None:
    c = Corpus(name="HSE podcast")
    assert c.language == "ru"
    assert c.document_count == 0


def test_tool_invocation_payload_serializable() -> None:
    ti = ToolInvocation(
        node_id=new_id(),
        tool="wikidata_lookup",
        arguments={"qid": "Q123"},
        result={"label": "test"},
    )
    json.loads(ti.model_dump_json())


def test_extra_field_rejected() -> None:
    with pytest.raises(Exception):
        Corpus(name="x", bogus_field=1)  # type: ignore[call-arg]
