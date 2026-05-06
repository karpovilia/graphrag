"""HTTP routes. Each module exposes a `router` for inclusion in __main__."""

from .corpora import router as corpora_router
from .eda import router as eda_router
from .graphs import router as graphs_router
from .strategies import router as strategies_router

__all__ = [
    "corpora_router",
    "eda_router",
    "graphs_router",
    "strategies_router",
]
