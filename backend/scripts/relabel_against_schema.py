"""Apply a CorpusSchema to an existing GraphVariant via relabeling.

Cheap alternative to re-extracting: we already have all the entities
and edges, we just need to (a) retype each entity to a schema entity_type
(via examples-match + LLM batch fallback), and (b) canonicalize each
distinct predicate string to a schema relation_type. Then drop edges
whose endpoints don't satisfy the relation's domain/range, and re-run
Leiden so communities reflect the new (typed) edge set.

Cost: ~3-5 min for a 20k-entity graph on Deepseek vs ~100 min for a
full re-extract.

The API server must be stopped before running.

Usage:
    cd backend && .venv/bin/python -m scripts.relabel_against_schema \\
        --variant-id <uuid> [--variant-id <uuid> ...]
"""

from __future__ import annotations

import argparse
import asyncio
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

from api.agents.schema_relabeler import (  # noqa: E402
    apply_relabeling,
    relabel_entities,
    relabel_relations,
)
from api.config import get_settings  # noqa: E402
from api.domain.graph import EdgeType, Layer  # noqa: E402
from api.domain.schema import CorpusSchema  # noqa: E402
from api.llm import register_clients  # noqa: E402
from api.llm.deepseek import DeepseekClient  # noqa: E402
from api.repository.snapshot import SnapshotRepository  # noqa: E402
from api.strategies.state import GraphBuildState  # noqa: E402

import api.strategies.builders  # noqa: E402, F401
import api.strategies.clusterers  # noqa: E402, F401
from api.strategies.registry import clusterers  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--variant-id",
        action="append",
        required=True,
        help="UUID of a GraphVariant to relabel. Pass multiple times.",
    )
    parser.add_argument(
        "--clusterer",
        default="leiden",
        help="Clusterer to re-run after relabeling.",
    )
    parser.add_argument(
        "--resolution",
        type=float,
        default=1.0,
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
    )
    parser.add_argument(
        "--entity-batch",
        type=int,
        default=50,
        help="Entities per LLM relabel call.",
    )
    parser.add_argument(
        "--predicate-batch",
        type=int,
        default=30,
        help=(
            "Distinct predicate strings per LLM relabel call. "
            "Smaller batches dramatically reduce mode-collapse into DROP — "
            "LLMs that see a few junk predicates start padding the rest "
            "with DROP. 30 is the empirical sweet spot."
        ),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
    )
    parser.add_argument(
        "--strict-domain-range",
        action="store_true",
        help=(
            "Drop typed edges where source/target types violate the "
            "relation's domain/range. Default: soft mode — such edges "
            "are kept and tagged attributes.ill_typed=true so the UI "
            "can filter them."
        ),
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.deepseek.api_key:
        logger.error("DEEPSEEK__API_KEY not set")
        return 2

    register_clients(
        completion={
            "deepseek": DeepseekClient(
                api_key=settings.deepseek.api_key,
                base_url=settings.deepseek.base_url,
                default_model=settings.deepseek.model,
                timeout_s=settings.deepseek.timeout_s,
            )
        },
        default_completion="deepseek",
    )
    from api.llm import get_completion_client

    llm = get_completion_client()

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
            corpus = await repo.get_corpus(variant.corpus_id)
        except Exception as e:
            logger.error("variant {} not found: {}", variant_id, e)
            return 3

        schema_raw = corpus.metadata.get("schema")
        if not schema_raw:
            logger.error(
                "corpus {} has no committed schema — set it via "
                "PUT /api/corpora/{}/schema first",
                corpus.id,
                corpus.id,
            )
            return 4
        schema = CorpusSchema.model_validate(schema_raw)
        logger.info(
            "variant {}: schema v{} = {} entity_types, {} relation_types",
            variant_id,
            schema.version,
            len(schema.entity_types),
            len(schema.relation_types),
        )

        entities = [n for n in state.nodes if n.layer == Layer.ENTITY]
        started = datetime.now(tz=timezone.utc)

        entity_mapping, _entity_report = await relabel_entities(
            entities,
            schema,
            llm,
            batch_size=args.entity_batch,
            concurrency=args.concurrency,
        )

        distinct_predicates = sorted(
            {
                (e.relation or "").strip()
                for e in state.edges
                if e.type == EdgeType.ENTITY_RELATION and e.relation
            }
        )
        logger.info(
            "variant {}: {} distinct predicates", variant_id, len(distinct_predicates)
        )
        relation_mapping, rel_calls = await relabel_relations(
            distinct_predicates,
            schema,
            llm,
            batch_size=args.predicate_batch,
            concurrency=args.concurrency,
        )

        new_nodes, new_edges, report = apply_relabeling(
            state.nodes,
            state.edges,
            entity_mapping,
            relation_mapping,
            schema,
            strict_domain_range=args.strict_domain_range,
        )
        report.llm_calls += rel_calls

        # Re-cluster: edges have changed (drops + retypes), communities
        # need to be regenerated.
        stripped = GraphBuildState(
            nodes=new_nodes, edges=new_edges, journal=list(state.journal)
        )
        new_state = await clusterer_inst.cluster(stripped, clusterer_params)
        elapsed = (datetime.now(tz=timezone.utc) - started).total_seconds()

        # Overwrite variant in-place via direct dict mutation, like
        # rewrite_edge_weights does — SnapshotRepository inherits from
        # InMemoryRepository so private attrs are shared.
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
                    "schema_relabeled": True,
                    "schema_version": schema.version,
                    "relabel_report": {
                        "entities_before": report.entities_before,
                        "entities_after": report.entities_after,
                        "entities_dropped": report.entities_dropped,
                        "relations_before": report.relations_before,
                        "relations_after": report.relations_after,
                        "relations_dropped_unmapped": report.relations_dropped_unmapped,
                        "relations_dropped_ill_typed": report.relations_dropped_ill_typed,
                        "distinct_predicates_in": report.distinct_predicates_in,
                        "distinct_predicates_mapped": report.distinct_predicates_mapped,
                        "llm_calls": report.llm_calls,
                        "elapsed_s": round(elapsed, 1),
                    },
                },
            }
        )
        repo._variants[variant_id] = updated_variant  # type: ignore[attr-defined]

        logger.info(
            "variant {}: entities {}→{} (-{}), relations {}→{} (unmapped -{}, ill-typed -{}), {} LLM calls, {:.1f}s",
            variant_id,
            report.entities_before,
            report.entities_after,
            report.entities_dropped,
            report.relations_before,
            report.relations_after,
            report.relations_dropped_unmapped,
            report.relations_dropped_ill_typed,
            report.llm_calls,
            elapsed,
        )
        logger.info(
            "variant {}: type distribution = {}",
            variant_id,
            sorted(report.entity_type_distribution.items(), key=lambda kv: -kv[1]),
        )

    await repo._snapshot()  # type: ignore[attr-defined]
    logger.info("snapshot written to {}", snapshot_path)
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
