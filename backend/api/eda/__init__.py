"""Exploratory Data Analysis pass over a corpus.

Powers wizard step 3 (F4.2): given freshly uploaded documents, surface
the kind of corpus the user is dealing with and propose a starting
Builder/Cleaner/Clusterer + a NodeType set to seed F6.1. Heuristic and
fast — no LLM calls in the EDA path. Russian NER goes through natasha.
"""

from .ner import EntityMention, NatashaNer, NerProtocol
from .recommend import recommend
from .report import (
    DocumentStats,
    EdaReport,
    EntityFrequency,
    NodeTypeRecommendation,
    Recommendation,
)
from .service import EdaService

__all__ = [
    "DocumentStats",
    "EdaReport",
    "EdaService",
    "EntityFrequency",
    "EntityMention",
    "NatashaNer",
    "NerProtocol",
    "NodeTypeRecommendation",
    "Recommendation",
    "recommend",
]
