"""Train the GAT relevance ranker for one GraphVariant.

Phase 5b finish. Loads a variant via RepositoryProtocol, materializes
its (features, edge_index), and trains a 2-layer GAT contrastively
against community membership: nodes in the same COMMUNITY-layer node
come close in 16-dim embedding space, random pairs stay far. After
training, per-node embeddings are written to STORAGE__DATA_DIR/gat/
{variant_id}.npz so GATRanker.rank can blend them with the TF-IDF
baseline at inference.

Run:
    uv run python -m scripts.train_gat <variant_id> [--epochs 50] [--postgres]

Without `--postgres` the script uses InMemoryRepository, which is only
useful when paired with a prior `migrate_podcast` run in the same
process — practical use is `--postgres` against the alembic-migrated
DB, where the variant already lives.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import random
from pathlib import Path
from uuid import UUID

import numpy as np
import torch
import torch.nn.functional as F
from loguru import logger
from torch import nn

from api.config import get_settings
from api.repository import InMemoryRepository, RepositoryProtocol
from api.strategies.rankers._gat_model import (
    DEFAULT_HIDDEN,
    DEFAULT_OUT,
    DEFAULT_HEADS,
    GATEncoder,
    feature_dim,
    save_embeddings,
    tensorize,
)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("variant_id", help="GraphVariant.id (UUID)")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--lr", type=float, default=5e-3)
    parser.add_argument("--hidden", type=int, default=DEFAULT_HIDDEN)
    parser.add_argument("--out", type=int, default=DEFAULT_OUT)
    parser.add_argument("--heads", type=int, default=DEFAULT_HEADS)
    parser.add_argument(
        "--negatives-per-anchor",
        type=int,
        default=4,
        help="Random negatives drawn per positive pair.",
    )
    parser.add_argument(
        "--margin",
        type=float,
        default=0.5,
        help="Triplet-loss margin. Larger = stricter separation.",
    )
    parser.add_argument(
        "--postgres",
        action="store_true",
        help="Use PostgresRepository instead of InMemoryRepository.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Affects feature projection AND torch RNG.",
    )
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    np.random.seed(args.seed)

    repo = await _make_repo(use_postgres=args.postgres)
    state = await repo.load_state(UUID(args.variant_id))
    logger.info(
        "loaded variant {}: nodes={} edges={}",
        args.variant_id,
        len(state.nodes),
        len(state.edges),
    )

    tg = tensorize(state.nodes, state.edges, seed=args.seed)
    logger.info(
        "feature dim={} community-tagged nodes={}",
        tg.features.shape[1],
        len(tg.community_of),
    )

    if not tg.community_of:
        raise SystemExit(
            "no MEMBER_OF edges in this variant — train_gat needs community "
            "labels to mine positive pairs",
        )

    pairs = _community_pairs(tg.community_of)
    if not pairs:
        raise SystemExit("no community has ≥2 members; nothing to train against")

    logger.info("mined {} positive pairs", len(pairs))

    model = GATEncoder(
        in_dim=tg.features.shape[1],
        hidden=args.hidden,
        out=args.out,
        heads=args.heads,
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)

    n_nodes = tg.features.shape[0]
    rng = random.Random(args.seed)

    for epoch in range(args.epochs):
        model.train()
        emb = model(tg.features, tg.edge_index)

        loss = _triplet_loss(
            emb=emb,
            pairs=pairs,
            n_nodes=n_nodes,
            negatives=args.negatives_per_anchor,
            margin=args.margin,
            rng=rng,
        )

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        if (epoch + 1) % 10 == 0 or epoch == 0:
            logger.info("epoch {:>3}: loss={:.4f}", epoch + 1, loss.item())

    model.eval()
    with torch.no_grad():
        final_emb = model(tg.features, tg.edge_index)

    s = get_settings()
    out_path = s.storage.data_dir / "gat" / f"{args.variant_id}.npz"
    save_embeddings(
        out_path,
        node_ids=tg.node_ids,
        embeddings=final_emb,
        feature_dim=tg.features.shape[1],
    )
    logger.info("wrote {} ({} nodes, {} dims)", out_path, n_nodes, args.out)
    print(str(out_path))


async def _make_repo(*, use_postgres: bool) -> RepositoryProtocol:
    if not use_postgres:
        logger.info("using InMemoryRepository — variant must already be loaded into this process")
        return InMemoryRepository()
    from api.db.engine import get_sessionmaker
    from api.repository.postgres import PostgresRepository

    return PostgresRepository(sessionmaker=get_sessionmaker())


def _community_pairs(community_of: dict[int, object]) -> list[tuple[int, int]]:
    """All within-community ordered pairs (i, j) with i < j. The trainer
    re-mines negatives every step so this small set generalizes.
    """

    by_community: dict[object, list[int]] = {}
    for node_idx, community_id in community_of.items():
        by_community.setdefault(community_id, []).append(node_idx)
    pairs: list[tuple[int, int]] = []
    for members in by_community.values():
        if len(members) < 2:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                pairs.append((members[i], members[j]))
    return pairs


def _triplet_loss(
    *,
    emb: torch.Tensor,
    pairs: list[tuple[int, int]],
    n_nodes: int,
    negatives: int,
    margin: float,
    rng: random.Random,
) -> torch.Tensor:
    """Margin-based triplet loss. For each (a, p), draw `negatives`
    random nodes; loss = max(0, d(a,p) - d(a,n) + margin) averaged over
    the batch. Distances are 1 - cosine since emb is L2-normalized.
    """

    a_idx = torch.tensor([p[0] for p in pairs], dtype=torch.long)
    p_idx = torch.tensor([p[1] for p in pairs], dtype=torch.long)
    n_idx_list: list[int] = []
    for _ in range(negatives):
        for _ in pairs:
            n_idx_list.append(rng.randrange(n_nodes))
    n_idx = torch.tensor(n_idx_list, dtype=torch.long).reshape(negatives, len(pairs))

    a_emb = emb[a_idx]
    p_emb = emb[p_idx]
    pos_dist = 1.0 - (a_emb * p_emb).sum(dim=-1)

    # Negatives: stack all (negatives × pairs) and broadcast against
    # the same anchor for each.
    losses = []
    for k in range(negatives):
        n_emb = emb[n_idx[k]]
        neg_dist = 1.0 - (a_emb * n_emb).sum(dim=-1)
        losses.append(F.relu(pos_dist - neg_dist + margin))
    return torch.stack(losses).mean()


if __name__ == "__main__":
    asyncio.run(main())
