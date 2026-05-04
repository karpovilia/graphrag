from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from api.vectorstore import And, Eq, In, Not, Or, VecItem, VectorStoreError
from api.vectorstore.base import matches
from api.vectorstore.faiss_adapter import FaissAdapter

COLL = "graph-test__e5-large"


async def _seed(store: FaissAdapter, n: int = 20, dim: int = 8) -> list[VecItem]:
    await store.create_collection(COLL, dim=dim, metric="cosine")
    items = [
        VecItem(
            id=f"n{i}",
            vector=[float(i + j) / 10 for j in range(dim)],
            payload={
                "layer": "entity" if i % 2 == 0 else "community",
                "type": "PERSON" if i < 10 else "ORG",
            },
        )
        for i in range(n)
    ]
    await store.upsert(COLL, items)
    return items


async def test_search_returns_top_k_in_order(faiss_store: FaissAdapter) -> None:
    items = await _seed(faiss_store)
    hits = await faiss_store.search(COLL, vector=items[0].vector, k=3)
    assert [h.id for h in hits] == ["n0", "n1", "n2"]
    assert hits[0].score == pytest.approx(1.0, abs=1e-6)


async def test_filter_eq_narrows_results(faiss_store: FaissAdapter) -> None:
    items = await _seed(faiss_store)
    hits = await faiss_store.search(
        COLL, vector=items[0].vector, k=3, filter=Eq("layer", "entity")
    )
    assert all(h.id.startswith("n") and int(h.id[1:]) % 2 == 0 for h in hits)


async def test_delete_and_persist_round_trip(
    faiss_store: FaissAdapter, tmp_path: Path
) -> None:
    items = await _seed(faiss_store)
    await faiss_store.delete(COLL, ["n0", "n2"])
    hits = await faiss_store.search(COLL, vector=items[0].vector, k=2)
    assert "n0" not in {h.id for h in hits}
    assert "n2" not in {h.id for h in hits}

    fresh = FaissAdapter(data_dir=faiss_store._data_dir)
    hits2 = await fresh.search(COLL, vector=items[0].vector, k=2)
    assert {h.id for h in hits2} == {h.id for h in hits}


async def test_upsert_replaces_existing_id(faiss_store: FaissAdapter) -> None:
    items = await _seed(faiss_store)
    await faiss_store.upsert(
        COLL,
        [VecItem(id="n0", vector=items[0].vector, payload={"layer": "entity", "v": 99})],
    )
    hits = await faiss_store.search(COLL, vector=items[0].vector, k=1)
    assert hits[0].id == "n0"
    assert hits[0].payload["v"] == 99


async def test_complex_filter(faiss_store: FaissAdapter) -> None:
    items = await _seed(faiss_store)
    hits = await faiss_store.search(
        COLL,
        vector=items[0].vector,
        k=20,
        filter=And(clauses=(Eq("type", "PERSON"), In("layer", ("entity", "community")))),
    )
    assert hits and all(h.payload["type"] == "PERSON" for h in hits)


async def test_dim_mismatch_raises(faiss_store: FaissAdapter) -> None:
    await faiss_store.create_collection("bad", dim=4)
    with pytest.raises(VectorStoreError):
        await faiss_store.upsert(
            "bad", [VecItem(id="x", vector=[0.1, 0.2, 0.3], payload={})]
        )


async def test_drop_collection_removes_files(faiss_store: FaissAdapter) -> None:
    await _seed(faiss_store)
    await faiss_store.drop_collection(COLL)
    fresh = FaissAdapter(data_dir=faiss_store._data_dir)
    with pytest.raises(VectorStoreError):
        await fresh.search(COLL, vector=[0.0] * 8, k=1)


async def test_double_create_raises(faiss_store: FaissAdapter) -> None:
    await faiss_store.create_collection(COLL, dim=8)
    with pytest.raises(VectorStoreError):
        await faiss_store.create_collection(COLL, dim=8)


async def test_search_on_empty_collection(faiss_store: FaissAdapter) -> None:
    await faiss_store.create_collection("empty", dim=4)
    hits = await faiss_store.search("empty", vector=[0.0] * 4, k=5)
    assert hits == []


def test_filter_adt_unit() -> None:
    p = {"layer": "entity", "type": "PERSON"}
    assert matches(Eq("layer", "entity"), p) is True
    assert matches(Eq("layer", "topic"), p) is False
    assert matches(In("type", ("PERSON", "ORG")), p) is True
    assert matches(Not(Eq("layer", "entity")), p) is False
    assert matches(Or(clauses=(Eq("layer", "topic"), Eq("type", "PERSON"))), p) is True


@pytest.mark.slow
async def test_bench_meets_r02_dod(faiss_store: FaissAdapter) -> None:
    """R-02 DoD: 3k × 1024 dim — rebuild < 2 s, search k=20 < 5 ms p95."""

    rng = np.random.default_rng(42)
    n, dim = 3000, 1024
    coll = "bench__e5-large"
    await faiss_store.create_collection(coll, dim=dim, metric="cosine")
    vecs = rng.standard_normal((n, dim)).astype("float32").tolist()
    items = [
        VecItem(id=f"b{i}", vector=vecs[i], payload={"graph": "g", "layer": "entity"})
        for i in range(n)
    ]

    t0 = time.perf_counter()
    await faiss_store.upsert(coll, items)
    upsert_ms = (time.perf_counter() - t0) * 1000
    assert upsert_ms < 2000, f"upsert took {upsert_ms:.0f} ms"

    await faiss_store.search(coll, vector=vecs[0], k=20)  # warmup
    t0 = time.perf_counter()
    for _ in range(50):
        await faiss_store.search(coll, vector=vecs[0], k=20)
    avg_ms = (time.perf_counter() - t0) * 1000 / 50
    assert avg_ms < 5.0, f"search avg {avg_ms:.2f} ms exceeds 5 ms"
