export interface RenderNode {
  id: string;
  name: string;
  x: number;
  y: number;
  data: {
    color: string;
    size: number;
    borderColor?: string;
    tags: string[];
    pinned?: boolean;
    verified?: boolean;
    _matched?: boolean | null;
    _deltaStatus?: string;
  };
}

/** Full node/edge records returned by the detail endpoints (for the inspector). */
export interface Verification {
  by: string;
  at: string;
  asOf?: string | null;
  axis?: "tx" | "valid";
}
export interface FactSource {
  id: string;
  documentId: string | null;
  text: string | null;
}
export interface Fact {
  id: string;
  kind: "relation" | "attribute";
  // relation
  dir?: "in" | "out";
  relation?: string;
  neighbor?: { id: string; name: string; layer: string; type: string; validFrom?: string | null; validTo?: string | null };
  category?: string;
  /** valid interval of this fact (relationship/attribute), if dated. */
  validFrom?: string | null;
  validTo?: string | null;
  // attribute
  key?: string;
  value?: unknown;
  // common
  confidence: number | null;
  verified: Verification | null;
  /** verified, but the fact was edited after verification → re-verify. */
  stale?: boolean;
  sources: FactSource[];
  sourceCount: number;
}
export interface NodeDetail {
  node: {
    id: string; name: string; type: string; layer: string; granularity: number;
    summary: string | null; pinned: boolean; verified: Verification | null;
    validFrom?: string | null; validTo?: string | null; txFrom?: string | null; txTo?: string | null;
  };
  facts: Fact[];
  sources: FactSource[];
}
export interface EdgeDetail {
  edge: Record<string, unknown>;
  source: { id: string; name: string; layer?: string; type?: string };
  target: { id: string; name: string; layer?: string; type?: string };
}
export interface RenderLink {
  source: string;
  target: string;
  data: { id: string; relation?: string | null; confidence: string; tags: string[]; color: string };
}
export interface LayerLegend {
  layer: string;
  color: string;
  count: number;
  active: boolean;
}
export interface RenderGroup {
  id: string;
  name: string;
  color: string;
  summary: string | null;
  memberIds: string[];
}
export interface TypeLegend {
  type: string;
  color: string;
  count: number;
  active: boolean;
}
export interface RenderGraph {
  name: string;
  version: number;
  graph: {
    nodes: RenderNode[];
    links: RenderLink[];
    groups: RenderGroup[];
    legends: {
      size: string;
      color: { color: string; description: string }[];
      layers: LayerLegend[];
      types: TypeLegend[];
    };
    settings: { alwaysLabelVisible: boolean };
  };
}

/** The graph's data model (JSON-Schema-shaped) driving the dossier card. */
export interface SchemaField {
  key: string;
  title: string;
  type: "string" | "number" | "date" | "boolean" | "ref";
  icon?: string;
  summary?: boolean;
  multi?: boolean;
  ref?: { entityType?: string; edgeType?: string; relation?: string | null };
}
export interface SchemaSection {
  key: string;
  title: string;
  icon?: string;
  fields: SchemaField[];
}
export interface EntityTypeSchema {
  type: string;
  title: string;
  icon?: string;
  sections: SchemaSection[];
}
export interface GraphSchema {
  $schema: string;
  derivedAt?: string;
  entityTypes: Record<string, EntityTypeSchema>;
}

/** ── AI-led setup flow (analyze corpus → propose scenarios → build) ── */
export interface CorpusProfile {
  format: "plain" | "chat";
  docCount: number;
  sampledDocs: number;
  charCount: number;
  estChunks: number;
  languages: { lang: "ru" | "en"; share: number }[];
  timeSpan: { from: string | null; to: string | null; dated: number };
  authors: { name: string; count: number }[];
  entityTypes: Record<string, number>;
  topTerms: { term: string; count: number }[];
  provider: string | null;
}
export interface GraphScenario {
  id: string;
  title: string;
  subtitle: string;
  category: string;
  icon: string;
  answers: string[];
  entityTypes: string[];
  relations: string[];
  build: { extractor: "keyless" | "lightrag"; resolution?: number; minCooccurrence?: number };
  view: { axis: "tx" | "valid"; communities: boolean; types?: string[] };
}
export interface WhyReason {
  code: "types" | "time" | "chat" | "goal" | "terms";
  arg?: string;
}
export interface RankedScenario {
  scenario: GraphScenario;
  score: number;
  recommended: boolean;
  why: WhyReason[];
}
export interface SetupSession {
  projectId: string;
  goal: string;
  graphName: string;
  profile: CorpusProfile | null;
  scenarios: RankedScenario[];
  selectedScenarioId: string | null;
  confirmedTypes: string[];
  extractor: "keyless" | "lightrag";
  communities: boolean;
  axis: "tx" | "valid";
  step: number;
  status: "idle" | "analyzing" | "ready" | "building" | "done";
  assistantNotes: { by: string; at: string; text: string; step?: number }[];
  builtGraphId?: string;
  updatedAt: string;
}
export type SetupPatch = Partial<
  Pick<SetupSession, "goal" | "graphName" | "selectedScenarioId" | "confirmedTypes" | "extractor" | "communities" | "axis" | "step">
>;

/** Current view restriction: visible layers + optional time-travel. */
export interface GraphView {
  layers: string[];
  types: string[];
  asOf: string | null;
  axis: "tx" | "valid";
  /** overlay Batagelj same-layer projections (derived 2nd-order edges). */
  projections?: boolean;
  /** time window: keep only nodes born within [from, to]. */
  from?: string | null;
  to?: string | null;
}

/** One activity bucket on the timeline scrubber (heatmap cell). */
export interface TimelineEvent {
  id: string;
  at: string;
  label: string;
  bornCount: number;
  deadCount: number;
  opCount: number;
  eventCount: number;
}
export type Bucket = "instant" | "hour" | "day" | "week" | "month" | "quarter" | "year";
export interface QuantSegment { from?: string | null; to?: string | null; bucket: Bucket }
export interface Timeline {
  axis: "tx" | "valid";
  events: TimelineEvent[];
  genesisCount: number;
  genesisNodeIds: string[];
  min: string | null;
  max: string | null;
}

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = init?.body
    ? { "content-type": "application/json", ...(init?.headers ?? {}) }
    : init?.headers;
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) throw new Error(`${res.status} ${path}: ${await res.text()}`);
  return (res.status === 204 ? null : await res.json()) as T;
}

export const api = {
  listGraphs: () =>
    j<{ id: string; name: string; nodeCount: number; edgeCount: number; layersPresent: string[]; source?: string | null; createdAt: string }[]>("/api/graphs"),
  deleteGraph: (id: string) => j(`/api/graphs/${id}`, { method: "DELETE" }),
  deleteProject: (p: string) => j(`/api/projects/${p}`, { method: "DELETE" }),
  listProjects: () =>
    j<{ id: string; name: string; createdAt: string; documentCount: number; graphCount: number; parse: { format: string }; source?: string | null }[]>("/api/projects"),
  getProject: (p: string) =>
    j<{ id: string; name: string; parse: { format: string; chunkSize: number; chunkOverlap: number }; documentCount: number; graphs: { id: string; name: string; nodeCount: number; edgeCount: number; layersPresent: string[] }[] }>(`/api/projects/${p}`),
  createProject: (body: { name?: string; source?: string; parse?: Record<string, unknown>; files: { uri: string; text: string }[] }) =>
    j<{ id: string }>("/api/projects", { method: "POST", body: JSON.stringify(body) }),
  createGraphInProject: (p: string, body: { name?: string; language?: string; llm?: boolean }) =>
    j<{ id: string }>(`/api/projects/${p}/graphs`, { method: "POST", body: JSON.stringify(body) }),
  // ── AI-led setup flow ──
  setupAnalyze: (p: string, body: { goal?: string; llm?: boolean }) =>
    j<SetupSession>(`/api/projects/${p}/setup/analyze`, { method: "POST", body: JSON.stringify(body) }),
  getSetup: (p: string) => j<SetupSession>(`/api/projects/${p}/setup`),
  patchSetup: (p: string, patch: SetupPatch) =>
    j<SetupSession>(`/api/projects/${p}/setup`, { method: "PATCH", body: JSON.stringify(patch) }),
  setupBuild: (p: string) =>
    j<{ id: string; scenario: string | null }>(`/api/projects/${p}/setup/build`, { method: "POST", body: "{}" }),
  setupNote: (p: string, text: string, step?: number, by = "user:anon") =>
    j<SetupSession>(`/api/projects/${p}/setup/note`, { method: "POST", body: JSON.stringify({ by, text, step }) }),
  // chat with the setup assistant (DeepSeek): stores user + assistant notes
  setupChat: (p: string, text: string, step?: number) =>
    j<SetupSession>(`/api/projects/${p}/setup/chat`, { method: "POST", body: JSON.stringify({ text, step }) }),
  // project-less chat (before the project exists)
  chatGeneric: (text: string, history: { role: string; content: string }[]) =>
    j<{ reply: string | null; provider: string | null }>(`/api/setup/chat`, { method: "POST", body: JSON.stringify({ text, history }) }),
  ingestProject: (p: string, body: { files: { uri: string; text: string }[]; llm?: boolean }) =>
    j<{ documents: number; graphs: Record<string, unknown> }>(`/api/projects/${p}/ingest`, { method: "POST", body: JSON.stringify(body) }),
  profileGraph: (body: { documents: { id?: string; text: string }[]; llm?: boolean }) =>
    j<{ provider: string | null; sampledDocs: number; entityCount: number; types: Record<string, number>; schema: GraphSchema }>("/api/graphs/profile", { method: "POST", body: JSON.stringify(body) }),
  createGraph: (body: { name?: string; language?: string; documents: { id?: string; text: string }[]; llm?: boolean }) =>
    j<{ id: string }>("/api/graphs", { method: "POST", body: JSON.stringify(body) }),
  ingest: (id: string, body: { documents: { id?: string; text: string }[]; llm?: boolean }) =>
    j<{ addedNodes: number; addedEdges: number; linked: unknown[]; conflicts: unknown[]; autoMerges: number }>(`/api/graphs/${id}/ingest`, { method: "POST", body: JSON.stringify(body) }),
  getGraph: (id: string, view?: Partial<GraphView>) => {
    const q = new URLSearchParams();
    if (view?.layers?.length) q.set("layers", view.layers.join(","));
    if (view?.types?.length) q.set("types", view.types.join(","));
    if (view?.asOf) q.set("asOf", view.asOf);
    if (view?.axis) q.set("axis", view.axis);
    if (view?.projections) q.set("projections", "1");
    if (view?.from) q.set("from", view.from);
    if (view?.to) q.set("to", view.to);
    const qs = q.toString();
    return j<RenderGraph>(`/api/graph/${id}${qs ? `?${qs}` : ""}`);
  },
  journal: (id: string) => j<unknown[]>(`/api/graphs/${id}/journal`),
  ask: (
    id: string,
    question: string,
    opts?: {
      algorithm?: "lightrag" | "ms-graphrag" | "tog";
      useDate?: boolean; useKinds?: boolean; useSelection?: boolean;
      selection?: string[];
      view?: { from?: string | null; to?: string | null; types?: string[]; axis?: "tx" | "valid" };
      model?: string;
    },
  ) =>
    j<{
      answer: string;
      provider: string | null;
      model?: string;
      algorithm?: string;
      usedEntities: { id: string; name: string }[];
      usedCommunities: { id: string; name: string }[];
      paths?: string[];
      sources: { id: string; documentId: string | null; text: string }[];
    }>(`/api/graphs/${id}/ask`, { method: "POST", body: JSON.stringify({ question, ...opts }) }),
  // route a console question to the agent (Claude) instead of a server-side LLM.
  ragAsk: (id: string, question: string, config: Record<string, unknown>, by?: string) =>
    j<{ id: string }>(`/api/graphs/${id}/rag-questions`, {
      method: "POST",
      body: JSON.stringify({ question, config, by }),
    }),
  getNode: (id: string, nodeId: string, view?: Partial<GraphView>) => {
    const q = new URLSearchParams();
    if (view?.asOf) q.set("asOf", view.asOf);
    if (view?.axis) q.set("axis", view.axis);
    const qs = q.toString();
    return j<NodeDetail>(`/api/graphs/${id}/nodes/${nodeId}${qs ? `?${qs}` : ""}`);
  },
  getEdge: (id: string, edgeId: string) => j<EdgeDetail>(`/api/graphs/${id}/edges/${edgeId}`),
  projectionEdge: (id: string, source: string, target: string, relation: string) =>
    j<{
      source: { id: string; name: string };
      target: { id: string; name: string };
      relation: string;
      normalization: string;
      raw: number;
      weight: number;
      intermediaries: { id: string; kind: string; name: string; documentId: string | null; text: string | null; degree: number; contribution: number }[];
    }>(`/api/graphs/${id}/projection?source=${encodeURIComponent(source)}&target=${encodeURIComponent(target)}&relation=${encodeURIComponent(relation)}`),
  getSchema: (id: string) => j<GraphSchema>(`/api/graphs/${id}/schema`),
  putSchema: (id: string, schema: GraphSchema) =>
    j<GraphSchema>(`/api/graphs/${id}/schema`, { method: "PUT", body: JSON.stringify(schema) }),
  search: (id: string, q: string, limit = 8) =>
    j<{ id: string; name: string; type: string; layer: string }[]>(`/api/graphs/${id}/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  timeline: (id: string, axis: "tx" | "valid", bucket?: Bucket | "auto", segments?: QuantSegment[]) => {
    const q = new URLSearchParams({ axis });
    if (bucket) q.set("bucket", bucket);
    if (segments?.length) q.set("segments", JSON.stringify(segments));
    return j<Timeline>(`/api/graphs/${id}/timeline?${q}`);
  },
  diff: (id: string, from: string, to: string, axis: "tx" | "valid") =>
    j<{ born: string[]; dead: string[] }>(`/api/graphs/${id}/diff?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&axis=${axis}`),
  suggestions: (id: string) => j<unknown[]>(`/api/graphs/${id}/suggestions`),
  applyOp: (id: string, op: string, payload: Record<string, unknown>, actor: string) =>
    j(`/api/graphs/${id}/ops`, { method: "POST", body: JSON.stringify({ op, payload, actor }) }),
  revert: (id: string, actor: string) =>
    j(`/api/graphs/${id}/revert`, { method: "POST", body: JSON.stringify({ actor }) }),
  runAgent: (id: string, name: "dedup" | "orphans" | "dedup-llm") =>
    j(`/api/graphs/${id}/agents/${name}/run`, { method: "POST" }),
  suggestSkills: (id: string) =>
    j<{ id: string; name: string }[]>(`/api/graphs/${id}/skills/suggest`, { method: "POST" }),
  resolveDecision: (
    id: string,
    did: string,
    choice: string,
    actor: string,
    editedPayload?: Record<string, unknown>,
  ) =>
    j(`/api/graphs/${id}/decisions/${did}/resolve`, {
      method: "POST",
      body: JSON.stringify({ choice, actor, editedPayload }),
    }),
  pin: (id: string, nodeIds: string[], pinned: boolean) =>
    j(`/api/graphs/${id}/pin`, { method: "POST", body: JSON.stringify({ nodeIds, pinned }) }),
  compileSkill: (id: string, body: Record<string, unknown>) =>
    j(`/api/graphs/${id}/skills/compile`, { method: "POST", body: JSON.stringify(body) }),
  listSkills: (id: string) => j<{ id: string; name: string }[]>(`/api/graphs/${id}/skills`),
  runSkill: (id: string, skillId: string, nodeIds: string[], actor: string, confirmDestructive = false) =>
    j(`/api/graphs/${id}/skills/${skillId}/run`, {
      method: "POST",
      body: JSON.stringify({ scope: { kind: "selection", nodeIds }, actor, confirmDestructive }),
    }),
};
