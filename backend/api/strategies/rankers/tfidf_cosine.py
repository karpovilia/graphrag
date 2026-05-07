from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from api.domain.graph import Node
from api.strategies.registry import rankers


@rankers.register(
    "tfidf_cosine",
    summary="TF-IDF cosine over node.name + node.summary as the GNN baseline.",
    description=(
        "No-dependency baseline ranker — the floor a future GAT must beat "
        "for F5 to ship. IDF is computed across the candidate set per "
        "call (cheap because Phase 5 retrieves a shortlist of 50–200 "
        "nodes, not the whole graph). Russian morphology is ignored at "
        "this layer; lemmas are EDA's job and live in node.attributes."
    ),
    params_schema={
        "min_token_length": {
            "type": "integer",
            "default": 3,
        },
    },
    cost_hint="cheap",
    references=("docs/raw/2405.16506v3.pdf",),
)
class TfIdfCosineRanker:
    async def rank(
        self,
        query: str,
        candidates: list[Node],
        params: dict[str, Any],
    ) -> list[Node]:
        if not candidates:
            return []
        min_len = int(params.get("min_token_length", 3))

        candidate_tokens = [_tokenize(_node_text(n), min_len) for n in candidates]
        query_tokens = _tokenize(query, min_len)
        if not query_tokens:
            return list(candidates)

        # IDF over the candidate set itself — local IDF picks up domain
        # discriminative tokens without needing a corpus-level index.
        n_docs = len(candidate_tokens)
        df: Counter[str] = Counter()
        for toks in candidate_tokens:
            df.update(set(toks))
        idf = {tok: math.log((1 + n_docs) / (1 + count)) + 1 for tok, count in df.items()}

        def _tfidf_vec(toks: list[str]) -> dict[str, float]:
            tf = Counter(toks)
            return {tok: count * idf.get(tok, 1.0) for tok, count in tf.items()}

        query_vec = _tfidf_vec(query_tokens)
        scored: list[tuple[float, Node]] = []
        for cand, toks in zip(candidates, candidate_tokens, strict=True):
            score = _cosine(query_vec, _tfidf_vec(toks))
            scored.append((score, cand))

        scored.sort(key=lambda kv: (-kv[0], str(kv[1].id)))
        return [n for _, n in scored]


_TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)


def _tokenize(text: str, min_len: int) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) >= min_len]


def _node_text(node: Node) -> str:
    parts = [node.name]
    if node.summary:
        parts.append(node.summary)
    return " ".join(parts)


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    overlap = set(a) & set(b)
    if not overlap:
        return 0.0
    dot = sum(a[t] * b[t] for t in overlap)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
