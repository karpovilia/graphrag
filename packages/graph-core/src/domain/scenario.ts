import type { CorpusProfile } from "../build/profile.js";

/** A GRAPH SCENARIO is a ready-made bundle: "how the graphrag will work" for a
 *  business goal — which entity kinds it centers on, which relations matter, how
 *  to build (extractor, clustering) and how to view it (axis, communities). The
 *  AI-led setup flow proposes scenarios after analyzing the parsed corpus; the
 *  human picks one and the build is preset. (Afina's "Выберите сценарий".) */
export interface ScenarioView {
  axis: "tx" | "valid";
  communities: boolean;
  /** entity types to show by default (empty = all). */
  types?: string[];
}
export interface ScenarioBuild {
  /** preferred extraction backend (the human can still override). */
  extractor: "keyless" | "lightrag";
  /** Louvain resolution: higher → more, smaller communities. */
  resolution?: number;
  minCooccurrence?: number;
}
/** Data-driven match descriptor → makes ranking a pure function (serializable). */
export interface ScenarioMatch {
  /** entity kinds whose presence in the corpus boosts this scenario. */
  entityTypes?: string[];
  /** boost when the corpus carries event time (dated chat messages). */
  needsTime?: boolean;
  /** boost when the corpus is a chat (authors present). */
  needsChat?: boolean;
  /** boost when the goal text / top terms contain any of these. */
  keywords?: string[];
}
export interface GraphScenario {
  id: string;
  title: string;
  subtitle: string;
  category: string;
  icon: string;
  /** questions this scenario lets you answer. */
  answers: string[];
  entityTypes: string[];
  relations: string[];
  build: ScenarioBuild;
  view: ScenarioView;
  match: ScenarioMatch;
  /** always available regardless of fit (baseline scenarios). */
  baseline?: boolean;
}

export const SCENARIO_CATALOG: GraphScenario[] = [
  {
    id: "team-map",
    title: "Карта команды и ответственности",
    subtitle: "Кто над чем работает и кто за что отвечает",
    category: "Команда",
    icon: "👥",
    answers: ["Кто владеет задачей?", "Кто в какой команде?", "Зоны ответственности"],
    entityTypes: ["PERSON", "TEAM", "ORG", "TASK"],
    relations: ["works_on", "owns", "member_of", "reports_to"],
    build: { extractor: "lightrag", resolution: 1.1 },
    view: { axis: "tx", communities: true, types: ["PERSON", "TEAM", "ORG", "TASK"] },
    match: { entityTypes: ["PERSON", "TEAM", "ORG"], needsChat: true, keywords: ["команда", "ответствен", "team", "owner", "роль"] },
  },
  {
    id: "timeline",
    title: "Хронология проекта",
    subtitle: "Эпики → стори → таски на временной оси",
    category: "Время",
    icon: "🗓",
    answers: ["Что когда происходило?", "Как развивались эпики?", "Активность по времени"],
    entityTypes: ["EPIC", "STORY", "TASK", "EVENT"],
    relations: ["part_of", "blocks", "depends_on", "happened_at"],
    build: { extractor: "lightrag", resolution: 1.0 },
    view: { axis: "valid", communities: false, types: ["EPIC", "STORY", "TASK", "EVENT"] },
    match: { needsTime: true, entityTypes: ["EPIC", "STORY", "TASK", "EVENT"], keywords: ["срок", "хронолог", "timeline", "дедлайн", "релиз", "спринт"] },
  },
  {
    id: "clients",
    title: "Клиенты и обязательства",
    subtitle: "Клиенты, организации и что им обещано",
    category: "Клиенты",
    icon: "🤝",
    answers: ["Какие обязательства перед клиентом?", "Кто ведёт клиента?", "Контракты и сроки"],
    entityTypes: ["CLIENT", "ORG", "CONTRACT", "PERSON"],
    relations: ["commitment", "deadline", "owns", "works_on"],
    build: { extractor: "lightrag", resolution: 1.0 },
    view: { axis: "valid", communities: true, types: ["CLIENT", "ORG", "CONTRACT", "PERSON"] },
    match: { entityTypes: ["CLIENT", "ORG", "CONTRACT"], keywords: ["клиент", "билайн", "контракт", "обязательств", "client", "sla"] },
  },
  {
    id: "themes",
    title: "Тематические сообщества знаний",
    subtitle: "Кластеры тем с интерпретируемыми названиями и summary",
    category: "Темы",
    icon: "◎",
    answers: ["Какие темы есть в корпусе?", "Что внутри каждой темы?", "Связи между темами"],
    entityTypes: [],
    relations: ["co_occurrence", "entity_relation"],
    build: { extractor: "lightrag", resolution: 1.3 },
    view: { axis: "tx", communities: true },
    match: { keywords: ["темы", "обзор", "overview", "знани", "карта"] },
    baseline: true,
  },
  {
    id: "risks",
    title: "Риски и блокеры",
    subtitle: "Что блокирует прогресс и от чего зависит",
    category: "Риски",
    icon: "⚠",
    answers: ["Что заблокировано?", "Где узкие места?", "Цепочки зависимостей"],
    entityTypes: ["TASK", "STORY", "RISK"],
    relations: ["blocks", "depends_on", "risk"],
    build: { extractor: "lightrag", resolution: 1.2 },
    view: { axis: "tx", communities: false, types: ["TASK", "STORY", "RISK"] },
    match: { entityTypes: ["TASK", "STORY"], keywords: ["риск", "блок", "blocker", "зависим", "проблем", "risk"] },
  },
];

/** A structured fit reason (localized on the client, not baked in a language). */
export interface WhyReason {
  code: "types" | "time" | "chat" | "goal" | "terms";
  arg?: string;
}
export interface RankedScenario {
  scenario: GraphScenario;
  score: number;
  recommended: boolean;
  /** why this scenario fits — structured so the UI localizes it. */
  why: WhyReason[];
}

/** Score every scenario against the corpus profile + the user's goal text, and
 *  flag the top fits as recommended. Pure — drives both the server default and
 *  the AI assistant's ranking. */
export function rankScenarios(profile: CorpusProfile, goal = ""): RankedScenario[] {
  const goalL = goal.toLowerCase();
  const termSet = new Set(profile.topTerms.map((t) => t.term));
  const typePresent = new Set(Object.keys(profile.entityTypes).map((t) => t.toUpperCase()));

  const ranked = SCENARIO_CATALOG.map((s) => {
    const why: WhyReason[] = [];
    let score = s.baseline ? 0.25 : 0;

    const hitTypes = (s.match.entityTypes ?? []).filter((t) => typePresent.has(t));
    if (hitTypes.length) {
      score += 0.25 * Math.min(2, hitTypes.length);
      why.push({ code: "types", arg: hitTypes.join(", ") });
    }
    if (s.match.needsTime && profile.timeSpan.dated > 0) {
      score += 0.3;
      why.push({ code: "time" });
    }
    if (s.match.needsChat && profile.authors.length > 1) {
      score += 0.15;
      why.push({ code: "chat", arg: String(profile.authors.length) });
    }
    const kw = (s.match.keywords ?? []).filter(
      (k) => goalL.includes(k) || [...termSet].some((t) => t.includes(k)),
    );
    if (kw.length) {
      score += 0.2 * Math.min(2, kw.length);
      if (goalL && (s.match.keywords ?? []).some((k) => goalL.includes(k))) why.push({ code: "goal" });
      else why.push({ code: "terms", arg: kw.slice(0, 3).join(", ") });
    }
    return { scenario: s, score: Math.min(1, score), recommended: false, why };
  }).sort((a, b) => b.score - a.score);

  // recommend the leaders (score within 0.15 of the top, at least the top one)
  const top = ranked[0]?.score ?? 0;
  for (const r of ranked) r.recommended = r.score > 0.3 && top - r.score <= 0.15;
  if (ranked[0]) ranked[0].recommended = true;
  return ranked;
}

export const scenarioById = (id: string): GraphScenario | undefined =>
  SCENARIO_CATALOG.find((s) => s.id === id);
