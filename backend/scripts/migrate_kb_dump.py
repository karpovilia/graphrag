"""Migrate the corporate KB dump into the R2 domain model with WEEKLY
bi-temporal stamping so the Temporal Explorer (timeline / scrub / diff)
runs on real, evolving data.

Unlike `migrate_podcast.py` (which hand-builds a graph from parquet),
this script runs the live `run_build_pipeline` (ner_extraction builder →
threshold_prune cleaner → leiden clusterer) over one Document per dump
file, then stamps every node/edge with the ISO-week Monday it first
appears, so `materialize_at(t)` grows over time and `diff(week_a, week_b)`
yields born entities.

DUMP LAYOUT
    <dump>/<ISO-week>/<channel>/<name>.txt
    weeks  : 2025-W36 … 2026-W23   (format %G-W%V)
    channel: mattermost | telegram | calls

WEEKLY STAMPING (the point of this script)
    * chunk    node: tx_from = valid_from = Monday of its provenance doc's week
    * entity   node: tx_from = valid_from = MIN week over docs of its
                     MENTIONED_IN neighbours (week of first mention)
    * community node: MIN week over its member entities (via MEMBER_OF)
    * edge          : MIN week over its endpoint nodes (or its own
                      provenance.document_id week, when present)

RUN (dry-run validation, no persistence):
    uv run python -m scripts.migrate_kb_dump --dry-run --channels calls \
        --max-files-per-week 5 --weeks 2026-W20:2026-W23

Full persistent run writes to get_repository() (SnapshotRepository at
data/var/state.json, read by the live API) — pass real --channels and
omit --dry-run. Add --postgres to target PostgreSQL instead.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

# Plugins register themselves on import (decorator side-effects). The API
# does this in api/routes/strategies.py; a standalone script must do it too
# or the registry is empty and run_build_pipeline raises "unknown builder".
import api.strategies.builders  # noqa: F401
import api.strategies.cleaners  # noqa: F401
import api.strategies.clusterers  # noqa: F401
from api.domain.corpus import Corpus, Document
from api.domain.graph import EdgeType, GraphVariant, GraphVariantStatus, Layer
from api.domain.temporal import IngestionEvent
from api.domain.types import Id
from api.orchestrator import run_build_pipeline
from api.repository import InMemoryRepository, RepositoryProtocol
from api.strategies.state import GraphBuildState

CHANNELS = ("mattermost", "telegram", "calls")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dump",
        default="/home/ki/repos/kb/data/dump",
        help="Root dump dir holding <ISO-week>/<channel>/<name>.txt",
    )
    parser.add_argument(
        "--channels",
        default="calls",
        help="CSV of channels to ingest (subset of mattermost,telegram,calls)",
    )
    parser.add_argument(
        "--max-files-per-week",
        type=int,
        default=0,
        help="Cap files per (week, channel); 0 = no limit",
    )
    parser.add_argument(
        "--weeks",
        default=None,
        help="Inclusive ISO-week range 'START:END' e.g. 2026-W01:2026-W23 (default all)",
    )
    parser.add_argument("--corpus-name", default="KB Dump")
    parser.add_argument("--variant-name", default="kb-ner-leiden")
    parser.add_argument(
        "--prune-weight",
        type=float,
        default=0.0,
        help="threshold_prune weight cutoff; >0 drops weak co-mention edges (UI readability)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use InMemoryRepository, do not persist; only count + report",
    )
    parser.add_argument(
        "--postgres",
        action="store_true",
        help="Persist to PostgreSQL (overrides the on-disk snapshot repo)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# week helpers
# ---------------------------------------------------------------------------


def _week_monday(week: str) -> datetime:
    """'2026-W22' -> Monday 00:00:00 UTC of that ISO week."""
    year_s, wk_s = week.split("-W")
    return datetime.fromisocalendar(int(year_s), int(wk_s), 1).replace(
        tzinfo=timezone.utc
    )


def _enumerate_weeks(dump: Path, week_range: str | None) -> list[str]:
    weeks = [p.name for p in dump.iterdir() if p.is_dir() and "-W" in p.name]
    if week_range:
        start_s, end_s = week_range.split(":")
        lo, hi = _week_monday(start_s), _week_monday(end_s)
        weeks = [w for w in weeks if lo <= _week_monday(w) <= hi]
    return sorted(weeks, key=_week_monday)


# ---------------------------------------------------------------------------
# document collection
# ---------------------------------------------------------------------------


# A message block header: "YYYY-MM-DD HH:MM:SS <author>" at line start.
_MSG_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ", re.MULTILINE)


def _collect_documents(
    dump: Path,
    *,
    corpus_id: Id,
    weeks: list[str],
    channels: list[str],
    max_files_per_week: int,
) -> tuple[list[Document], dict[Id, datetime], dict[str, int]]:
    """Build one Document per .txt file. Returns the docs, a
    document.id -> week-Monday map for weekly stamping, and a
    week -> message-count map for the scrubber activity histogram."""

    documents: list[Document] = []
    doc_week: dict[Id, datetime] = {}
    week_counts: dict[str, int] = {}

    all_channels = ("mattermost", "telegram", "calls")
    for week in weeks:
        monday = _week_monday(week)
        monday_iso = monday.isoformat()

        # Activity histogram = every message across ALL channels this week,
        # independent of the (small) build slice — so the scrubber shows true
        # weekly volume even when the graph is built from a sample.
        total = 0
        for channel in all_channels:
            chan_dir = dump / week / channel
            if not chan_dir.is_dir():
                continue
            for path in sorted(chan_dir.glob("*.txt")):
                try:
                    total += len(_MSG_RE.findall(path.read_text(encoding="utf-8", errors="replace")))
                except OSError:  # pragma: no cover - defensive
                    pass
        week_counts[week] = total

        # Build documents from the selected channels (capped).
        for channel in channels:
            chan_dir = dump / week / channel
            if not chan_dir.is_dir():
                continue
            files = sorted(chan_dir.glob("*.txt"))
            if max_files_per_week > 0:
                files = files[:max_files_per_week]
            for path in files:
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:  # pragma: no cover - defensive
                    logger.warning("skip {}: {}", path, exc)
                    continue
                if not text.strip():
                    continue
                doc = Document(
                    corpus_id=corpus_id,
                    title=f"{week}/{channel}/{path.name}",
                    language="ru",
                    char_length=len(text),
                    sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    text=text,
                    metadata={
                        "week": week,
                        "channel": channel,
                        "source": path.name,
                        "event_time": monday_iso,
                    },
                )
                documents.append(doc)
                doc_week[doc.id] = monday
    return documents, doc_week, week_counts


# ---------------------------------------------------------------------------
# weekly bi-temporal stamping
# ---------------------------------------------------------------------------


def _stamp_weekly(
    state: GraphBuildState,
    doc_week: dict[Id, datetime],
) -> tuple[int, dict[str, int]]:
    """In-place bi-temporal stamping by week-Monday.

    tx_from (existence / cumulative knowledge) = first week seen, on every
    node/edge — this drives the "graph grows over time" scrub. valid time
    (real-world extent) takes the form that fits the fact:
      - chunk (a dated message) and mention/relation observations → POINT
        (valid_from == valid_to == week);
      - entity / community / membership → OPEN END (valid_from = first week,
        valid_to = None — known/holds since first seen).
    (Timeless (None, None) is reserved for definitional facts an LLM
    extractor would mark; the structural NER pass emits none.)

    Returns (entities_without_week, born-histogram by week-iso)."""

    nodes_by_id = {n.id: n for n in state.nodes}

    # chunk node -> its week (from provenance document_id)
    chunk_week: dict[Id, datetime] = {}
    for n in state.nodes:
        if n.layer == Layer.CHUNK:
            wk = None
            for prov in n.provenance:
                wk = doc_week.get(prov.document_id)
                if wk is not None:
                    break
            if wk is not None:
                chunk_week[n.id] = wk
                # chunk = a dated message block → point event in valid time
                n.tx_from = wk
                n.valid_from = n.valid_to = wk

    # entity node -> MIN week over MENTIONED_IN-linked chunks.
    # MENTIONED_IN is emitted entity -> chunk; we also accept either
    # direction defensively. Edge provenance carries the document_id too,
    # which is the most direct anchor.
    entity_week: dict[Id, datetime] = {}
    for e in state.edges:
        if e.type != EdgeType.MENTIONED_IN:
            continue
        # which endpoint is the entity, which is the chunk
        src, tgt = nodes_by_id.get(e.source_node_id), nodes_by_id.get(e.target_node_id)
        entity_id = chunk_id = None
        if src is not None and src.layer == Layer.ENTITY:
            entity_id = src.id
        if tgt is not None and tgt.layer == Layer.ENTITY:
            entity_id = tgt.id
        if src is not None and src.layer == Layer.CHUNK:
            chunk_id = src.id
        if tgt is not None and tgt.layer == Layer.CHUNK:
            chunk_id = tgt.id
        # candidate week: edge provenance doc, else the chunk's week
        wk = None
        for prov in e.provenance:
            wk = doc_week.get(prov.document_id)
            if wk is not None:
                break
        if wk is None and chunk_id is not None:
            wk = chunk_week.get(chunk_id)
        if entity_id is not None and wk is not None:
            cur = entity_week.get(entity_id)
            if cur is None or wk < cur:
                entity_week[entity_id] = wk

    entities_without_week = 0
    for n in state.nodes:
        if n.layer != Layer.ENTITY:
            continue
        wk = entity_week.get(n.id)
        if wk is None:
            entities_without_week += 1
            continue
        n.tx_from = n.valid_from = wk

    # community node -> MIN week over member entities (via MEMBER_OF).
    # materialize_communities emits entity -> community.
    community_week: dict[Id, datetime] = {}
    for e in state.edges:
        if e.type != EdgeType.MEMBER_OF:
            continue
        src, tgt = nodes_by_id.get(e.source_node_id), nodes_by_id.get(e.target_node_id)
        comm_id = entity_id = None
        for node in (src, tgt):
            if node is None:
                continue
            if node.layer == Layer.COMMUNITY:
                comm_id = node.id
            elif node.layer == Layer.ENTITY:
                entity_id = node.id
        if comm_id is None or entity_id is None:
            continue
        wk = entity_week.get(entity_id)
        if wk is None:
            continue
        cur = community_week.get(comm_id)
        if cur is None or wk < cur:
            community_week[comm_id] = wk

    for n in state.nodes:
        if n.layer != Layer.COMMUNITY:
            continue
        wk = community_week.get(n.id)
        if wk is not None:
            n.tx_from = n.valid_from = wk

    # build a combined node -> week lookup for edge stamping
    node_week: dict[Id, datetime] = {}
    node_week.update(chunk_week)
    node_week.update(entity_week)
    node_week.update(community_week)

    # edges: own provenance doc week if present, else MIN over endpoints.
    for e in state.edges:
        wk = None
        for prov in e.provenance:
            cand = doc_week.get(prov.document_id)
            if cand is not None and (wk is None or cand < wk):
                wk = cand
        if wk is None:
            for endpoint in (e.source_node_id, e.target_node_id):
                cand = node_week.get(endpoint)
                if cand is not None and (wk is None or cand < wk):
                    wk = cand
        if wk is not None:
            e.tx_from = e.valid_from = wk
            # co-mention / mention observations are point events; membership
            # is an open-ended interval (entity belongs since first seen).
            if e.type in (EdgeType.MENTIONED_IN, EdgeType.ENTITY_RELATION):
                e.valid_to = wk

    # born histogram: nodes whose tx_from == each week
    born = Counter()
    for n in state.nodes:
        if n.tx_from is not None:
            born[_iso_of(n.tx_from)] += 1
    return entities_without_week, dict(born)


def _iso_of(dt: datetime) -> str:
    return f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}"


# ---------------------------------------------------------------------------
# repository
# ---------------------------------------------------------------------------


async def _make_repo(*, dry_run: bool, use_postgres: bool) -> RepositoryProtocol:
    if dry_run:
        logger.info("dry-run: InMemoryRepository (no persistence)")
        return InMemoryRepository()
    if use_postgres:
        from api.db.engine import get_sessionmaker
        from api.repository.postgres import PostgresRepository

        logger.info("persisting to PostgresRepository")
        return PostgresRepository(sessionmaker=get_sessionmaker())
    # Live local repo read by the API — SnapshotRepository at data/var/state.json
    from api.runtime import get_repository

    repo = get_repository()
    logger.info("persisting to {}", type(repo).__name__)
    return repo


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def main() -> None:
    args = _parse_args()
    dump = Path(args.dump)
    if not dump.is_dir():
        raise SystemExit(f"dump dir not found: {dump}")

    channels = [c.strip() for c in args.channels.split(",") if c.strip()]
    bad = [c for c in channels if c not in CHANNELS]
    if bad:
        raise SystemExit(f"unknown channel(s) {bad}; valid: {CHANNELS}")

    weeks = _enumerate_weeks(dump, args.weeks)
    if not weeks:
        raise SystemExit("no weeks matched the selection")
    logger.info("weeks={}..{} ({} total) channels={}", weeks[0], weeks[-1], len(weeks), channels)

    repo = await _make_repo(dry_run=args.dry_run, use_postgres=args.postgres)

    corpus = Corpus(
        name=args.corpus_name,
        language="ru",
        metadata={"source": "kb_dump", "channels": channels},
    )
    corpus = await repo.create_corpus(corpus)

    documents, doc_week, week_counts = _collect_documents(
        dump,
        corpus_id=corpus.id,
        weeks=weeks,
        channels=channels,
        max_files_per_week=args.max_files_per_week,
    )
    if not documents:
        raise SystemExit("no documents collected — check channels/weeks")
    for doc in documents:
        await repo.create_document(doc)
    logger.info("collected {} documents across {} weeks", len(documents), len(weeks))

    # ---- build the graph once ----
    t0 = time.perf_counter()
    variant_id, state = await run_build_pipeline(
        corpus_id=corpus.id,
        documents=[(doc, doc.text or "") for doc in documents],
        builder="ner_extraction",
        cleaner_chain=["threshold_prune"],
        clusterer="leiden",
        cleaner_params={"threshold_prune": {"weight_threshold": args.prune_weight}},
    )
    elapsed = time.perf_counter() - t0
    logger.info(
        "built variant {} in {:.1f}s — {} nodes, {} edges",
        variant_id,
        elapsed,
        len(state.nodes),
        len(state.edges),
    )

    # ---- weekly bi-temporal stamping ----
    entities_without_week, born_hist = _stamp_weekly(state, doc_week)

    # ---- persist variant (mirrors POST /api/corpora/{id}/graphs) ----
    layers_present = sorted(
        {n.layer for n in state.nodes}, key=lambda layer: layer.value
    )
    variant = GraphVariant(
        id=variant_id,
        corpus_id=corpus.id,
        name=args.variant_name,
        status=GraphVariantStatus.READY,
        builder="ner_extraction",
        cleaner_chain=["threshold_prune"],
        clusterer="leiden",
        config={
            "builder_params": {},
            "cleaner_params": {},
            "clusterer_params": {},
            "migrated_from": "kb_dump",
            "weeks": [weeks[0], weeks[-1]],
            "channels": channels,
        },
        seed=None,
        node_count=len(state.nodes),
        edge_count=len(state.edges),
        layers_present=layers_present,
        completed_at=datetime.now(tz=timezone.utc),
    )
    persisted = await repo.create_variant(variant, state)

    # ---- one IngestionEvent per week ----
    for week in weeks:
        monday = _week_monday(week)
        await repo.create_ingestion_event(
            IngestionEvent(
                corpus_id=corpus.id,
                graph_variant_id=persisted.id,
                label=week,
                event_time=monday,
                ingested_at=monday,
                kind="week",
                event_count=week_counts.get(week, 0),
            )
        )

    # ---- report ----
    nodes_by_layer = Counter(n.layer.value for n in state.nodes)
    edges_by_type = Counter(e.type.value for e in state.edges)
    born_weeks_nonzero = sum(1 for v in born_hist.values() if v > 0)

    print("=" * 60)
    print(f"corpus_id   = {corpus.id}")
    print(f"variant_id  = {persisted.id}")
    print(f"dry_run     = {args.dry_run}  repo={type(repo).__name__}")
    print(f"weeks       = {len(weeks)} ({weeks[0]}..{weeks[-1]})")
    print(f"documents   = {len(documents)}")
    print(f"nodes       = {len(state.nodes)}  {dict(nodes_by_layer)}")
    print(f"edges       = {len(state.edges)}  {dict(edges_by_type)}")
    print(f"entities w/o week = {entities_without_week}")
    print(f"born-weeks nonzero = {born_weeks_nonzero}")
    print(f"build elapsed = {elapsed:.1f}s")
    print("-" * 60)
    print("born-node histogram (tx_from week -> count):")
    for wk in sorted(born_hist, key=_week_monday):
        bar = "#" * min(60, born_hist[wk])
        print(f"  {wk}: {born_hist[wk]:5d} {bar}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
