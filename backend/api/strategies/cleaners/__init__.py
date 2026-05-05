"""Cleaner plugins.

Importing this package triggers @register decorators on every cleaner
class so the registry is populated. Add new cleaners here and re-export.
"""

from .llm_dedup import LLMDeduplicator
from .threshold_prune import ThresholdPruner

__all__ = ["LLMDeduplicator", "ThresholdPruner"]
