"""Vector store gateway.

Per R-02 (`docs/redesign/research/vector_store.md`) the R2 backend is
FAISS in a per-graph-index pattern: one HNSW index per (graph_variant_id,
model). The Protocol stays generic so a swap to Qdrant or pgvector in R3
costs one file, not call-site rewrites.
"""

from .base import (
    And,
    Eq,
    Filter,
    In,
    Not,
    Or,
    SearchHit,
    VecItem,
    VectorStoreError,
    VectorStoreProtocol,
)

__all__ = [
    "And",
    "Eq",
    "Filter",
    "In",
    "Not",
    "Or",
    "SearchHit",
    "VecItem",
    "VectorStoreError",
    "VectorStoreProtocol",
]
