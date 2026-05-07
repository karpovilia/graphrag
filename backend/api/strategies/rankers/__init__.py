"""Ranker plugins (Phase 5b — F5).

Importing this package registers every ranker. Reasoners pass a
post-retrieval candidate shortlist through `rank(query, candidates)`
to reorder before composing an answer.

`tfidf_cosine` is the always-on baseline (no torch). `gat` is the
GNN-driven ranker — descriptor registered now so the wizard surfaces
it; training/inference wiring lands in 5.x once embeddings are produced.
"""

from .gat import GATRanker
from .tfidf_cosine import TfIdfCosineRanker

__all__ = ["GATRanker", "TfIdfCosineRanker"]
