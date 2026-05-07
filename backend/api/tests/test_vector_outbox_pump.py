from __future__ import annotations

import asyncio

import pytest

from api.domain.corpus import Corpus
from api.domain.curation import JournalEntry, JournalOp
from api.domain.graph import GraphVariant, Layer, Node
from api.domain.types import EmbeddingRef, Id
from api.repository import InMemoryRepository
from api.strategies.state import GraphBuildState
from api.vectorstore.outbox import VectorOutboxPump


async def _seed_variant_with_outbox_entry(
    repo: InMemoryRepository,
) -> tuple[Id, list[Node]]:
    corpus = await repo.create_corpus(Corpus(name="c"))
    variant = GraphVariant(corpus_id=corpus.id, name="v", builder="ner_extraction")
    node_a = Node(
        graph_variant_id=variant.id,
        layer=Layer.ENTITY,
        type="PERSON",
        granularity=1,
        name="A",
        embedding=EmbeddingRef(
            model="e5-large", dim=1024, collection="x", vector_id="a"
        ),
    )
    node_b = Node(
        graph_variant_id=variant.id,
        layer=Layer.ENTITY,
        type="PERSON",
        granularity=1,
        name="B",
        embedding=EmbeddingRef(
            model="bge-m3", dim=1024, collection="x", vector_id="b"
        ),
    )
    state = GraphBuildState(nodes=[node_a, node_b], edges=[])
    stored = await repo.create_variant(variant, state)
    entry = JournalEntry(
        graph_variant_id=stored.id,
        op=JournalOp.UPDATE_NODE_NAME,
        payload={"node_id": str(node_a.id), "name": "A1"},
        actor="user:t",
    )
    await repo.append_journal(stored.id, entry, expected_version=0)
    return stored.id, [node_a, node_b]


async def test_run_once_calls_handler_per_group_and_acks() -> None:
    repo = InMemoryRepository()
    variant_id, _ = await _seed_variant_with_outbox_entry(repo)
    calls: list[tuple[Id, str]] = []

    async def handler(vid: Id, model: str) -> None:
        calls.append((vid, model))

    pump = VectorOutboxPump(repo, handler=handler)
    acked = await pump.run_once()

    assert acked == 1  # only model "e5-large" was affected (node_a only)
    assert calls == [(variant_id, "e5-large")]
    assert await repo.list_pending_outbox(graph_variant_id=variant_id) == []


async def test_run_once_dedups_same_group_into_one_handler_call() -> None:
    repo = InMemoryRepository()
    variant_id, _ = await _seed_variant_with_outbox_entry(repo)

    # Trigger a second op affecting the same node → another outbox row
    # for (variant, e5-large). The pump should still call the handler
    # once for that group and ack both rows.
    state = await repo.load_state(variant_id)
    target = next(n for n in state.nodes if n.embedding and n.embedding.model == "e5-large")
    second = JournalEntry(
        graph_variant_id=variant_id,
        op=JournalOp.UPDATE_NODE_NAME,
        payload={"node_id": str(target.id), "name": "A2"},
        actor="user:t",
    )
    variant_after = await repo.get_variant(variant_id)
    await repo.append_journal(
        variant_id, second, expected_version=variant_after.version
    )

    assert len(await repo.list_pending_outbox(graph_variant_id=variant_id)) == 2

    calls: list[tuple[Id, str]] = []

    async def handler(vid: Id, model: str) -> None:
        calls.append((vid, model))

    pump = VectorOutboxPump(repo, handler=handler)
    acked = await pump.run_once()

    assert acked == 2
    assert calls == [(variant_id, "e5-large")]
    assert await repo.list_pending_outbox(graph_variant_id=variant_id) == []


async def test_handler_failure_leaves_entries_unacked_for_retry() -> None:
    repo = InMemoryRepository()
    variant_id, _ = await _seed_variant_with_outbox_entry(repo)

    async def failing_handler(vid: Id, model: str) -> None:
        raise RuntimeError("simulated FAISS rebuild error")

    pump = VectorOutboxPump(repo, handler=failing_handler)
    acked = await pump.run_once()

    assert acked == 0
    assert len(await repo.list_pending_outbox(graph_variant_id=variant_id)) == 1


async def test_run_once_returns_zero_on_empty_outbox() -> None:
    repo = InMemoryRepository()
    pump = VectorOutboxPump(repo)
    assert await pump.run_once() == 0


async def test_run_forever_can_be_stopped() -> None:
    repo = InMemoryRepository()
    pump = VectorOutboxPump(repo, interval_seconds=0.01)
    stop = asyncio.Event()

    async def stop_after_short_pause() -> None:
        await asyncio.sleep(0.05)
        stop.set()

    await asyncio.gather(pump.run_forever(stop=stop), stop_after_short_pause())


@pytest.mark.parametrize("count", [3, 7])
async def test_pump_handles_multiple_variants(count: int) -> None:
    repo = InMemoryRepository()
    variant_ids: list[Id] = []
    for _ in range(count):
        vid, _ = await _seed_variant_with_outbox_entry(repo)
        variant_ids.append(vid)

    seen: set[tuple[Id, str]] = set()

    async def handler(vid: Id, model: str) -> None:
        seen.add((vid, model))

    pump = VectorOutboxPump(repo, handler=handler)
    await pump.run_once()
    assert len(seen) == count
