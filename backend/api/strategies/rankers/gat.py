from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger

from api.domain.graph import Node
from api.strategies.registry import rankers
from api.strategies.rankers.tfidf_cosine import TfIdfCosineRanker

from ._gat_model import load_embeddings


@rankers.register(
    "gat",
    summary="2-layer GAT relevance ranker over a precomputed node-embedding cache.",
    description=(
        "F5 GNN ranker. Architecture: 2-layer Graph Attention Network "
        "(PyG-flavored) trained contrastively against community "
        "membership — nodes in the same community come close in the "
        "16-dim output space. At inference we don't run the GAT live: "
        "training caches per-node embeddings into an .npz keyed by "
        "graph_variant_id, and ranking blends a TF-IDF baseline (text "
        "match against query) with structural centrality (mean cosine "
        "to the top-K TF-IDF candidates in GAT space). Falls back to "
        "TfIdfCosineRanker if the embeddings file is missing — so the "
        "wizard works before training is run."
    ),
    params_schema={
        "embeddings_path": {
            "type": "string",
            "default": "",
            "description": (
                "Path to the .npz produced by scripts.train_gat. Empty "
                "→ resolves to STORAGE__DATA_DIR/gat/{variant_id}.npz; "
                "empty + missing file triggers fallback."
            ),
        },
        "alpha_tfidf": {
            "type": "number",
            "default": 0.6,
            "description": "Weight of the TF-IDF text-match score (0..1).",
        },
        "beta_structural": {
            "type": "number",
            "default": 0.4,
            "description": "Weight of the GAT structural-centrality boost.",
        },
        "top_k_anchor": {
            "type": "integer",
            "default": 10,
            "description": "Number of TF-IDF top hits used to define the centroid in GAT space.",
        },
    },
    cost_hint="moderate",
    references=("docs/raw/2405.16506v3.pdf", "docs/raw/2509.21710v2.pdf"),
)
class GATRanker:
    """Stateless wrapper. Embeddings are loaded lazily on first call and
    cached on the instance — orchestrator constructs one ranker per
    process and reuses it.
    """

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, np.ndarray]] = {}
        self._fallback = TfIdfCosineRanker()

    async def rank(
        self,
        query: str,
        candidates: list[Node],
        params: dict[str, Any],
    ) -> list[Node]:
        if not candidates:
            return []

        explicit_path = params.get("embeddings_path") or ""
        emb_map = self._resolve_embeddings(candidates, Path(explicit_path) if explicit_path else None)
        if emb_map is None:
            return await self._fallback.rank(query, candidates, params)

        # TF-IDF first; we use the same cosine the baseline does so the
        # ranker degrades smoothly when training quality is poor.
        tfidf_ranked = await self._fallback.rank(query, candidates, params)
        alpha = float(params.get("alpha_tfidf", 0.6))
        beta = float(params.get("beta_structural", 0.4))
        top_k = int(params.get("top_k_anchor", 10))
        anchors = tfidf_ranked[:top_k]
        anchor_embs = [emb_map[str(n.id)] for n in anchors if str(n.id) in emb_map]
        if not anchor_embs:
            return tfidf_ranked
        centroid = np.mean(np.stack(anchor_embs, axis=0), axis=0)
        c_norm = np.linalg.norm(centroid)
        if c_norm == 0:
            return tfidf_ranked
        centroid /= c_norm

        # Build the original TF-IDF ranks → score map. Lower rank index
        # = higher score; we map index i ∈ [0, N) to (N - i) / N ∈ (0, 1].
        n = len(tfidf_ranked)
        tfidf_score = {str(c.id): (n - i) / n for i, c in enumerate(tfidf_ranked)}

        scored: list[tuple[float, Node]] = []
        for c in candidates:
            s_text = tfidf_score.get(str(c.id), 0.0)
            v = emb_map.get(str(c.id))
            if v is None:
                s_struct = 0.0
            else:
                v_norm = np.linalg.norm(v)
                s_struct = float(v @ centroid / v_norm) if v_norm > 0 else 0.0
            scored.append((alpha * s_text + beta * s_struct, c))

        scored.sort(key=lambda kv: (-kv[0], str(kv[1].id)))
        return [n for _, n in scored]

    # ---- internals ----

    def _resolve_embeddings(
        self,
        candidates: list[Node],
        explicit: Path | None,
    ) -> dict[str, np.ndarray] | None:
        if explicit is not None:
            return self._load_cached(explicit)
        # Default: pick by variant_id so a single ranker instance can
        # serve multiple variants in a MoE run.
        first = candidates[0].graph_variant_id
        cache_key = str(first)
        if cache_key in self._cache:
            return self._cache[cache_key]
        path = self._default_path(first)
        loaded = self._load_cached(path)
        if loaded is None:
            self._cache[cache_key] = {}  # poisoned cache so we don't retry
            return None
        self._cache[cache_key] = loaded
        return loaded

    def _load_cached(self, path: Path) -> dict[str, np.ndarray] | None:
        if not path.exists():
            logger.warning("GATRanker: embeddings file {} not found — falling back", path)
            return None
        try:
            mapping, _fdim = load_embeddings(path)
            logger.debug("GATRanker: loaded {} embeddings from {}", len(mapping), path)
            return mapping
        except Exception as e:
            logger.exception("GATRanker: failed to read {}: {}", path, e)
            return None

    @staticmethod
    def _default_path(variant_id: object) -> Path:
        from api.config import get_settings

        s = get_settings()
        return s.storage.data_dir / "gat" / f"{variant_id}.npz"
