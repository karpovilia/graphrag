from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import faiss
import numpy as np

from .base import (
    Filter,
    Metric,
    SearchHit,
    VecItem,
    VectorStoreError,
    VectorStoreProtocol,
    matches,
)


@dataclass
class _Collection:
    name: str
    dim: int
    metric: Metric
    index: faiss.Index
    """faiss.IndexIDMap2 wrapping a flat or HNSW base. Internal int64 ids
    are positional; we keep id↔string-id and id↔payload maps in Python.
    """

    str_by_int: dict[int, str]
    int_by_str: dict[str, int]
    payload_by_str: dict[str, dict[str, Any]]
    next_int_id: int
    dirty: bool


class FaissAdapter(VectorStoreProtocol):
    """Per-graph FAISS adapter.

    Collection naming convention is `{graph_variant_id}__{embedding_model}`
    so that filtering by `graph_variant_id` is collapsed into "pick the
    right collection". Other filters are evaluated post-search in Python.

    Persistence: each collection writes two files alongside one another —
    `{name}.faiss` (the index, via faiss.write_index) and `{name}.json`
    (id maps + payloads + metadata). Saved lazily on a flush and on
    drop_collection.

    Concurrency: assumes a single process. If two workers ever share the
    same data dir, switch to Qdrant (see R-02 Variant B); FAISS file I/O
    isn't safe under multi-writer.
    """

    backend = "faiss"

    def __init__(
        self,
        data_dir: Path,
        cache_size: int = 16,
        flush_on_upsert: bool = True,
    ) -> None:
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._cache: OrderedDict[str, _Collection] = OrderedDict()
        self._cache_size = cache_size
        self._flush_on_upsert = flush_on_upsert
        self._lock = asyncio.Lock()

    # ---- public protocol ----

    async def create_collection(
        self,
        name: str,
        dim: int,
        metric: Metric = "cosine",
    ) -> None:
        async with self._lock:
            if self._faiss_path(name).exists() or name in self._cache:
                raise VectorStoreError(f"collection {name!r} already exists")
            coll = self._new_collection(name, dim, metric)
            self._cache[name] = coll
            self._touch(name)
            await asyncio.to_thread(self._flush, coll)

    async def upsert(self, collection: str, items: list[VecItem]) -> None:
        if not items:
            return
        async with self._lock:
            coll = await self._load(collection)
            self._validate_dims(coll, items)

            # Tombstone any pre-existing ids first; FAISS HNSW can't
            # update vectors in place, so a logical update is delete+add.
            existing = [it.id for it in items if it.id in coll.int_by_str]
            if existing:
                self._remove_ids(coll, existing)

            new_int_ids = list(range(coll.next_int_id, coll.next_int_id + len(items)))
            coll.next_int_id += len(items)
            xb = np.asarray([it.vector for it in items], dtype=np.float32)
            if coll.metric == "cosine":
                _l2_normalize(xb)
            ids_arr = np.asarray(new_int_ids, dtype=np.int64)
            await asyncio.to_thread(coll.index.add_with_ids, xb, ids_arr)

            for item, int_id in zip(items, new_int_ids, strict=True):
                coll.str_by_int[int_id] = item.id
                coll.int_by_str[item.id] = int_id
                coll.payload_by_str[item.id] = item.payload

            coll.dirty = True
            if self._flush_on_upsert:
                await asyncio.to_thread(self._flush, coll)

    async def delete(self, collection: str, ids: list[str]) -> None:
        if not ids:
            return
        async with self._lock:
            coll = await self._load(collection)
            removed = self._remove_ids(coll, ids)
            if removed:
                coll.dirty = True
                if self._flush_on_upsert:
                    await asyncio.to_thread(self._flush, coll)

    async def search(
        self,
        collection: str,
        vector: list[float],
        k: int,
        filter: Filter | None = None,
    ) -> list[SearchHit]:
        async with self._lock:
            coll = await self._load(collection)
            if k <= 0 or coll.index.ntotal == 0:
                return []
            xq = np.asarray([vector], dtype=np.float32)
            if coll.metric == "cosine":
                _l2_normalize(xq)
            # Overshoot when filtering; 5x is enough for our sizes (R-02 §7).
            search_k = min(k * 5 if filter is not None else k, coll.index.ntotal)
            distances, int_ids = await asyncio.to_thread(
                coll.index.search, xq, search_k
            )

            out: list[SearchHit] = []
            for raw_id, raw_score in zip(int_ids[0], distances[0], strict=True):
                int_id = int(raw_id)
                if int_id < 0:
                    continue
                str_id = coll.str_by_int.get(int_id)
                if str_id is None:
                    continue
                payload = coll.payload_by_str.get(str_id, {})
                if filter is not None and not matches(filter, payload):
                    continue
                out.append(
                    SearchHit(
                        id=str_id,
                        score=_to_similarity(coll.metric, float(raw_score)),
                        payload=payload,
                    )
                )
                if len(out) >= k:
                    break
            return out

    async def drop_collection(self, name: str) -> None:
        async with self._lock:
            self._cache.pop(name, None)
            for path in (self._faiss_path(name), self._meta_path(name)):
                if path.exists():
                    path.unlink()

    # ---- helpers ----

    def _faiss_path(self, name: str) -> Path:
        return self._data_dir / f"{name}.faiss"

    def _meta_path(self, name: str) -> Path:
        return self._data_dir / f"{name}.json"

    def _new_collection(self, name: str, dim: int, metric: Metric) -> _Collection:
        # Brute-force flat index: supports remove_ids natively under IDMap2,
        # < 5 ms on 50k×1024 per R-02. HNSW would shave milliseconds but
        # has no in-place delete — wrong tradeoff for a curation-driven
        # workload where every merge/split rewrites embeddings.
        if metric in ("cosine", "ip"):
            base = faiss.IndexFlatIP(dim)
        else:
            base = faiss.IndexFlatL2(dim)
        index = faiss.IndexIDMap2(base)
        return _Collection(
            name=name,
            dim=dim,
            metric=metric,
            index=index,
            str_by_int={},
            int_by_str={},
            payload_by_str={},
            next_int_id=0,
            dirty=True,
        )

    async def _load(self, name: str) -> _Collection:
        if name in self._cache:
            self._touch(name)
            return self._cache[name]
        if not self._faiss_path(name).exists():
            raise VectorStoreError(f"collection {name!r} not found")
        coll = await asyncio.to_thread(self._load_from_disk, name)
        self._cache[name] = coll
        self._touch(name)
        self._evict_if_needed()
        return coll

    def _load_from_disk(self, name: str) -> _Collection:
        index = faiss.read_index(str(self._faiss_path(name)))
        meta = json.loads(self._meta_path(name).read_text())
        str_by_int = {int(k): v for k, v in meta["str_by_int"].items()}
        return _Collection(
            name=name,
            dim=int(meta["dim"]),
            metric=meta["metric"],
            index=index,
            str_by_int=str_by_int,
            int_by_str={v: k for k, v in str_by_int.items()},
            payload_by_str=meta["payload_by_str"],
            next_int_id=int(meta["next_int_id"]),
            dirty=False,
        )

    def _flush(self, coll: _Collection) -> None:
        if not coll.dirty:
            return
        faiss.write_index(coll.index, str(self._faiss_path(coll.name)))
        meta = {
            "dim": coll.dim,
            "metric": coll.metric,
            "next_int_id": coll.next_int_id,
            "str_by_int": {str(k): v for k, v in coll.str_by_int.items()},
            "payload_by_str": coll.payload_by_str,
        }
        self._meta_path(coll.name).write_text(json.dumps(meta, ensure_ascii=False))
        coll.dirty = False

    def _validate_dims(self, coll: _Collection, items: list[VecItem]) -> None:
        for it in items:
            if len(it.vector) != coll.dim:
                raise VectorStoreError(
                    f"collection {coll.name!r} dim={coll.dim}, got vector dim={len(it.vector)} for id={it.id!r}"
                )

    def _remove_ids(self, coll: _Collection, ids: list[str]) -> int:
        int_ids = [coll.int_by_str[s] for s in ids if s in coll.int_by_str]
        if not int_ids:
            return 0
        sel = faiss.IDSelectorBatch(np.asarray(int_ids, dtype=np.int64))
        coll.index.remove_ids(sel)
        for s in ids:
            int_id = coll.int_by_str.pop(s, None)
            if int_id is not None:
                coll.str_by_int.pop(int_id, None)
            coll.payload_by_str.pop(s, None)
        return len(int_ids)

    def _touch(self, name: str) -> None:
        self._cache.move_to_end(name)

    def _evict_if_needed(self) -> None:
        while len(self._cache) > self._cache_size:
            _, evicted = self._cache.popitem(last=False)
            if evicted.dirty:
                self._flush(evicted)


def _l2_normalize(arr: np.ndarray) -> None:
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    np.divide(arr, np.maximum(norms, 1e-12), out=arr)


def _to_similarity(metric: Metric, raw: float) -> float:
    """FAISS returns inner product (higher=better) for IP/cosine and
    squared L2 (lower=better) for L2. Normalize so score is always
    higher=better in [-1, 1] for cosine and unbounded for the others.
    """

    if metric == "l2":
        return -raw
    return raw
