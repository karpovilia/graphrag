// Seeds the InMemory backend with a fresh HSE-podcast fixture and
// returns the corpus + variant ids the spec navigates to. Each test
// run is independent; we don't try to reuse state between specs.

import fs from "node:fs/promises";
import path from "node:path";

export type SeedResult = {
  run_id: string;
  corpus_id: string;
  corpus_name: string;
  variant_leiden_id: string;
  variant_leiden_name: string;
  variant_bare_id: string;
  variant_bare_name: string;
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

  return {
    run_id,
    corpus_id: corpus.id,
    corpus_name,
    variant_leiden_id: leiden.id,
    variant_leiden_name,
    variant_bare_id: bare.id,
    variant_bare_name,
  };
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
