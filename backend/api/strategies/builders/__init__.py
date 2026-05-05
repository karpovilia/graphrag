"""Builder plugins.

Importing this package triggers @register decorators. NerExtractionBuilder
is the one fully wired implementation in Phase 1.2 — natasha NER over
chunks, no LLM, doubles as MoE baseline. Microsoft / LightRAG / ToG3 /
FastRAG ship with descriptors so /api/builders surfaces the wizard
cards; their .build() raises NotImplementedError until follow-ups land.
"""

from .fastrag import FastRAGBuilder
from .lightrag import LightRAGBuilder
from .microsoft import MicrosoftBuilder
from .ner_extraction import NerExtractionBuilder
from .tog3 import ToG3Builder

__all__ = [
    "FastRAGBuilder",
    "LightRAGBuilder",
    "MicrosoftBuilder",
    "NerExtractionBuilder",
    "ToG3Builder",
]
