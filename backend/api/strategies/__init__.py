"""Strategy registries for R2.

Phase 1.1 — the substrate for every plugin kind: builders that produce
GraphVariants from corpora, cleaners that mutate them, clusterers that
assign communities, summarizers that fill in topic-layer summaries,
reasoners that answer queries against one or more variants.

Plugins register themselves via decorators on import. The orchestrator
(Phase 1.5) walks the registry to populate /api/builders, /api/cleaners,
etc., and to materialize a build pipeline from user-chosen names.
"""

from .descriptor import Kind, StrategyDescriptor
from .protocols import (
    AgentProtocol,
    AggregatorProtocol,
    BuilderProtocol,
    CleanerProtocol,
    ClustererProtocol,
    ExpertResult,
    NodeToolProtocol,
    RankerProtocol,
    ReasonerProtocol,
    ReasonResult,
)
from .registry import Registry, all_descriptors
from .state import GraphBuildState

# NOTE: do NOT re-export the per-kind registry singletons here. Their
# names (builders / cleaners / clusterers / reasoners) collide with the
# subpackage names under api/strategies/, and importing those
# subpackages would silently shadow the singletons. Callers reach for
# them via `from api.strategies.registry import cleaners` instead.

__all__ = [
    "AgentProtocol",
    "AggregatorProtocol",
    "BuilderProtocol",
    "CleanerProtocol",
    "ClustererProtocol",
    "ExpertResult",
    "GraphBuildState",
    "Kind",
    "NodeToolProtocol",
    "RankerProtocol",
    "ReasonResult",
    "ReasonerProtocol",
    "Registry",
    "StrategyDescriptor",
    "all_descriptors",
]
