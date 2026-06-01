"""One-off script: run a builder pipeline on an existing corpus.

Loads the snapshot repository, picks the corpus by name, runs the full
build pipeline (builder + cleaners + clusterer), persists the resulting
GraphVariant. Designed to be safe to re-run — variants with the same
name are skipped unless --force is passed.

The API server must be stopped before running this (both processes hold
their own SnapshotRepository state in memory and would race each other's
JSON dumps).

Usage:
    cd backend && .venv/bin/python -m scripts.run_builder_on_corpus \\
        --corpus-name "Afina (meeting notes)" \\
        --builder lightrag \\
        --variant-name afina-lightrag-v1
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

# Load .env BEFORE importing settings so DEEPSEEK__API_KEY is picked up
# even when this script is invoked from outside docker compose.
try:
    from dotenv import load_dotenv

    here = Path(__file__).resolve().parent.parent
    load_dotenv(here / ".env")
except ImportError:  # pragma: no cover
    pass

from api.config import get_settings  # noqa: E402
from api.domain.corpus import Document  # noqa: E402
from api.domain.graph import GraphVariant, GraphVariantStatus  # noqa: E402
from api.domain.types import new_id  # noqa: E402
from api.llm import register_clients  # noqa: E402
from api.llm.deepseek import DeepseekClient  # noqa: E402
from api.orchestrator import run_build_pipeline  # noqa: E402
from api.repository.snapshot import SnapshotRepository  # noqa: E402

# Import for side effects: each builder / cleaner / clusterer module
# registers itself via decorator at import time. Mirrors what
# routes/strategies.py does in the FastAPI app.
import api.strategies.builders  # noqa: E402, F401
import api.strategies.cleaners  # noqa: E402, F401
import api.strategies.clusterers  # noqa: E402, F401


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-name", required=True)
    parser.add_argument("--builder", required=True, choices=["lightrag", "microsoft"])
    parser.add_argument("--variant-name", required=True)
    parser.add_argument("--clusterer", default="leiden")
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=0,
        help="Cap LLM calls (0 = unlimited).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="Concurrent LLM extractions.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=0,
        help="Override builder default chunk_size (0 = builder default).",
    )
    parser.add_argument(
        "--gleanings",
        type=int,
        default=1,
        help="Microsoft only — extra refinement passes per chunk.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace any existing variant with the same name.",
    )
    parser.add_argument(
        "--no-schema",
        action="store_true",
        help=(
            "Force open-vocabulary extraction even when a Corpus.metadata.schema "
            "is committed. Useful for A/B comparison runs."
        ),
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.deepseek.api_key:
        logger.error("DEEPSEEK__API_KEY not set — extraction needs an LLM provider")
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
    logger.info("registered deepseek llm client")

    snapshot_path = settings.storage.data_dir / "state.json"
    repo = SnapshotRepository(snapshot_path=snapshot_path)
    logger.info("loaded SnapshotRepository at {}", snapshot_path)

    corpora = await repo.list_corpora()
    target = next((c for c in corpora if c.name == args.corpus_name), None)
    if target is None:
        logger.error(
            "corpus {!r} not found. Available: {}",
            args.corpus_name,
            [c.name for c in corpora],
        )
        return 3
    logger.info("target corpus: {} ({})", target.name, target.id)

    existing = await repo.list_variants(target.id)
    same_name = [v for v in existing if v.name == args.variant_name]
    if same_name and not args.force:
        logger.warning(
            "variant {!r} already exists ({}) — pass --force to rebuild",
            args.variant_name,
            same_name[0].id,
        )
        return 0

    docs = await repo.list_documents(target.id)
    if not docs:
        logger.error("corpus has no documents")
        return 4
    logger.info("corpus has {} documents", len(docs))

    docs_with_text: list[tuple[Document, str]] = []
    skipped = 0
    for d in docs:
        text = d.text or d.metadata.get("raw_text")
        if not text:
            skipped += 1
            continue
        docs_with_text.append((d, text))
    if skipped:
        logger.warning("skipping {} documents without text body", skipped)

    builder_params: dict = {
        "concurrency": args.concurrency,
        "max_chunks": args.max_chunks,
    }
    if args.chunk_size > 0:
        builder_params["chunk_size"] = args.chunk_size
    # Auto-attach the corpus schema (if committed via PUT /api/corpora/{id}/schema)
    # so the builder extracts against the typed ontology — same behavior as
    # the HTTP route. `--no-schema` lets the user force open-vocab mode for
    # comparison runs.
    if not args.no_schema:
        schema = target.metadata.get("schema")
        if schema:
            builder_params["schema"] = schema
            logger.info(
                "attached schema: {} entity_types, {} relation_types",
                len(schema.get("entity_types") or []),
                len(schema.get("relation_types") or []),
            )
    if args.builder == "microsoft":
        builder_params["extraction_max_gleanings"] = args.gleanings

    variant_id = new_id()
    logger.info(
        "starting build: builder={} clusterer={} variant_id={} params={}",
        args.builder,
        args.clusterer,
        variant_id,
        builder_params,
    )

    started = datetime.now(tz=timezone.utc)
    _, state = await run_build_pipeline(
        corpus_id=target.id,
        documents=docs_with_text,
        builder=args.builder,
        cleaner_chain=[],
        clusterer=args.clusterer,
        builder_params=builder_params,
        graph_variant_id=variant_id,
    )
    elapsed = (datetime.now(tz=timezone.utc) - started).total_seconds()

    layers_present = sorted({n.layer for n in state.nodes})
    variant = GraphVariant(
        id=variant_id,
        corpus_id=target.id,
        name=args.variant_name,
        status=GraphVariantStatus.READY,
        builder=args.builder,
        cleaner_chain=[],
        clusterer=args.clusterer,
        config={"builder_params": builder_params, "elapsed_s": round(elapsed, 1)},
        node_count=len(state.nodes),
        edge_count=len(state.edges),
        layers_present=list(layers_present),
        completed_at=datetime.now(tz=timezone.utc),
    )

    await repo.create_variant(variant, state)
    logger.info(
        "variant persisted: id={} nodes={} edges={} elapsed={:.1f}s",
        variant.id,
        variant.node_count,
        variant.edge_count,
        elapsed,
    )
    print(
        f"OK variant_id={variant.id} nodes={variant.node_count} "
        f"edges={variant.edge_count} elapsed={elapsed:.1f}s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
