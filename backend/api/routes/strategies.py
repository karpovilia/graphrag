"""Strategy catalog endpoints.

Powers the wizard's Builder / Cleaner / Clusterer / Reasoner selection
cards. Pure read-only — walks the registry on each call (cheap, no I/O).
"""

from __future__ import annotations

# Importing the strategies subpackages triggers their @register
# decorators so the registry is populated before any request hits.
import api.strategies.aggregators  # noqa: F401
import api.strategies.builders  # noqa: F401
import api.strategies.cleaners  # noqa: F401
import api.strategies.clusterers  # noqa: F401
import api.strategies.reasoners  # noqa: F401
from fastapi import APIRouter, HTTPException

from api.strategies import StrategyDescriptor, all_descriptors
from api.strategies.descriptor import Kind
from api.strategies.registry import (
    aggregators,
    builders,
    cleaners,
    clusterers,
    reasoners,
)

router = APIRouter(prefix="/api", tags=["strategies"])


_REGISTRIES = {
    "builder": builders,
    "cleaner": cleaners,
    "clusterer": clusterers,
    "reasoner": reasoners,
    "aggregator": aggregators,
}


@router.get("/strategies", response_model=dict[str, list[StrategyDescriptor]])
def list_all_strategies() -> dict[str, list[StrategyDescriptor]]:
    """Aggregator endpoint — one round-trip for the whole wizard."""

    return all_descriptors()


@router.get("/builders", response_model=list[StrategyDescriptor])
def list_builders() -> list[StrategyDescriptor]:
    return builders.list()


@router.get("/cleaners", response_model=list[StrategyDescriptor])
def list_cleaners() -> list[StrategyDescriptor]:
    return cleaners.list()


@router.get("/clusterers", response_model=list[StrategyDescriptor])
def list_clusterers() -> list[StrategyDescriptor]:
    return clusterers.list()


@router.get("/reasoners", response_model=list[StrategyDescriptor])
def list_reasoners() -> list[StrategyDescriptor]:
    return reasoners.list()


@router.get("/aggregators", response_model=list[StrategyDescriptor])
def list_aggregators() -> list[StrategyDescriptor]:
    return aggregators.list()


@router.get(
    "/strategies/{kind}/{name}",
    response_model=StrategyDescriptor,
)
def describe_strategy(kind: Kind, name: str) -> StrategyDescriptor:
    """Single-strategy lookup for the wizard detail panel."""

    registry = _REGISTRIES.get(kind)
    if registry is None:
        raise HTTPException(status_code=404, detail=f"unknown strategy kind {kind!r}")
    try:
        return registry.get_descriptor(name)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"{kind} {name!r} not registered"
        ) from None
