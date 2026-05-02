"""Domain model for GraphRAG Explorer R2.

All persisted entities live here as Pydantic v2 models. The model is the
contract between API, strategy plugins, and persistence — no plugin
imports anything outside this package to talk about graphs.
"""

from .corpus import Corpus, Document, DocumentSpan
from .curation import (
    JournalEntry,
    JournalOp,
    Suggestion,
    SuggestionAction,
    SuggestionStatus,
)
from .graph import (
    Edge,
    EdgeType,
    GraphVariant,
    GraphVariantStatus,
    Layer,
    Node,
    NodeType,
)
from .run import Run, RunKind, RunStatus, ToolInvocation
from .types import EmbeddingRef, Id, Provenance

__all__ = [
    "Corpus",
    "Document",
    "DocumentSpan",
    "Edge",
    "EdgeType",
    "EmbeddingRef",
    "GraphVariant",
    "GraphVariantStatus",
    "Id",
    "JournalEntry",
    "JournalOp",
    "Layer",
    "Node",
    "NodeType",
    "Provenance",
    "Run",
    "RunKind",
    "RunStatus",
    "Suggestion",
    "SuggestionAction",
    "SuggestionStatus",
    "ToolInvocation",
]
