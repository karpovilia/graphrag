/** One-off: parse the last 3 weeks of kb2/dump into a PROJECT (full corpus,
 *  chat-parsed) and assemble a TYPED graph hand-extracted by Claude (the
 *  reasoning tier) per the agreed schema. Entities are auto-linked to the real
 *  source messages (provenance + valid-time) by matching their names/aliases in
 *  the parsed text. Writes projects/<pid>/ and graphs/<gid>/. */
import { promises as fs } from "node:fs";
import path from "node:path";
import {
  parseDocuments, withLayout, granularityOf, nowIso, louvain,
  type Edge, type GraphMeta, type GraphState, type Node, type ParsedDocument, type ProjectMeta,
} from "@graphcraft/core";

const ROOT = "/home/ki/repos/kb2/dump";
const PROJECTS = "/home/ki/repos/graphcraft/projects";
const GRAPHS = "/home/ki/repos/graphcraft/graphs";
const PID = "kb2-3w";
const GID = "kb2-3w-afina";
const now = nowIso();

// ── revised schema (entity types + relations) ──
const SCHEMA = {
  $schema: "https://json-schema.org/draft-07/schema#",
  entityTypes: {
    PERSON: { title: "Человек", icon: "👤", sections: [{ key: "f", title: "Данные", fields: [{ key: "aliases", title: "Алиасы", type: "string", multi: true }, { key: "role", title: "Роль", type: "string", summary: true }] }] },
    ORG: { title: "Организация", icon: "🏢", sections: [{ key: "f", title: "Данные", fields: [{ key: "kind", title: "Вид", type: "string" }] }] },
    TEAM: { title: "Команда", icon: "👥", sections: [{ key: "f", title: "Данные", fields: [] }] },
    CLIENT: { title: "Клиент", icon: "🤝", sections: [{ key: "f", title: "Данные", fields: [{ key: "segment", title: "Сегмент", type: "string" }] }] },
    PROJECT: { title: "Проект", icon: "📁", sections: [{ key: "f", title: "Данные", fields: [] }] },
    SYSTEM: { title: "Система", icon: "🖥", sections: [{ key: "f", title: "Данные", fields: [] }] },
    METRIC: { title: "Метрика", icon: "📊", sections: [{ key: "f", title: "Данные", fields: [{ key: "value", title: "Значение", type: "string", summary: true }] }] },
    MEETING: { title: "Созвон", icon: "📅", sections: [{ key: "f", title: "Данные", fields: [{ key: "date", title: "Дата", type: "date", summary: true }] }] },
    DECISION: { title: "Решение", icon: "⚖", sections: [{ key: "f", title: "Данные", fields: [] }] },
    INCIDENT: { title: "Инцидент", icon: "🔥", sections: [{ key: "f", title: "Данные", fields: [{ key: "status", title: "Статус", type: "string" }] }] },
    TECH: { title: "Технология", icon: "💡", sections: [{ key: "f", title: "Данные", fields: [] }] },
    EPIC: { title: "Эпик", icon: "🗂", sections: [{ key: "f", title: "Данные", fields: [{ key: "status", title: "Статус", type: "string", summary: true }] }] },
    STORY: { title: "Стори", icon: "📄", sections: [{ key: "f", title: "Данные", fields: [{ key: "status", title: "Статус", type: "string", summary: true }] }] },
    TASK: { title: "Таск", icon: "✅", sections: [{ key: "f", title: "Данные", fields: [{ key: "status", title: "Статус", type: "enum", enum: ["Бэклог", "Подготовка", "В работе", "На проверке", "Готово"], summary: true }, { key: "priority", title: "Приоритет", type: "enum", enum: ["Low", "Medium", "High", "Urgent"] }, { key: "task_id", title: "ID", type: "string" }, { key: "url", title: "Ссылка", type: "string" }] }] },
  },
};

// ── Claude's extraction from the read sample (people, clients, systems, tasks…) ──
type E = { id: string; type: string; name: string; aliases?: string[]; attrs?: Record<string, unknown> };
const ENT: E[] = [
  // people
  { id: "ilia_karpov", type: "PERSON", name: "Илья Карпов", aliases: ["Karpov Ilia", "Ilia Karpov", "Илья"], attrs: { role: "lead" } },
  { id: "denis", type: "PERSON", name: "Денис" },
  { id: "dima", type: "PERSON", name: "Дима" },
  { id: "yura", type: "PERSON", name: "Юра", aliases: ["Yuri Kh"] },
  { id: "kirill", type: "PERSON", name: "Кирилл" },
  { id: "artem", type: "PERSON", name: "Артём", aliases: ["Артем"] },
  { id: "sasha_borzova", type: "PERSON", name: "Саша Борзова" },
  { id: "kolya", type: "PERSON", name: "Коля", aliases: ["nick_romanov", "Nick Romanov", "Романов"] },
  { id: "maksim_guskov", type: "PERSON", name: "Максим Гуськов", aliases: ["Максим Владимирович Гуськов", "Maksim"] },
  { id: "prisyazhnyuk", type: "PERSON", name: "Александр Присяжнюк", aliases: ["avprisyazhnyuk", "Александр Васильевич Присяжнюк"] },
  { id: "karelin", type: "PERSON", name: "Карелин" },
  { id: "matvey", type: "PERSON", name: "Матвей" },
  { id: "olesya", type: "PERSON", name: "Олеся" },
  { id: "ivan", type: "PERSON", name: "Иван", aliases: ["ivan"] },
  { id: "standrik", type: "PERSON", name: "Alexander Standrik", aliases: ["Стандрик"] },
  { id: "ilia_tarasov", type: "PERSON", name: "Илья Тарасов" },
  { id: "asad", type: "PERSON", name: "Asad" },
  // orgs / teams / clients
  { id: "c2m", type: "ORG", name: "C2M", aliases: ["С2М"], attrs: { kind: "company" } },
  { id: "hse", type: "ORG", name: "ВШЭ", aliases: ["Высшая школа экономики", "HSE"], attrs: { kind: "university" } },
  { id: "team_stats", type: "TEAM", name: "Statistics" },
  { id: "team_afina", type: "TEAM", name: "Команда Afina" },
  { id: "beeline_kz", type: "CLIENT", name: "Beeline KZ", aliases: ["Билайн КЗ"], attrs: { segment: "telecom" } },
  { id: "beeline_ru", type: "CLIENT", name: "Beeline", aliases: ["Билайн"], attrs: { segment: "telecom" } },
  { id: "mts", type: "CLIENT", name: "МТС", aliases: ["MTS"], attrs: { segment: "telecom" } },
  { id: "tele2", type: "CLIENT", name: "Tele2", aliases: ["t2 RU", "т2"], attrs: { segment: "telecom" } },
  // project / systems
  { id: "afina", type: "PROJECT", name: "Afina", aliases: ["Афина", "афина"] },
  { id: "betting_checker", type: "PROJECT", name: "Беттинг-чекер" },
  { id: "research_tg", type: "PROJECT", name: "Temporal graph research" },
  { id: "clp", type: "SYSTEM", name: "CLP" },
  { id: "dmp", type: "SYSTEM", name: "DMP" },
  { id: "vitrины", type: "SYSTEM", name: "Витрины" },
  { id: "demo_stends", type: "SYSTEM", name: "Демо-стенды", aliases: ["RC-стенды"] },
  { id: "antibot", type: "SYSTEM", name: "Антибот" },
  { id: "dvh", type: "SYSTEM", name: "ДВХ" },
  { id: "sms_cascade", type: "SYSTEM", name: "SMS-каскады" },
  // metrics
  { id: "m_default", type: "METRIC", name: "Доля дефолтов в топ-1%", attrs: { value: "27.2% vs 5%" } },
  { id: "m_acc", type: "METRIC", name: "Точность дообучения", attrs: { value: "94–94.7%" } },
  // meetings
  { id: "mt_sync", type: "MEETING", name: "afina Management Sync", attrs: { date: "2026-05-25" } },
  { id: "mt_dev", type: "MEETING", name: "afina Development Weekly", attrs: { date: "2026-05-27" } },
  { id: "mt_mon", type: "MEETING", name: "afina Monetization", attrs: { date: "2026-05-27" } },
  { id: "mt_clp", type: "MEETING", name: "afina CLP status update", attrs: { date: "2026-05-26" } },
  { id: "mt_mentor", type: "MEETING", name: "Mentor's Seminar", attrs: { date: "2026-05-27" } },
  { id: "mt_swot", type: "MEETING", name: "SWOT-анализ хеширование/шифрование", attrs: { date: "2026-05-26" } },
  { id: "mt_4035", type: "MEETING", name: "4035 антибот", attrs: { date: "2026-05-26" } },
  { id: "mt_bkz", type: "MEETING", name: "C2M Afina x Beeline KZ", attrs: { date: "2026-05-26" } },
  // decisions / incidents / tech
  { id: "dec_sms", type: "DECISION", name: "Увеличить первую задержку SMS до 1 часа", attrs: {} },
  { id: "dec_matvey", type: "DECISION", name: "Сделать выговор Матвею" },
  { id: "dec_tracker", type: "DECISION", name: "Завести трекер задач" },
  { id: "inc_bkz", type: "INCIDENT", name: "Beeline KZ: дублирование кампаний, нет альфа-имён", attrs: { status: "resolved" } },
  { id: "inc_vitrina", type: "INCIDENT", name: "Обновление МФО-витрины на ставки.лайв", attrs: { status: "investigating" } },
  { id: "inc_4035", type: "INCIDENT", name: "Антибот 4035: спорные конверсии, потеря CID", attrs: { status: "investigating" } },
  { id: "tech_tgn", type: "TECH", name: "TGN" }, { id: "tech_tgat", type: "TECH", name: "TGAT" },
  { id: "tech_jodie", type: "TECH", name: "Jodie" }, { id: "tech_lora", type: "TECH", name: "LoRA" },
  { id: "tech_gnn", type: "TECH", name: "GNN" }, { id: "tech_sha", type: "TECH", name: "SHA-256" },
  // epic / stories / tasks
  { id: "epic_stats", type: "EPIC", name: "Statistics Roadmap", attrs: { status: "В работе" } },
  { id: "story_stats", type: "STORY", name: "Внедрение статистики", attrs: { status: "В работе" } },
  { id: "story_bkz_migr", type: "STORY", name: "Переезд Beeline KZ в новый ЦОД", attrs: { status: "Готово" } },
  { id: "t5318", type: "TASK", name: "Статистика MVP — разрез первичное/каскадное/утилизация", attrs: { status: "Подготовка", priority: "High", task_id: "ADH-5318" } },
  { id: "t5319", type: "TASK", name: "Анализ метрик витрин с сентября 2025 — аномалии", attrs: { status: "Подготовка", priority: "High", task_id: "ADH-5319" } },
  { id: "t5320", type: "TASK", name: "Crashbackloop для беттинг-чекера", attrs: { status: "Подготовка", priority: "Medium", task_id: "ADH-5320" } },
  { id: "t5321", type: "TASK", name: "Уведомления Карелина об изменениях в беттинге", attrs: { status: "Подготовка", priority: "Medium", task_id: "ADH-5321" } },
  { id: "t5322", type: "TASK", name: "Сводка и 2 слайда по архитектуре беттинг-чекера", attrs: { status: "Подготовка", priority: "Medium", task_id: "ADH-5322" } },
  { id: "t5358", type: "TASK", name: "Разрезы «3 дня» и «За вчера»", attrs: { status: "В работе", priority: "Medium", task_id: "ADH-5358" } },
  { id: "t_bkz_dc", type: "TASK", name: "Переезд серверов Beeline KZ в новый ЦОД", attrs: { status: "Готово", priority: "High" } },
];

type R = { s: string; p: string; t: string };
const REL: R[] = [
  // org / membership
  ...["ilia_karpov", "denis", "dima", "yura", "kirill", "artem", "sasha_borzova", "kolya", "maksim_guskov", "prisyazhnyuk", "matvey", "olesya"].map((s) => ({ s, p: "works_at", t: "c2m" })),
  { s: "standrik", p: "works_at", t: "hse" }, { s: "ilia_tarasov", p: "works_at", t: "hse" }, { s: "ilia_karpov", p: "works_at", t: "hse" },
  { s: "kolya", p: "member_of", t: "team_stats" }, { s: "kirill", p: "member_of", t: "team_stats" },
  { s: "ilia_karpov", p: "member_of", t: "team_afina" }, { s: "denis", p: "member_of", t: "team_afina" }, { s: "dima", p: "member_of", t: "team_afina" }, { s: "yura", p: "member_of", t: "team_afina" },
  { s: "team_afina", p: "owns", t: "afina" }, { s: "team_stats", p: "owns", t: "clp" },
  // systems of afina + clients
  ...["clp", "dmp", "vitrины", "demo_stends", "antibot", "sms_cascade"].map((t) => ({ s: "afina", p: "about", t })),
  { s: "afina", p: "for_client", t: "beeline_kz" }, { s: "afina", p: "for_client", t: "beeline_ru" }, { s: "afina", p: "for_client", t: "mts" }, { s: "afina", p: "for_client", t: "tele2" },
  // tasks hierarchy + assignment + about
  { s: "story_stats", p: "part_of", t: "epic_stats" },
  ...["t5318", "t5358"].map((s) => ({ s, p: "part_of", t: "story_stats" })),
  { s: "t_bkz_dc", p: "part_of", t: "story_bkz_migr" },
  { s: "t5318", p: "assigned_to", t: "kolya" }, { s: "t5358", p: "assigned_to", t: "kolya" },
  { s: "t5321", p: "assigned_to", t: "karelin" }, { s: "t_bkz_dc", p: "assigned_to", t: "ivan" }, { s: "t_bkz_dc", p: "assigned_to", t: "yura" }, { s: "t_bkz_dc", p: "assigned_to", t: "maksim_guskov" },
  ...["t5320", "t5322"].map((s) => ({ s, p: "about", t: "betting_checker" })),
  ...["t5318", "t5319", "t5358", "epic_stats"].map((s) => ({ s, p: "about", t: "afina" })),
  { s: "t5319", p: "about", t: "vitrины" }, { s: "t_bkz_dc", p: "for_client", t: "beeline_kz" },
  // incidents
  { s: "inc_bkz", p: "affects", t: "beeline_kz" }, { s: "inc_bkz", p: "affects", t: "sms_cascade" },
  { s: "inc_vitrina", p: "affects", t: "vitrины" }, { s: "inc_4035", p: "affects", t: "antibot" },
  // decisions
  { s: "ilia_karpov", p: "made_decision", t: "dec_tracker" }, { s: "dec_sms", p: "decision_about", t: "sms_cascade" }, { s: "dec_matvey", p: "decision_about", t: "matvey" },
  // meetings (who discussed what)
  ...["mt_sync", "mt_dev", "mt_mon", "mt_clp"].map((t) => ({ s: "afina", p: "discussed_in", t })),
  { s: "inc_bkz", p: "discussed_in", t: "mt_bkz" }, { s: "inc_4035", p: "discussed_in", t: "mt_4035" },
  { s: "dec_sms", p: "discussed_in", t: "mt_mon" }, { s: "tech_sha", p: "discussed_in", t: "mt_swot" },
  ...["tech_tgn", "tech_tgat", "tech_jodie", "tech_lora", "tech_gnn"].map((s) => ({ s, p: "about", t: "research_tg" })),
  { s: "standrik", p: "discussed_in", t: "mt_mentor" }, { s: "m_acc", p: "about", t: "research_tg" }, { s: "m_default", p: "about", t: "research_tg" },
];

// ── assemble ──
async function readWeeks(): Promise<{ uri: string; text: string }[]> {
  const out: { uri: string; text: string }[] = [];
  const weeks = (await fs.readdir(ROOT)).filter((w) => /^20\d\d-W\d\d$/.test(w)).sort().slice(-3);
  const walk = async (dir: string) => {
    for (const e of await fs.readdir(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) await walk(p);
      else if (e.name.endsWith(".txt")) out.push({ uri: path.relative(ROOT, p), text: await fs.readFile(p, "utf8") });
    }
  };
  for (const w of weeks) await walk(path.join(ROOT, w));
  return out;
}

const hash = (s: string) => { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return (h >>> 0).toString(36); };

async function main() {
  const files = await readWeeks();
  const docs: ParsedDocument[] = parseDocuments(files, { format: "chat", chunkSize: 1200, chunkOverlap: 100, perMessage: true });
  console.log(`parsed ${files.length} files → ${docs.length} message-docs`);

  // project
  await fs.mkdir(path.join(PROJECTS, PID), { recursive: true });
  const pmeta: ProjectMeta = { id: PID, name: "KB2 — последние 3 недели", createdAt: now, parse: { format: "chat", chunkSize: 1200, chunkOverlap: 100, perMessage: true }, source: "kb2/dump (last 3 weeks)", documentCount: docs.length };
  await fs.writeFile(path.join(PROJECTS, PID, "meta.json"), JSON.stringify(pmeta, null, 2));
  await fs.writeFile(path.join(PROJECTS, PID, "documents.json"), JSON.stringify(docs, null, 2));

  // index docs by lowercased text for name matching
  const lc = docs.map((d) => ({ d, t: d.text.toLowerCase() }));
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const chunkNodes = new Map<string, Node>();
  const idOf = new Map(ENT.map((e) => [e.id, `n_${e.id}`]));

  for (const e of ENT) {
    const needles = [e.name, ...(e.aliases ?? [])].map((s) => s.toLowerCase());
    const matches = lc.filter((x) => needles.some((n) => n.length > 2 && x.t.includes(n))).slice(0, 6);
    let validFrom: string | null = null;
    const prov = matches.map((m) => {
      if (m.d.validFrom && (!validFrom || m.d.validFrom < validFrom)) validFrom = m.d.validFrom;
      const cid = `c_${hash(m.d.id)}`;
      if (!chunkNodes.has(cid)) {
        chunkNodes.set(cid, { id: cid, graphId: GID, layer: "chunk", type: "CHUNK", granularity: 0, name: m.d.uri, summary: null, attributes: { text: m.d.text, documentId: m.d.uri, ...(m.d.author ? { author: m.d.author } : {}) }, provenance: [{ documentId: m.d.uri, spanStart: 0, spanEnd: m.d.text.length }], x: null, y: null, pinned: false, validFrom: m.d.validFrom ?? null, validTo: null, txFrom: now, txTo: null });
      }
      return { documentId: m.d.uri, spanStart: 0, spanEnd: m.d.text.length };
    });
    nodes.push({ id: idOf.get(e.id)!, graphId: GID, layer: "entity", type: e.type, granularity: granularityOf("entity"), name: e.name, summary: null, attributes: { ...(e.aliases ? { aliases: e.aliases } : {}), ...(e.attrs ?? {}) }, provenance: prov, x: null, y: null, pinned: false, validFrom, validTo: null, txFrom: now, txTo: null });
    for (const m of matches) edges.push({ id: `m_${hash(e.id + m.d.id)}`, graphId: GID, type: "mentioned_in", sourceId: idOf.get(e.id)!, targetId: `c_${hash(m.d.id)}`, weight: null, relation: null, explanation: null, confidence: "extracted", provenance: [], attributes: {}, validFrom: null, validTo: null, txFrom: now, txTo: null, invalidation: null });
  }
  for (const n of chunkNodes.values()) nodes.push(n);

  let ri = 0;
  for (const r of REL) {
    const s = idOf.get(r.s), t = idOf.get(r.t);
    if (!s || !t) { console.warn("bad rel", r); continue; }
    edges.push({ id: `r_${++ri}`, graphId: GID, type: "entity_relation", sourceId: s, targetId: t, weight: 1, relation: r.p, explanation: null, confidence: "extracted", confidenceScore: 0.95, provenance: [], attributes: {}, validFrom: null, validTo: null, txFrom: now, txTo: null, invalidation: null });
  }

  // communities via Louvain over the entity_relation graph → zones on canvas
  const entIds = ENT.map((e) => idOf.get(e.id)!);
  const relForLouvain = edges.filter((e) => e.type === "entity_relation").map((e) => ({ a: e.sourceId, b: e.targetId, w: 1 }));
  const membership = louvain(entIds, relForLouvain);
  const byComm = new Map<number, string[]>();
  for (const [nid, c] of membership) (byComm.get(c) ?? byComm.set(c, []).get(c)!).push(nid);
  let ci = 0;
  for (const [, members] of [...byComm.entries()].sort((a, b) => a[0] - b[0])) {
    if (members.length < 3) continue; // skip tiny clusters
    const cid = `k_${ci}`;
    nodes.push({ id: cid, graphId: GID, layer: "community", type: "COMMUNITY", granularity: 2, name: `Сообщество ${ci + 1}`, summary: null, attributes: { algorithm: "louvain", size: members.length }, provenance: [], x: null, y: null, pinned: false, validFrom: null, validTo: null, txFrom: now, txTo: null });
    for (const m of members) edges.push({ id: `mo_${hash(m + cid)}`, graphId: GID, type: "member_of", sourceId: m, targetId: cid, weight: null, relation: null, explanation: null, confidence: "extracted", provenance: [], attributes: { algorithm: "louvain" }, validFrom: null, validTo: null, txFrom: now, txTo: null, invalidation: null });
    ci++;
  }

  let state: GraphState = { nodes, edges, journal: [] };
  state = withLayout(state, { seed: 42 });
  const layersPresent = [...new Set(state.nodes.map((n) => n.layer))];
  const meta: GraphMeta = { id: GID, name: "KB2 Afina (typed by Claude)", language: "ru", projectId: PID, version: 0, source: "build:claude-reasoning", createdAt: now, nodeCount: state.nodes.length, edgeCount: state.edges.length, layersPresent };

  await fs.mkdir(path.join(GRAPHS, GID), { recursive: true });
  await fs.writeFile(path.join(GRAPHS, GID, "base.json"), JSON.stringify({ nodes: state.nodes, edges: state.edges, journal: [] }, null, 2));
  await fs.writeFile(path.join(GRAPHS, GID, "journal.jsonl"), "");
  await fs.writeFile(path.join(GRAPHS, GID, "meta.json"), JSON.stringify(meta, null, 2));
  await fs.writeFile(path.join(GRAPHS, GID, "schema.json"), JSON.stringify(SCHEMA, null, 2));

  const byType: Record<string, number> = {};
  for (const e of ENT) byType[e.type] = (byType[e.type] ?? 0) + 1;
  console.log(`graph ${GID}: ${state.nodes.length} nodes (${ENT.length} entities + ${chunkNodes.size} chunks), ${state.edges.length} edges`);
  console.log("entity types:", JSON.stringify(byType));
}
main().catch((e) => { console.error(e); process.exit(1); });
