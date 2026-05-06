from __future__ import annotations

import pytest

from api.domain.corpus import Corpus, Document
from api.domain.curation import JournalEntry, JournalOp
from api.domain.graph import (
    Edge,
    EdgeType,
    GraphVariant,
    GraphVariantStatus,
    Layer,
    Node,
)
from api.domain.types import EmbeddingRef, new_id
from api.repository import (
    ConcurrentEditError,
    InMemoryRepository,
    NotFoundError,
    diff_states,
)
from api.strategies.state import GraphBuildState


def _corpus(name: str = "corpus") -> Corpus:
    return Corpus(name=name)


def _variant(corpus_id) -> GraphVariant:
    return GraphVariant(corpus_id=corpus_id, name="v", builder="ner_extraction")


def _node(name: str, gv, **kw) -> Node:
    return Node(
        graph_variant_id=gv,
        layer=kw.pop("layer", Layer.ENTITY),
        type=kw.pop("type_", "PERSON"),
        granularity=1,
        name=name,
        **kw,
    )


# ---- corpora / documents ----


async def test_create_and_list_corpora() -> None:
    repo = InMemoryRepository()
    c = await repo.create_corpus(_corpus("a"))
    listed = await repo.list_corpora()
    assert [x.id for x in listed] == [c.id]


async def test_get_unknown_corpus_raises() -> None:
    repo = InMemoryRepository()
    with pytest.raises(NotFoundError):
        await repo.get_corpus(new_id())


async def test_create_document_increments_corpus_count() -> None:
    repo = InMemoryRepository()
    c = await repo.create_corpus(_corpus())
    doc = Document(corpus_id=c.id, title="d", char_length=10, sha256="0" * 64)

    await repo.create_document(doc)
    refreshed = await repo.get_corpus(c.id)
    assert refreshed.document_count == 1


async def test_create_document_unknown_corpus_raises() -> None:
    repo = InMemoryRepository()
    bogus = Document(corpus_id=new_id(), title="d", char_length=1, sha256="0" * 64)
    with pytest.raises(NotFoundError):
        await repo.create_document(bogus)


# ---- variants ----


async def test_create_variant_pins_counts_and_layers() -> None:
    repo = InMemoryRepository()
    c = await repo.create_corpus(_corpus())
    v = _variant(c.id)
    a, b = _node("a", v.id), _node("b", v.id)
    state = GraphBuildState(
        nodes=[a, b],
        edges=[
            Edge(
                graph_variant_id=v.id,
                type=EdgeType.ENTITY_RELATION,
                source_node_id=a.id,
                target_node_id=b.id,
                weight=1.0,
            )
        ],
    )

    stored = await repo.create_variant(v, state)
    assert stored.node_count == 2
    assert stored.edge_count == 1
    assert Layer.ENTITY in stored.layers_present


async def test_load_state_round_trip() -> None:
    repo = InMemoryRepository()
    c = await repo.create_corpus(_corpus())
    v = _variant(c.id)
    a = _node("a", v.id)
    state = GraphBuildState(nodes=[a], edges=[])
    await repo.create_variant(v, state)

    out = await repo.load_state(v.id)
    assert {n.id for n in out.nodes} == {a.id}


# ---- journal append + optimistic lock ----


async def _seed_pair(repo: InMemoryRepository) -> tuple[GraphVariant, Node, Node]:
    c = await repo.create_corpus(_corpus())
    v = _variant(c.id)
    survivor = _node("Иванов А.", v.id, summary="lead")
    absorbed = _node("Иванов И.", v.id)
    state = GraphBuildState(nodes=[survivor, absorbed], edges=[])
    stored = await repo.create_variant(v, state)
    return stored, survivor, absorbed


async def test_append_merge_updates_state_version_and_journal() -> None:
    repo = InMemoryRepository()
    variant, survivor, absorbed = await _seed_pair(repo)

    entry = JournalEntry(
        graph_variant_id=variant.id,
        op=JournalOp.MERGE_NODES,
        payload={
            "survivor_id": str(survivor.id),
            "absorbed_ids": [str(absorbed.id)],
        },
        actor="user:test",
    )
    result = await repo.append_journal(variant.id, entry, expected_version=0)

    assert result.variant.version == 1
    assert result.variant.node_count == 1
    state = await repo.load_state(variant.id)
    assert {n.id for n in state.nodes} == {survivor.id}
    journal = await repo.list_journal(variant.id)
    assert len(journal) == 1
    assert journal[0].op == JournalOp.MERGE_NODES


async def test_concurrent_edit_raises_on_stale_version() -> None:
    repo = InMemoryRepository()
    variant, survivor, absorbed = await _seed_pair(repo)
    entry = JournalEntry(
        graph_variant_id=variant.id,
        op=JournalOp.UPDATE_NODE_NAME,
        payload={"node_id": str(survivor.id), "name": "X"},
        actor="user:a",
    )
    await repo.append_journal(variant.id, entry, expected_version=0)

    stale = JournalEntry(
        graph_variant_id=variant.id,
        op=JournalOp.UPDATE_NODE_NAME,
        payload={"node_id": str(survivor.id), "name": "Y"},
        actor="user:b",
    )
    with pytest.raises(ConcurrentEditError) as exc:
        await repo.append_journal(variant.id, stale, expected_version=0)
    assert exc.value.actual == 1


async def test_actor_override_replaces_entry_actor() -> None:
    repo = InMemoryRepository()
    variant, survivor, _ = await _seed_pair(repo)
    entry = JournalEntry(
        graph_variant_id=variant.id,
        op=JournalOp.UPDATE_NODE_NAME,
        payload={"node_id": str(survivor.id), "name": "X"},
        actor="user:original",
    )
    result = await repo.append_journal(
        variant.id, entry, expected_version=0, actor="user:auth"
    )
    assert result.entry.actor == "user:auth"


# ---- vector outbox ----


async def test_outbox_emits_one_entry_per_affected_model() -> None:
    repo = InMemoryRepository()
    c = await repo.create_corpus(_corpus())
    v = _variant(c.id)
    survivor = _node(
        "Иванов А.",
        v.id,
        embedding=EmbeddingRef(model="e5", dim=1024, collection="x", vector_id="s"),
    )
    absorbed = _node(
        "Иванов И.",
        v.id,
        embedding=EmbeddingRef(model="e5", dim=1024, collection="x", vector_id="a"),
    )
    state = GraphBuildState(nodes=[survivor, absorbed], edges=[])
    stored = await repo.create_variant(v, state)

    entry = JournalEntry(
        graph_variant_id=stored.id,
        op=JournalOp.MERGE_NODES,
        payload={
            "survivor_id": str(survivor.id),
            "absorbed_ids": [str(absorbed.id)],
        },
        actor="user:test",
    )
    await repo.append_journal(stored.id, entry, expected_version=0)

    pending = await repo.list_pending_outbox(graph_variant_id=stored.id)
    assert len(pending) == 1
    assert pending[0].embedding_model == "e5"
    assert pending[0].reason == "journal_append"


async def test_outbox_empty_when_no_node_has_embedding() -> None:
    repo = InMemoryRepository()
    variant, survivor, absorbed = await _seed_pair(repo)  # no embeddings

    entry = JournalEntry(
        graph_variant_id=variant.id,
        op=JournalOp.MERGE_NODES,
        payload={
            "survivor_id": str(survivor.id),
            "absorbed_ids": [str(absorbed.id)],
        },
        actor="user:test",
    )
    await repo.append_journal(variant.id, entry, expected_version=0)
    assert await repo.list_pending_outbox() == []


async def test_ack_outbox_removes_entries() -> None:
    repo = InMemoryRepository()
    c = await repo.create_corpus(_corpus())
    v = _variant(c.id)
    n = _node(
        "n",
        v.id,
        embedding=EmbeddingRef(model="e5", dim=1024, collection="x", vector_id="n"),
    )
    state = GraphBuildState(nodes=[n], edges=[])
    stored = await repo.create_variant(v, state)
    entry = JournalEntry(
        graph_variant_id=stored.id,
        op=JournalOp.UPDATE_NODE_NAME,
        payload={"node_id": str(n.id), "name": "n2"},
        actor="user:test",
    )
    await repo.append_journal(stored.id, entry, expected_version=0)
    [pending] = await repo.list_pending_outbox(graph_variant_id=stored.id)

    await repo.ack_outbox([pending.id])
    assert await repo.list_pending_outbox(graph_variant_id=stored.id) == []


# ---- diff helper ----


def test_diff_detects_added_removed_changed() -> None:
    gv = new_id()
    a, b, c = _node("a", gv), _node("b", gv), _node("c", gv)
    before = GraphBuildState(nodes=[a, b], edges=[])
    after = GraphBuildState(nodes=[a.model_copy(update={"name": "A2"}), c], edges=[])

    diff = diff_states(before, after)
    assert {n.id for n in diff.nodes_changed} == {a.id}
    assert {n.id for n in diff.nodes_added} == {c.id}
    assert set(diff.nodes_removed) == {b.id}


def test_diff_ignores_order() -> None:
    gv = new_id()
    a, b = _node("a", gv), _node("b", gv)
    before = GraphBuildState(nodes=[a, b], edges=[])
    after = GraphBuildState(nodes=[b, a], edges=[])

    diff = diff_states(before, after)
    assert diff.nodes_added == ()
    assert diff.nodes_removed == ()
    assert diff.nodes_changed == ()


@pytest.mark.parametrize("status", [GraphVariantStatus.PENDING])
async def test_status_persists(status: GraphVariantStatus) -> None:
    repo = InMemoryRepository()
    c = await repo.create_corpus(_corpus())
    v = GraphVariant(
        corpus_id=c.id,
        name="v",
        builder="ner_extraction",
        status=status,
    )
    stored = await repo.create_variant(v, GraphBuildState())
    assert stored.status == status
