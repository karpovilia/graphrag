"""Mixture-of-Experts reasoning over multiple GraphVariants.

Phase 4.2. The orchestrator fans out a query across N variants in
parallel, runs the chosen Reasoner against each, and feeds the
ExpertResults to an Aggregator plugin. Per-expert errors don't crash
the run — they propagate as ExpertResult.error so the aggregator can
decide.

Not registered in any plugin registry: MoEReasoner is the registry
*caller*, not a registry entry. The Reasoner and Aggregator names
that drive a run are user-supplied (or wizard-defaulted).
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from loguru import logger

from api.domain.types import DomainModel, Id
from api.llm import CompletionClient
from api.strategies.protocols import (
    AggregatorProtocol,
    ExpertResult,
    GraphLoader,
    ReasonerProtocol,
    ReasonResult,
)
from api.strategies.registry import aggregators, reasoners


class MoEError(RuntimeError):
    """MoE run could not start (e.g. unknown reasoner / aggregator).

    Per-expert failures are non-fatal and surface in expert_results.
    """


class MoEResult(DomainModel):
    """The final aggregated answer plus the per-expert breakdown the
    UI needs for split-view rendering.
    """

    answer: ReasonResult
    experts: list[ExpertResult]
    aggregator: str


_AggregatorFactory = Callable[[str], AggregatorProtocol]


def _default_aggregator_factory(llm: CompletionClient | None) -> _AggregatorFactory:
    """Most aggregators are stateless; LLMJudge needs an LLM. We hide
    the difference behind one factory the orchestrator can call."""

    def factory(name: str) -> AggregatorProtocol:
        cls = aggregators.get(name)
        if name == "llm_judge":
            if llm is None:
                raise MoEError(
                    "llm_judge aggregator needs an LLM client; "
                    "no completion provider registered"
                )
            return cls(llm=llm)  # type: ignore[call-arg]
        return cls()  # type: ignore[call-arg]

    return factory


async def run_moe(
    *,
    query: str,
    variant_ids: list[Id],
    reasoner_name: str,
    aggregator_name: str,
    loader: GraphLoader,
    reasoner_params: dict[str, Any] | None = None,
    aggregator_params: dict[str, Any] | None = None,
    llm: CompletionClient | None = None,
    aggregator_factory: _AggregatorFactory | None = None,
) -> MoEResult:
    """Fan-out → aggregate. Returns once every expert has finished or
    errored out.

    Errors per expert are caught and turned into ExpertResult.error;
    only orchestration-level problems (unknown plugin name, missing
    LLM for llm_judge) raise MoEError.
    """

    if not variant_ids:
        raise MoEError("MoE needs at least one variant_id")
    if not reasoners.has(reasoner_name):
        raise MoEError(
            f"unknown reasoner {reasoner_name!r}. Available: {reasoners.names()}"
        )
    if not aggregators.has(aggregator_name):
        raise MoEError(
            f"unknown aggregator {aggregator_name!r}. "
            f"Available: {aggregators.names()}"
        )

    factory = aggregator_factory or _default_aggregator_factory(llm)
    aggregator = factory(aggregator_name)
    reasoner_cls = reasoners.get(reasoner_name)
    reasoner: ReasonerProtocol = reasoner_cls()  # all R2 reasoners stateless

    coros = [
        _run_one_expert(
            query=query,
            variant_id=vid,
            reasoner_name=reasoner_name,
            reasoner=reasoner,
            params=reasoner_params or {},
            loader=loader,
        )
        for vid in variant_ids
    ]
    expert_results = await asyncio.gather(*coros)

    answer = await aggregator.aggregate(query, expert_results, aggregator_params or {})
    return MoEResult(
        answer=answer,
        experts=expert_results,
        aggregator=aggregator_name,
    )


async def stream_moe(
    *,
    query: str,
    variant_ids: list[Id],
    reasoner_name: str,
    aggregator_name: str,
    loader: GraphLoader,
    reasoner_params: dict[str, Any] | None = None,
    aggregator_params: dict[str, Any] | None = None,
    llm: CompletionClient | None = None,
    aggregator_factory: _AggregatorFactory | None = None,
) -> "asyncio.Queue[tuple[str, Any]]":
    """SSE-friendly streaming variant.

    Returns an asyncio.Queue that yields (event_type, payload) tuples:
      ('expert', ExpertResult) — once per finished expert, in
        completion order (not variant_ids order)
      ('answer', MoEResult)    — final aggregated answer
      ('done', None)           — sentinel signalling end of stream

    The route handler iterates the queue and emits SSE frames; the
    queue is unbounded but the producer will not exceed
    len(variant_ids) + 2 puts.
    """

    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
    asyncio.create_task(
        _stream_runner(
            queue=queue,
            query=query,
            variant_ids=variant_ids,
            reasoner_name=reasoner_name,
            aggregator_name=aggregator_name,
            loader=loader,
            reasoner_params=reasoner_params,
            aggregator_params=aggregator_params,
            llm=llm,
            aggregator_factory=aggregator_factory,
        )
    )
    return queue


# ---- internals ----


async def _run_one_expert(
    *,
    query: str,
    variant_id: Id,
    reasoner_name: str,
    reasoner: ReasonerProtocol,
    params: dict[str, Any],
    loader: GraphLoader,
) -> ExpertResult:
    try:
        result = await reasoner.reason(
            query=query,
            graph_variant_ids=[variant_id],
            params=params,
            loader=loader,
        )
        return ExpertResult(
            variant_id=variant_id,
            reasoner=reasoner_name,
            result=result,
        )
    except NotImplementedError as e:
        logger.warning(
            "moe expert {} not implemented: {}", reasoner_name, e
        )
        return ExpertResult(
            variant_id=variant_id,
            reasoner=reasoner_name,
            result=ReasonResult(text="", confidence=0.0),
            error=f"NotImplementedError: {e}",
        )
    except Exception as e:
        logger.exception("moe expert {} failed: {}", reasoner_name, e)
        return ExpertResult(
            variant_id=variant_id,
            reasoner=reasoner_name,
            result=ReasonResult(text="", confidence=0.0),
            error=f"{type(e).__name__}: {e}",
        )


async def _stream_runner(
    *,
    queue: "asyncio.Queue[tuple[str, Any]]",
    query: str,
    variant_ids: list[Id],
    reasoner_name: str,
    aggregator_name: str,
    loader: GraphLoader,
    reasoner_params: dict[str, Any] | None,
    aggregator_params: dict[str, Any] | None,
    llm: CompletionClient | None,
    aggregator_factory: _AggregatorFactory | None,
) -> None:
    try:
        factory = aggregator_factory or _default_aggregator_factory(llm)
        aggregator = factory(aggregator_name)
        reasoner_cls = reasoners.get(reasoner_name)
        reasoner: ReasonerProtocol = reasoner_cls()
    except Exception as e:
        await queue.put(("error", str(e)))
        await queue.put(("done", None))
        return

    completed: list[ExpertResult] = []
    pending = {
        asyncio.create_task(
            _run_one_expert(
                query=query,
                variant_id=vid,
                reasoner_name=reasoner_name,
                reasoner=reasoner,
                params=reasoner_params or {},
                loader=loader,
            )
        )
        for vid in variant_ids
    }
    try:
        while pending:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                expert = task.result()
                completed.append(expert)
                await queue.put(("expert", expert))

        answer = await aggregator.aggregate(
            query, completed, aggregator_params or {}
        )
        await queue.put(
            (
                "answer",
                MoEResult(
                    answer=answer,
                    experts=completed,
                    aggregator=aggregator_name,
                ),
            )
        )
    except Exception as e:
        await queue.put(("error", str(e)))
    finally:
        await queue.put(("done", None))
