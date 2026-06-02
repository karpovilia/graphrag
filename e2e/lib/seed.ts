// Seeds the InMemory backend with a fresh HSE-podcast fixture and
// returns the corpus + variant ids the spec navigates to. Each test
// run is independent; we don't try to reuse state between specs.
//
// R2 §2 (bi-temporal) extension: on top of the original corpus/variant
// seed, we POST a small time-series of IngestionEvents (podcast
// episodes) and auto-invalidate one edge so the temporal.spec.ts flows
// (timeline scrub, axis re-sort, diff, revert, latency) have real data.
//
// The whole temporal block is best-effort and guarded: a single
// `POST /api/corpora/{cid}/ingestion-events` test/seed endpoint is the
// only backend addition the seed depends on. On an older backend that
// route 404s — we then leave `episode_events=[]` so the specs
// `test.skip` instead of failing, preserving the existing demo.spec
// runs. We never throw out of the temporal block.

import fs from "node:fs/promises";
import path from "node:path";

export type EpisodeEvent = {
  id: string;
  label: string;
  event_time: string; // T  — episode/publication date
  ingested_at: string; // T' — build/ingest time
};

export type SeedResult = {
  run_id: string;
  corpus_id: string;
  corpus_name: string;
  variant_leiden_id: string;
  variant_leiden_name: string;
  variant_bare_id: string;
  variant_bare_name: string;

  // Reused by the query-delta spec (§2.2). Kept here so spec and seed
  // agree on the exact query string the MoE runs against.
  moe_query: string;

  // --- R2 §2 temporal fixture (empty on older backends → specs skip) ---
  episode_events: EpisodeEvent[];
  // Two ISO instants on the tx axis bracketing the auto-invalidation.
  // Used by diff(tx_a, tx_b, axis=tx) in §2.4 (the invalidated edge is
  // alive at tx_a and dead by tx_b → it lands in diff.invalidated).
  tx_a: string | null;
  tx_b: string | null;
  // §2.1 compression: an instant *before* the first ingest, when zero
  // facts are born. materialize_at(tx_pre) yields an empty graph while
  // materialize_at(tx_b) yields the full one — a true, observable
  // temporal compression. (Distinct from tx_a, which must sit *after*
  // the first ingest so §2.4's invalidated edge stays in the diff
  // window — the backend stamps every node's tx_from at the first
  // event's ingested_at, so an instant between episodes is NOT enough to
  // compress; see backend test_backfill_is_idempotent_and_staggered.)
  tx_pre: string | null;
  // The auto-invalidated edge and the variant version *after* the
  // auto-invalidation journal append landed (revert expected_version).
  invalidated_edge_id: string | null;
  invalidated_edge_version: number | null;
};

export async function seed(backendUrl: string): Promise<SeedResult> {
  // Unique per-run suffix so the spec can target *its* corpus / variants
  // even when the InMemoryRepository accumulates rows from previous
  // demo runs. Using time + random — collisions are not an issue at
  // this scale but it's defensive.
  const run_id = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
  const corpus_name = `HSE Podcast (e2e ${run_id})`;
  const variant_leiden_name = `ner-leiden-${run_id}`;
  const variant_bare_name = `ner-bare-${run_id}`;
  const moe_query = "Кто работает в ВШЭ?";

  const text = await loadPodcastText();

  const corpus = await postJson<{ id: string }>(
    `${backendUrl}/api/corpora`,
    {
      name: corpus_name,
      description: `seeded by e2e/lib/seed.ts run=${run_id}`,
      language: "ru",
    },
  );

  await postJson(
    `${backendUrl}/api/corpora/${corpus.id}/documents`,
    { title: "podcast.txt", text, language: "ru" },
  );

  const leiden = await postJson<{ id: string }>(
    `${backendUrl}/api/corpora/${corpus.id}/graphs`,
    {
      name: variant_leiden_name,
      builder: "ner_extraction",
      cleaner_chain: ["threshold_prune"],
      cleaner_params: { threshold_prune: { weight_threshold: 1.0 } },
      clusterer: "leiden",
    },
  );

  const bare = await postJson<{ id: string }>(
    `${backendUrl}/api/corpora/${corpus.id}/graphs`,
    {
      name: variant_bare_name,
      builder: "ner_extraction",
    },
  );

  // Seed a couple of agent runs so the suggestions sidebar has rows
  // even when the spec doesn't trigger them itself.
  await postJson(
    `${backendUrl}/api/graphs/${leiden.id}/agents/low_confidence_triplet/run`,
    { params: { weight_threshold: 5.0, max_suggestions: 30 } },
  );

  // --- R2 §2 temporal fixture --------------------------------------
  // Best-effort. Any failure (e.g. the ingestion-events endpoint is
  // absent on an older backend) leaves the temporal fields at their
  // empty defaults so the specs `test.skip`.
  let episode_events: EpisodeEvent[] = [];
  let tx_a: string | null = null;
  let tx_b: string | null = null;
  let tx_pre: string | null = null;
  let invalidated_edge_id: string | null = null;
  let invalidated_edge_version: number | null = null;

  try {
    const temporal = await seedTemporal(backendUrl, corpus.id, leiden.id);
    episode_events = temporal.episode_events;
    tx_a = temporal.tx_a;
    tx_b = temporal.tx_b;
    tx_pre = temporal.tx_pre;
    invalidated_edge_id = temporal.invalidated_edge_id;
    invalidated_edge_version = temporal.invalidated_edge_version;
  } catch (err) {
    // Never throw: preserve current demo.spec runs. The temporal specs
    // gate on episode_events.length / invalidated_edge_id and skip.
    // eslint-disable-next-line no-console
    console.warn(
      `[seed] temporal block skipped (older backend or transient error): ${
        (err as Error).message
      }`,
    );
    episode_events = [];
  }

  return {
    run_id,
    corpus_id: corpus.id,
    corpus_name,
    variant_leiden_id: leiden.id,
    variant_leiden_name,
    variant_bare_id: bare.id,
    variant_bare_name,
    moe_query,
    episode_events,
    tx_a,
    tx_b,
    tx_pre,
    invalidated_edge_id,
    invalidated_edge_version,
  };
}

type TemporalSeed = {
  episode_events: EpisodeEvent[];
  tx_a: string | null;
  tx_b: string | null;
  tx_pre: string | null;
  invalidated_edge_id: string | null;
  invalidated_edge_version: number | null;
};

// Builds the episode time-series + one auto-invalidation. Throws if the
// ingestion-events endpoint is missing (caught by the caller → skip).
async function seedTemporal(
  backendUrl: string,
  corpusId: string,
  leidenId: string,
): Promise<TemporalSeed> {
  // Monotonic event_time (T): Эпизод 1..4 published in order.
  // ingested_at (T'): mostly monotonic, but Эпизод 3 is *back-dated* —
  // published earlier (event_time) than Эпизод 2/4 but ingested LAST.
  // This makes axis='tx' (sort by T') and axis='valid' (sort by T)
  // produce observably different orderings, which the AxisToggle spec
  // (§2.1 T vs T′) asserts. Concretely:
  //   label   event_time(T)         ingested_at(T')
  //   Эп.1     2024-01-10           2024-01-12   (idx 0 both axes)
  //   Эп.2     2024-02-10           2024-02-12
  //   Эп.3     2024-03-10           2024-05-20   ← back-dated: ingested last
  //   Эп.4     2024-04-10           2024-04-12
  // valid order: 1,2,3,4 ; tx order: 1,2,4,3 → Эп.3 moves. ✓
  const episodes: Array<{
    label: string;
    event_time: string;
    ingested_at: string;
  }> = [
    {
      label: "Эпизод 1 (ВШЭ)",
      event_time: "2024-01-10T00:00:00Z",
      ingested_at: "2024-01-12T00:00:00Z",
    },
    {
      label: "Эпизод 2 (ВШЭ)",
      event_time: "2024-02-10T00:00:00Z",
      ingested_at: "2024-02-12T00:00:00Z",
    },
    {
      label: "Эпизод 3 (ВШЭ)",
      event_time: "2024-03-10T00:00:00Z",
      ingested_at: "2024-05-20T00:00:00Z", // back-dated: published 3rd, ingested last
    },
    {
      label: "Эпизод 4 (ВШЭ)",
      event_time: "2024-04-10T00:00:00Z",
      ingested_at: "2024-04-12T00:00:00Z",
    },
  ];

  const created: EpisodeEvent[] = [];
  for (const ep of episodes) {
    // The seed-friendly endpoint just calls repo.create_ingestion_event
    // (no LLM, no build) and, behind the same POST, backfills tx_from on
    // the leiden variant's nodes/edges to the median ingested_at when
    // previously null (idempotent) so materialize_at(t, axis=tx) actually
    // compresses the visible graph for t between episodes.
    const ev = await postJson<{ id: string }>(
      `${backendUrl}/api/corpora/${corpusId}/ingestion-events`,
      {
        label: ep.label,
        event_time: ep.event_time,
        ingested_at: ep.ingested_at,
        graph_variant_id: leidenId,
        kind: "episode",
      },
    );
    created.push({
      id: ev.id,
      label: ep.label,
      event_time: ep.event_time,
      ingested_at: ep.ingested_at,
    });
  }

  // tx_a = just after Эпизод 1's ingest; tx_b = just after the last
  // ingest (Эп.3, the back-dated one, ingested 2024-05-20). diff(tx_a,
  // tx_b, axis=tx) must yield non-empty born + the invalidated edge.
  const sortedByTx = [...created].sort(
    (a, b) => Date.parse(a.ingested_at) - Date.parse(b.ingested_at),
  );
  const first = sortedByTx[0];
  const last = sortedByTx[sortedByTx.length - 1];
  const tx_a = plusOneSecond(first.ingested_at);
  const tx_b = plusOneSecond(last.ingested_at);
  // One second *before* the first ingest: nothing is born yet.
  const tx_pre = new Date(Date.parse(first.ingested_at) - 1000).toISOString();

  // --- one auto EdgeInvalidation via the journal API ---------------
  // Read the variant's current version and first edge, then DELETE_EDGE
  // with a reason. The DELETE_EDGE-with-reason path stamps tx_to and an
  // auto invalidation (auto=true, reason set, ingestion_event_id linked
  // when the backend supports it), so the edge shows in diff.invalidated
  // and is revert-eligible.
  let invalidated_edge_id: string | null = null;
  let invalidated_edge_version: number | null = null;

  const edges = await getJson<Array<{ id: string }>>(
    `${backendUrl}/api/graphs/${leidenId}/edges?limit=1`,
  );
  if (edges.length > 0) {
    const edgeId = edges[0].id;
    const variant = await getJson<{ version: number }>(
      `${backendUrl}/api/graphs/${leidenId}`,
    );
    const episode3 = created.find((e) => e.label.startsWith("Эпизод 3"));
    const result = await postJson<{ variant: { version: number } }>(
      `${backendUrl}/api/graphs/${leidenId}/journal`,
      {
        op: "delete_edge",
        payload: {
          edge_id: edgeId,
          reason: "superseded by Эпизод 3 re-extraction",
          ...(episode3 ? { ingestion_event_id: episode3.id } : {}),
        },
        expected_version: variant.version,
        actor: "agent:ingestion",
      },
    );
    invalidated_edge_id = edgeId;
    invalidated_edge_version = result.variant.version;
  }

  return {
    episode_events: created,
    tx_a,
    tx_b,
    tx_pre,
    invalidated_edge_id,
    invalidated_edge_version,
  };
}

function plusOneSecond(iso: string): string {
  return new Date(Date.parse(iso) + 1000).toISOString();
}

async function loadPodcastText(): Promise<string> {
  // Prefer the bundled parquet's raw_content; fall back to a short
  // synthetic snippet so the spec can run anywhere the bundled data
  // isn't present.
  const dataPath = path.resolve(
    process.cwd(),
    "..",
    "backend",
    "data",
    "yandex5_podcast",
    "raw_content.txt",
  );
  try {
    return await fs.readFile(dataPath, "utf-8");
  } catch {
    // Heavier-than-needed but enough text for natasha to find ~5+
    // entities so the leiden+threshold variant has something to cluster.
    return [
      "Иванов Иван Иванович работает в Высшей школе экономики (ВШЭ).",
      "Иванов И.И. руководит лабораторией обработки естественного языка.",
      "Петров А.С. — коллега Иванова И.И. в той же лаборатории.",
      "Сидоров читает лекции в МГУ, был в НИУ ВШЭ ассистентом.",
      "Иван Иванов выступал на конференции SIGIR в Мельбурне.",
      "Лаборатория сотрудничает с Институтом системного программирования РАН.",
    ].join(" ");
  }
}

async function postJson<T = unknown>(url: string, body: unknown): Promise<T> {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const txt = await resp.text();
    throw new Error(`POST ${url} → ${resp.status}: ${txt}`);
  }
  return (await resp.json()) as T;
}

async function getJson<T = unknown>(url: string): Promise<T> {
  const resp = await fetch(url, {
    method: "GET",
    headers: { accept: "application/json" },
  });
  if (!resp.ok) {
    const txt = await resp.text();
    throw new Error(`GET ${url} → ${resp.status}: ${txt}`);
  }
  return (await resp.json()) as T;
}
