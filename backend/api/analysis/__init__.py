"""Analytical (read-only) computations over a built graph variant.

These are diagnostics, not pipeline stages: they read a GraphBuildState and
return summaries. The first is projection importance (which latent two-mode
projection carries non-redundant structure).
"""

from .projection_importance import (
    ProjectionImportanceResult,
    ProjectionStat,
    compute_projection_importance,
)

__all__ = [
    "ProjectionImportanceResult",
    "ProjectionStat",
    "compute_projection_importance",
]
