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
    BuilderProtocol,
    CleanerProtocol,
    ClustererProtocol,
    ReasonerProtocol,
    ReasonResult,
)
from .registry import Registry, all_descriptors, builders, cleaners, clusterers, reasoners
from .state import GraphBuildState

__all__ = [
    "BuilderProtocol",
    "CleanerProtocol",
    "ClustererProtocol",
    "GraphBuildState",
    "Kind",
    "ReasonResult",
    "ReasonerProtocol",
    "Registry",
    "StrategyDescriptor",
    "all_descriptors",
    "builders",
    "cleaners",
    "clusterers",
    "reasoners",
]
