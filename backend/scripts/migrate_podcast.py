"""Migrate the bundled HSE podcast parquets into the R2 domain model.

Phase 7 demo-readiness. Reads the artifact directory in
`backend/data/yandex5_podcast/` and creates one Corpus, one Document,
one GraphVariant with CHUNK + ENTITY + COMMUNITY layers and the
edges between them.

The Microsoft GraphRAG parquet bundle has historic schema:
- create_final_documents.parquet           — 1 row, raw_content
- create_final_text_units.parquet          — 97 chunks
- create_summarized_entities.parquet       — single GraphML blob with
                                             nodes + entity_relations
- create_final_communities.parquet         — 28 communities
- create_final_relationships.parquet       — 169 entity-relation edges
- create_final_nodes/entities/community_reports.parquet — corrupted in
                                             the bundle we ship; we
                                             synthesize empty summaries.

Run:
    uv run python -m scripts.migrate_podcast --data-dir data/yandex5_podcast
add `--postgres` to persist to PG (Alembic-migrated DB must be live);
without the flag the script writes to InMemoryRepository and is mostly
useful as a smoke that the parquets parse correctly.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

import pandas as pd
from loguru import logger

from api.domain.corpus import Corpus, Document
from api.domain.graph import Edge, EdgeType, GraphVariant, GraphVariantStatus, Layer, Node
from api.domain.types import Id, Provenance, new_id
from api.repository import InMemoryRepository, RepositoryProtocol
from api.strategies.state import GraphBuildState

GRAPHML_NS = "{http://graphml.graphdrawing.org/xmlns}"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir",
        default="data/yandex5_podcast",
        help="Directory holding create_final_*.parquet files",
    )
    parser.add_argument(
        "--postgres",
        action="store_true",
        help="Persist to PostgreSQL via PostgresRepository (otherwise InMemoryRepository, no-op write)",
    )
    parser.add_argument(
        "--corpus-name",
        default="HSE Podcast",
        help="Corpus.name surfaced in the wizard",
    )
    parser.add_argument(
        "--variant-name",
        default="microsoft-graphrag-yandex5",
        help="GraphVariant.name to record",
    )
    args = parser.parse_args()

    repo = await _make_repo(use_postgres=args.postgres)
    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        raise SystemExit(f"data dir not found: {data_dir}")

    corpus, document = await _create_corpus_and_document(repo, data_dir, args.corpus_name)
    state, variant = _build_variant(
        data_dir,
        corpus_id=corpus.id,
        document_id=document.id,
        variant_name=args.variant_name,
    )
    persisted = await repo.create_variant(variant, state)

    logger.info(
        "migrated: corpus={} variant={} nodes={} edges={}",
        corpus.name,
        persisted.name,
        len(state.nodes),
        len(state.edges),
    )
    print(
        f"corpus_id={corpus.id} variant_id={persisted.id} "
        f"nodes={len(state.nodes)} edges={len(state.edges)}",
    )


async def _make_repo(*, use_postgres: bool) -> RepositoryProtocol:
    if not use_postgres:
        logger.info("using InMemoryRepository (no persistence)")
        return InMemoryRepository()
    # Lazy-import the PG path so the script still runs without asyncpg
    # configured for the in-memory dry run.
    from api.config import get_settings
    from api.db.engine import get_sessionmaker
    from api.repository.postgres import PostgresRepository

    s = get_settings()
    repo = PostgresRepository(sessionmaker=get_sessionmaker())
    logger.info("using PostgresRepository against {}", s.postgres.host)
    return repo


async def _create_corpus_and_document(
    repo: RepositoryProtocol,
    data_dir: Path,
    corpus_name: str,
) -> tuple[Corpus, Document]:
    docs_df = pd.read_parquet(data_dir / "create_final_documents.parquet")
    if docs_df.empty:
        raise SystemExit("create_final_documents.parquet is empty")
    row = docs_df.iloc[0]
    raw_text = str(row.get("raw_content") or "")
    title = str(row.get("title") or "podcast")

    corpus = Corpus(name=corpus_name, language="ru")
    corpus = await repo.create_corpus(corpus)

    document = Document(
        corpus_id=corpus.id,
        title=title,
        language="ru",
        char_length=len(raw_text),
        sha256="0" * 64,  # parquet bundle didn't carry one; keeping field non-null
        metadata={"raw_text": raw_text, "legacy_id": str(row["id"])},
    )
    document = await repo.create_document(document)
    return corpus, document


def _build_variant(
    data_dir: Path,
    *,
    corpus_id: Id,
    document_id: Id,
    variant_name: str,
) -> tuple[GraphBuildState, GraphVariant]:
    variant_id = new_id()

    chunks_df = pd.read_parquet(data_dir / "create_final_text_units.parquet")
    rels_df = pd.read_parquet(data_dir / "create_final_relationships.parquet")
    comms_df = pd.read_parquet(data_dir / "create_final_communities.parquet")
    entity_graph_xml = pd.read_parquet(data_dir / "create_summarized_entities.parquet").iloc[0][
        "entity_graph"
    ]

    chunk_nodes, chunk_id_map = _build_chunk_nodes(
        chunks_df, variant_id=variant_id, document_id=document_id
    )
    entity_nodes, entity_name_map = _build_entity_nodes(
        entity_graph_xml, variant_id=variant_id
    )
    relation_edges, mention_edges = _build_entity_edges(
        rels_df,
        variant_id=variant_id,
        entity_name_map=entity_name_map,
        chunk_id_map=chunk_id_map,
    )
    community_nodes, member_edges = _build_communities(
        comms_df,
        variant_id=variant_id,
        rels_df=rels_df,
        relation_edges=relation_edges,
        entity_name_map=entity_name_map,
    )

    nodes = chunk_nodes + entity_nodes + community_nodes
    edges = relation_edges + mention_edges + member_edges
    state = GraphBuildState(nodes=nodes, edges=edges)

    variant = GraphVariant(
        id=variant_id,
        corpus_id=corpus_id,
        name=variant_name,
        status=GraphVariantStatus.READY,
        builder="microsoft",
        cleaner_chain=[],
        clusterer="leiden",
        config={"migrated_from": "data/yandex5_podcast"},
        seed=None,
        node_count=len(nodes),
        edge_count=len(edges),
        layers_present=[Layer.CHUNK, Layer.ENTITY, Layer.COMMUNITY],
    )
    return state, variant


def _build_chunk_nodes(
    df: pd.DataFrame,
    *,
    variant_id: Id,
    document_id: Id,
) -> tuple[list[Node], dict[str, Id]]:
    """legacy_id (Microsoft chunk hash) → R2 Node.id."""

    out: list[Node] = []
    id_map: dict[str, Id] = {}
    cursor = 0
    for _, row in df.iterrows():
        text = str(row.get("text") or "")
        legacy_id = str(row["id"])
        node = Node(
            graph_variant_id=variant_id,
            layer=Layer.CHUNK,
            type="CHUNK",
            granularity=0,
            name=f"chunk@{cursor}",
            attributes={
                "char_start": cursor,
                "char_end": cursor + len(text),
                "n_tokens": int(row.get("n_tokens") or 0),
                "legacy_id": legacy_id,
            },
            provenance=[
                Provenance(
                    document_id=document_id,
                    span_start=cursor,
                    span_end=max(cursor + 1, cursor + len(text)),
                )
            ],
        )
        cursor += len(text) + 1
        out.append(node)
        id_map[legacy_id] = node.id
    return out, id_map


def _build_entity_nodes(
    entity_graph_xml: str,
    *,
    variant_id: Id,
) -> tuple[list[Node], dict[str, Id]]:
    """name (graphml node id) → R2 Node.id. Names appear verbatim in
    Microsoft GraphRAG relationships' source/target columns, so the
    map is keyed on the raw name string."""

    root = ET.parse(io.StringIO(entity_graph_xml)).getroot()
    graph = root.find(f"{GRAPHML_NS}graph")
    if graph is None:
        raise SystemExit("entity_graph: <graph> element missing")

    keys = {
        elem.get("id"): elem.get("attr.name")
        for elem in root.findall(f"{GRAPHML_NS}key")
    }

    out: list[Node] = []
    name_map: dict[str, Id] = {}
    for node_elem in graph.findall(f"{GRAPHML_NS}node"):
        name = node_elem.get("id") or ""
        attrs: dict[str, str] = {}
        for data in node_elem.findall(f"{GRAPHML_NS}data"):
            attr_name = keys.get(data.get("key", ""))
            if attr_name and data.text:
                attrs[attr_name] = data.text

        node = Node(
            graph_variant_id=variant_id,
            layer=Layer.ENTITY,
            type=str(attrs.get("type") or "GENERIC"),
            granularity=1,
            name=name,
            summary=attrs.get("description"),
            attributes={"legacy_human_readable_id": attrs.get("human_readable_id")},
        )
        out.append(node)
        name_map[name] = node.id
    return out, name_map


def _build_entity_edges(
    rels_df: pd.DataFrame,
    *,
    variant_id: Id,
    entity_name_map: dict[str, Id],
    chunk_id_map: dict[str, Id],
) -> tuple[list[Edge], list[Edge]]:
    relation_edges: list[Edge] = []
    mention_edges: list[Edge] = []
    seen_mentions: set[tuple[Id, Id]] = set()

    for _, row in rels_df.iterrows():
        src_name = str(row["source"])
        tgt_name = str(row["target"])
        src_id = entity_name_map.get(src_name)
        tgt_id = entity_name_map.get(tgt_name)
        if src_id is None or tgt_id is None:
            continue
        weight = float(row.get("weight") or 0.0) or None
        relation_edges.append(
            Edge(
                graph_variant_id=variant_id,
                type=EdgeType.ENTITY_RELATION,
                source_node_id=src_id,
                target_node_id=tgt_id,
                weight=weight,
                relation="microsoft_graphrag",
                explanation=str(row.get("description") or ""),
            )
        )
        # Mention edges: every text_unit_id linked to either endpoint.
        text_units = row.get("text_unit_ids")
        if text_units is None:
            text_units = []
        for legacy_chunk_id in text_units:
            chunk_id = chunk_id_map.get(str(legacy_chunk_id))
            if chunk_id is None:
                continue
            for entity_id in (src_id, tgt_id):
                key = (entity_id, chunk_id)
                if key in seen_mentions:
                    continue
                seen_mentions.add(key)
                mention_edges.append(
                    Edge(
                        graph_variant_id=variant_id,
                        type=EdgeType.MENTIONED_IN,
                        source_node_id=entity_id,
                        target_node_id=chunk_id,
                    )
                )
    return relation_edges, mention_edges


def _build_communities(
    comms_df: pd.DataFrame,
    *,
    variant_id: Id,
    rels_df: pd.DataFrame,
    relation_edges: list[Edge],
    entity_name_map: dict[str, Id],
) -> tuple[list[Node], list[Edge]]:
    """Each community lists relationship_ids; we map back to entity ids
    via rels_df[id] and emit MEMBER_OF edges from each entity to its
    community."""

    rel_id_to_entities: dict[str, set[Id]] = defaultdict(set)
    for _, row in rels_df.iterrows():
        rel_id = str(row["id"])
        for name in (row["source"], row["target"]):
            entity_id = entity_name_map.get(str(name))
            if entity_id is not None:
                rel_id_to_entities[rel_id].add(entity_id)

    community_nodes: list[Node] = []
    member_edges: list[Edge] = []
    for _, row in comms_df.iterrows():
        title = str(row.get("title") or f"Community {row['id']}")
        level = int(row.get("level") or 0)
        community_node = Node(
            graph_variant_id=variant_id,
            layer=Layer.COMMUNITY,
            type="COMMUNITY",
            granularity=2 + level,
            name=title,
            attributes={"legacy_id": str(row["id"]), "level": level},
        )
        community_nodes.append(community_node)
        member_ids: set[Id] = set()
        rel_ids = row.get("relationship_ids")
        if rel_ids is None:
            rel_ids = []
        for rel_id in rel_ids:
            member_ids.update(rel_id_to_entities.get(str(rel_id), set()))
        for member_id in member_ids:
            member_edges.append(
                Edge(
                    graph_variant_id=variant_id,
                    type=EdgeType.MEMBER_OF,
                    source_node_id=member_id,
                    target_node_id=community_node.id,
                )
            )
    return community_nodes, member_edges


if __name__ == "__main__":
    asyncio.run(main())
