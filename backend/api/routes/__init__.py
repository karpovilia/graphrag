"""HTTP routes. Each module exposes a `router` for inclusion in __main__."""

from .agents import router as agents_router
from .analysis import router as analysis_router
from .assistant import router as assistant_router
from .auth import router as auth_router
from .corpora import router as corpora_router
from .eda import router as eda_router
from .graphs import router as graphs_router
from .journal_export import router as journal_export_router
from .reason import router as reason_router
from .strategies import router as strategies_router
from .temporal import router as temporal_router
from .tog import router as tog_router
from .tools import router as tools_router

__all__ = [
    "agents_router",
    "analysis_router",
    "assistant_router",
    "auth_router",
    "corpora_router",
    "eda_router",
    "graphs_router",
    "journal_export_router",
    "reason_router",
    "strategies_router",
    "temporal_router",
    "tog_router",
    "tools_router",
]
