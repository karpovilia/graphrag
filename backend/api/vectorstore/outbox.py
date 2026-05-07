"""Outbox consumer.

Producer side lives in the repository layer: every successful
`append_journal` writes one VectorOutboxEntry per (variant, model) the
op affected. The consumer runs in-process (R2 single-instance deploy),
polls the repository for pending entries, debounces several entries
on the same (variant, model) into one rebuild call, and asks a
RebuildHandler to refresh the matching FAISS collection.

The handler interface is intentionally minimal — Phase 1.4.x lands the
real FAISS rebuilder once an embedder pipeline produces vectors. Until
then a no-op handler keeps the pump exercise-able and the queue from
backing up.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable

from loguru import logger

from api.domain.types import Id
from api.repository.protocol import RepositoryProtocol, VectorOutboxEntry

RebuildHandler = Callable[[Id, str], Awaitable[None]]
"""Coroutine called once per (graph_variant_id, embedding_model) combo
that's pending. Implementations rebuild the corresponding FAISS index.
Errors propagate; the pump leaves the entries unacked so the next pass
retries — handler is responsible for its own backoff/circuit-breaker.
"""


async def _noop_handler(graph_variant_id: Id, embedding_model: str) -> None:
    logger.debug(
        "vector outbox: no-op rebuild for variant={} model={}",
        graph_variant_id,
        embedding_model,
    )


class VectorOutboxPump:
    """In-process pump.

    Phase 2.1c scope: drain → group → handle → ack. No persistent
    bookkeeping beyond what the repository's outbox table offers; if
    the process restarts mid-rebuild, the un-acked entries get retried
    on next start.
    """

    def __init__(
        self,
        repo: RepositoryProtocol,
        handler: RebuildHandler | None = None,
        *,
        interval_seconds: float = 1.0,
        batch_limit: int = 256,
    ) -> None:
        self._repo = repo
        self._handler: RebuildHandler = handler or _noop_handler
        self._interval = interval_seconds
        self._batch_limit = batch_limit

    async def run_once(self) -> int:
        """Drain the current outbox, run the handler per group, ack on
        success. Returns the number of entries acked.
        """

        pending = await self._repo.list_pending_outbox(limit=self._batch_limit)
        if not pending:
            return 0

        groups = _group_by_variant_model(pending)
        acked_ids: list[int] = []
        for (variant_id, model), entries in groups.items():
            try:
                await self._handler(variant_id, model)
            except Exception as e:
                logger.exception(
                    "vector outbox: handler failed for variant={} model={} err={}",
                    variant_id,
                    model,
                    e,
                )
                continue
            acked_ids.extend(e.id for e in entries if e.id is not None)

        if acked_ids:
            await self._repo.ack_outbox(acked_ids)
        return len(acked_ids)

    async def run_forever(self, *, stop: asyncio.Event | None = None) -> None:
        """Long-running loop. Sleeps `interval_seconds` between drains.

        Cancelled via `stop.set()` (from FastAPI shutdown handler) or by
        cancelling the task directly.
        """

        stop = stop or asyncio.Event()
        while not stop.is_set():
            try:
                await self.run_once()
            except Exception as e:
                logger.exception("vector outbox: pump loop error: {}", e)
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                continue


def _group_by_variant_model(
    entries: list[VectorOutboxEntry],
) -> dict[tuple[Id, str], list[VectorOutboxEntry]]:
    out: dict[tuple[Id, str], list[VectorOutboxEntry]] = defaultdict(list)
    for entry in entries:
        out[(entry.graph_variant_id, entry.embedding_model)].append(entry)
    return out
