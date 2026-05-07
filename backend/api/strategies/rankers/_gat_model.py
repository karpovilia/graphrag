"""2-layer GAT encoder + feature builder.

Phase 5b finish. The model takes per-node features (layer one-hot +
log-degree + name-hash projection) and graph structure (edge_index in
the PyG sense) and emits one embedding vector per node. Trained
contrastively against community membership: nodes in the same
community come close, others stay far.

Inference doesn't run the full GAT — at training time we cache one
embedding per node into an `.npz` blob keyed by graph_variant_id,
and `GATRanker.rank()` just looks them up. Cheaper than rebuilding the
forward pass per query, and matches how F5 will eventually score
queries via FAISS over node embeddings.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch_geometric.nn import GATConv

from api.domain.graph import Edge, Node
from api.domain.types import Id

LAYER_ORDER: list[str] = ["chunk", "entity", "community", "topic"]
"""Stable ordering for the layer one-hot. The forward pass relies on
positions, so don't reshuffle without retraining."""

DEFAULT_NAME_PROJ_DIM = 16
DEFAULT_HIDDEN = 32
DEFAULT_OUT = 16
DEFAULT_HEADS = 4


def feature_dim(name_proj_dim: int = DEFAULT_NAME_PROJ_DIM) -> int:
    """Total per-node feature dimension."""

    # layer one-hot + log-in-degree + log-out-degree + name projection
    return len(LAYER_ORDER) + 2 + name_proj_dim


@dataclass
class TensorizedGraph:
    node_ids: list[Id]
    features: torch.Tensor  # [N, feature_dim]
    edge_index: torch.Tensor  # [2, 2E] (symmetric)
    community_of: dict[int, Id]
    """node_index → community_id (for the entity-layer subset)."""


def tensorize(
    nodes: list[Node],
    edges: list[Edge],
    *,
    name_proj_dim: int = DEFAULT_NAME_PROJ_DIM,
    seed: int = 42,
) -> TensorizedGraph:
    """Materialize a R2 graph into the (features, edge_index) pair the
    GATEncoder consumes. Edges are made symmetric — GAT expects
    undirected message-passing for the relational graph we care about.
    """

    rng = np.random.default_rng(seed)
    node_id_to_idx = {n.id: i for i, n in enumerate(nodes)}

    in_deg: dict[Id, int] = defaultdict(int)
    out_deg: dict[Id, int] = defaultdict(int)
    for e in edges:
        out_deg[e.source_node_id] += 1
        in_deg[e.target_node_id] += 1

    # Random projection for name hash. The same RNG seed gives
    # deterministic features across runs — important for reproducibility
    # of community-prediction baselines.
    name_proj_matrix = rng.standard_normal((128, name_proj_dim)).astype(np.float32)

    features = np.zeros((len(nodes), feature_dim(name_proj_dim)), dtype=np.float32)
    for i, n in enumerate(nodes):
        # layer one-hot
        if n.layer.value in LAYER_ORDER:
            features[i, LAYER_ORDER.index(n.layer.value)] = 1.0
        # log-normalized degrees
        features[i, len(LAYER_ORDER)] = math.log1p(in_deg[n.id])
        features[i, len(LAYER_ORDER) + 1] = math.log1p(out_deg[n.id])
        # name projection: char-bucket count → matrix product
        if n.name:
            counts = np.zeros(128, dtype=np.float32)
            for ch in n.name.lower():
                counts[ord(ch) % 128] += 1.0
            counts /= max(counts.sum(), 1.0)
            features[i, len(LAYER_ORDER) + 2 :] = counts @ name_proj_matrix

    src: list[int] = []
    dst: list[int] = []
    for e in edges:
        s = node_id_to_idx.get(e.source_node_id)
        t = node_id_to_idx.get(e.target_node_id)
        if s is None or t is None:
            continue
        src.append(s)
        dst.append(t)
    # Symmetric edge_index for undirected message-passing.
    edge_index = torch.tensor(
        [src + dst, dst + src],
        dtype=torch.long,
    ) if src else torch.empty((2, 0), dtype=torch.long)

    # Build the community label index from MEMBER_OF edges. Used by
    # the contrastive trainer to mine positive pairs without
    # re-walking edges every batch.
    from api.domain.graph import EdgeType

    community_of: dict[int, Id] = {}
    for e in edges:
        if e.type != EdgeType.MEMBER_OF:
            continue
        s = node_id_to_idx.get(e.source_node_id)
        if s is not None:
            community_of[s] = e.target_node_id

    return TensorizedGraph(
        node_ids=[n.id for n in nodes],
        features=torch.from_numpy(features),
        edge_index=edge_index,
        community_of=community_of,
    )


class GATEncoder(nn.Module):
    """2-layer GAT, ELU activation between layers, no dropout (small
    graphs in this codebase don't need it). Output is L2-normalized so
    inner-product becomes cosine similarity downstream.
    """

    def __init__(
        self,
        in_dim: int,
        hidden: int = DEFAULT_HIDDEN,
        out: int = DEFAULT_OUT,
        heads: int = DEFAULT_HEADS,
    ) -> None:
        super().__init__()
        self.gat1 = GATConv(in_dim, hidden, heads=heads, concat=True)
        self.gat2 = GATConv(hidden * heads, out, heads=1, concat=False)
        self.act = nn.ELU()

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        h = self.act(self.gat1(x, edge_index))
        h = self.gat2(h, edge_index)
        return torch.nn.functional.normalize(h, dim=-1)


def save_embeddings(
    path: Path,
    *,
    node_ids: list[Id],
    embeddings: torch.Tensor,
    feature_dim: int,
) -> None:
    """Persist trained per-node embeddings as a single .npz blob.

    Schema:
        ids: U64 byte-array of stringified UUIDs (one per row)
        emb: float32 [N, D]
        meta: shape + feature_dim sentinel
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        path,
        ids=np.array([str(i) for i in node_ids], dtype="U64"),
        emb=embeddings.detach().cpu().numpy().astype(np.float32),
        feature_dim=np.int64(feature_dim),
    )


def load_embeddings(path: Path) -> tuple[dict[str, np.ndarray], int]:
    """Inverse of save_embeddings. Returns id→vector dict + the feature
    dim so the ranker can sanity-check it isn't being fed embeddings
    trained with a different feature recipe.
    """

    blob = np.load(path)
    ids = blob["ids"].tolist()
    emb = blob["emb"]
    fdim = int(blob["feature_dim"])
    return {str(i): emb[idx] for idx, i in enumerate(ids)}, fdim
