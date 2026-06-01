"""Post-process existing GraphVariant: apply log1p to entity-relation
edge weights and re-cluster.

Used to retrofit the log1p weight transform onto variants that were
built before the transform landed in `_llm_extract.py`. The pipeline:

  1. Load variant state.
  2. For every ENTITY_RELATION edge, replace `weight` with
     `log1p(raw_weight)` (raw is preserved in `attributes.raw_weight`).
  3. Drop COMMUNITY-layer nodes and MEMBER_OF edges.
  4. Re-run Leiden on the new weights.
  5. Overwrite the variant's stored state + counters in-place.

The API server MUST be stopped before running this — both processes hold
their own SnapshotRepository state in memory and would race the JSON
dump otherwise.

Usage:
    cd backend && .venv/bin/python -m scripts.rewrite_edge_weights \\
        --variant-id <uuid> [--variant-id <uuid> ...]
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from loguru import logger

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # pragma: no cover
    pass

from api.config import get_settings  # noqa: E402
from api.domain.graph import EdgeType, Layer  # noqa: E402
from api.repository.snapshot import SnapshotRepository  # noqa: E402
from api.strategies.state import GraphBuildState  # noqa: E402

# Side-effect imports to register clusterer plugins.
import api.strategies.builders  # noqa: E402, F401
import api.strategies.clusterers  # noqa: E402, F401
from api.strategies.registry import clusterers  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--variant-id",
        action="append",
        required=True,
        help="UUID of a GraphVariant to rewrite. Pass multiple times.",
    )
    parser.add_argument(
        "--clusterer",
        default="leiden",
        help="Clusterer to re-run after weight transform.",
    )
    parser.add_argument(
        "--resolution",
        type=float,
        default=1.0,
        help="Resolution param for Leiden (higher = more, smaller communities).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
    )
    args = parser.parse_args()

    settings = get_settings()
    snapshot_path = settings.storage.data_dir / "state.json"
    repo = SnapshotRepository(snapshot_path=snapshot_path)
    logger.info("loaded SnapshotRepository at {}", snapshot_path)

    clusterer_cls = clusterers.get(args.clusterer)
    clusterer_inst = clusterer_cls()
    clusterer_params = {
        "resolution": args.resolution,
        "seed": args.seed,
        "n_iterations": 10,
    }

    for raw_id in args.variant_id:
        variant_id = UUID(raw_id)
        try:
            variant = await repo.get_variant(variant_id)
            state = await repo.load_state(variant_id)
        except Exception as e:
            logger.error("variant {} not found: {}", variant_id, e)
            return 2

        before_edges = len(state.edges)
        before_relation = sum(
            1 for e in state.edges if e.type == EdgeType.ENTITY_RELATION
        )
        before_communities = sum(1 for n in state.nodes if n.layer == Layer.COMMUNITY)

        # 1. log1p weight transform on entity_relation edges
        new_edges = []
        for e in state.edges:
            if e.type == EdgeType.ENTITY_RELATION:
                raw = float(e.weight if e.weight is not None else 1.0)
                attrs = dict(e.attributes)
                # Don't double-transform: if raw_weight is already stored,
                # the edge was rewritten before. Skip.
                if "raw_weight" not in attrs:
                    attrs["raw_weight"] = raw
                    new_weight = math.log1p(raw)
                else:
                    new_weight = e.weight
                new_edges.append(e.model_copy(update={"weight": new_weight, "attributes": attrs}))
            else:
                new_edges.append(e)

        # 2. drop old COMMUNITY-layer nodes and MEMBER_OF edges
        old_community_ids = {n.id for n in state.nodes if n.layer == Layer.COMMUNITY}
        nodes_no_communities = [n for n in state.nodes if n.layer != Layer.COMMUNITY]
        edges_no_members = [
            e
            for e in new_edges
            if e.type != EdgeType.MEMBER_OF
            and e.source_node_id not in old_community_ids
            and e.target_node_id not in old_community_ids
        ]
        stripped_state = GraphBuildState(
            nodes=nodes_no_communities,
            edges=edges_no_members,
            journal=list(state.journal),
        )

        # 3. re-cluster
        logger.info(
            "variant {}: {} edges → log1p, dropping {} old communities and "
            "{} member_of edges; re-running {}",
            variant_id,
            before_relation,
            before_communities,
            before_edges - len(edges_no_members),
            args.clusterer,
        )
        new_state = await clusterer_inst.cluster(stripped_state, clusterer_params)

        # 4. overwrite in-place: rewrite _states/_base_states, refresh
        # variant counters/timestamps. SnapshotRepository inherits from
        # InMemoryRepository, so these private attrs are the same dicts.
        repo._states[variant_id] = new_state  # type: ignore[attr-defined]
        repo._base_states[variant_id] = new_state  # type: ignore[attr-defined]
        new_layers = sorted({n.layer for n in new_state.nodes})
        updated_variant = variant.model_copy(
            update={
                "node_count": len(new_state.nodes),
                "edge_count": len(new_state.edges),
                "layers_present": list(new_layers),
                "completed_at": datetime.now(tz=timezone.utc),
                "config": {
                    **variant.config,
                    "edge_weight_transform": "log1p",
                    "reclustered_at": datetime.now(tz=timezone.utc).isoformat(),
                },
            }
        )
        repo._variants[variant_id] = updated_variant  # type: ignore[attr-defined]

        after_communities = sum(1 for n in new_state.nodes if n.layer == Layer.COMMUNITY)
        logger.info(
            "variant {}: now {} nodes / {} edges / {} communities",
            variant_id,
            updated_variant.node_count,
            updated_variant.edge_count,
            after_communities,
        )

    # 5. one snapshot at the end covers all variants
    await repo._snapshot()  # type: ignore[attr-defined]
    logger.info("snapshot written to {}", snapshot_path)
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
