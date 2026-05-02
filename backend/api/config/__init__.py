"""R2 settings.

Replaces the in-tree backend/api/settings.py once the legacy entry point
(backend/api/__main__.py with parquet-loaded PODCAST/GAZETA globals) is
retired in Phase 0.6. Until then both modules coexist.
"""

from .settings import (
    DeepseekSettings,
    PostgresSettings,
    R2Settings,
    StorageSettings,
    YandexSettings,
    get_settings,
)

__all__ = [
    "DeepseekSettings",
    "PostgresSettings",
    "R2Settings",
    "StorageSettings",
    "YandexSettings",
    "get_settings",
]
