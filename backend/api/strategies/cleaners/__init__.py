"""Cleaner plugins.

Importing this package triggers @register decorators on every cleaner
class so the registry is populated. Add new cleaners here and re-export.
"""

from .canonical_alias import CanonicalAlias
from .llm_dedup import LLMDeduplicator
from .threshold_prune import ThresholdPruner

__all__ = ["CanonicalAlias", "LLMDeduplicator", "ThresholdPruner"]
