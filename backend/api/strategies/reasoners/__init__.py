"""Reasoner plugins.

Importing this package triggers @register decorators. KeywordSearchReasoner
is the one fully wired implementation in Phase 1.4 — it stays useful as
a cheap MoE baseline. The Microsoft and LightRAG entries are registered
with descriptors so /api/reasoners surfaces them in the wizard, but
`.reason()` raises NotImplementedError until their follow-up commits
land in 1.4.x.
"""

from .keyword_search import KeywordSearchReasoner
from .lightrag import LightRAGDualKeyword
from .microsoft import MicrosoftGlobalSearch, MicrosoftLocalSearch

__all__ = [
    "KeywordSearchReasoner",
    "LightRAGDualKeyword",
    "MicrosoftGlobalSearch",
    "MicrosoftLocalSearch",
]
