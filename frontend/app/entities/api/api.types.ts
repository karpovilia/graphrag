// TypeScript shapes for the R2 backend domain model. Hand-mirrored
// from `backend/api/domain/` Pydantic v2 models — no codegen yet, so
// updates here track changes in the backend manually. Each section
// has a comment pointing to its source module.

export type Id = string; // UUID v4 string

// ---- corpus + document (api/domain/corpus.py) ----

export type Corpus = {
  id: Id;
  name: string;
  description: string | null;
  language: string;
  document_count: number;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type Document = {
  id: Id;
  corpus_id: Id;
  title: string;
  source_uri: string | null;
  language: string;
  char_length: number;
  sha256: string;
  text?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
};

// ---- corpus schema (api/domain/schema.py) ----

export type EntityTypeDef = {
  name: string;
  description: string;
  examples: string[];
  suggested_color?: string | null;
};

export type RelationTypeDef = {
  name: string;
  description: string;
  domain: string[];
  range: string[];
  symmetric: boolean;
  examples: string[];
};

export type CorpusSchema = {
  entity_types: EntityTypeDef[];
  relation_types: RelationTypeDef[];
  proposed_by?: string | null;
  version: number;
};

export type ProposeSchemaRequest = {
  sample_size?: number;
  sample_chunk_size?: number;
  seed?: number;
};

// ---- graph (api/domain/graph.py) ----

export type Layer = "chunk" | "entity" | "community" | "topic";

export type EdgeType =
  | "mentioned_in"
  | "member_of"
  | "summary_of"
  | "entity_relation"
  | "backbone"
  | "derived";

export type GraphVariantStatus =
  | "pending"
  | "building"
  | "ready"
  | "failed"
  | "archived";

export type GraphVariant = {
  id: Id;
  corpus_id: Id;
  name: string;
  status: GraphVariantStatus;
  builder: string;
  cleaner_chain: string[];
  clusterer: string | null;
  summarizer: string | null;
  config: Record<string, unknown>;
  llm_models: Record<string, string>;
  seed: number | null;
  node_count: number;
  edge_count: number;
  layers_present: Layer[];
  parent_variant_id: Id | null;
  version: number;
  created_at: string;
  completed_at: string | null;
};

export type Provenance = {
  document_id: Id;
  span_start: number;
  span_end: number;
  extracted_by_run_id: Id | null;
  confidence: number | null;
};

export type Node = {
  id: Id;
  graph_variant_id: Id;
  canonical_id: Id | null;
  layer: Layer;
  type: string;
  granularity: number;
  name: string;
  summary: string | null;
  attributes: Record<string, unknown>;
  provenance: Provenance[];
  embedding: { model: string; dim: number; collection: string; vector_id: string } | null;
  // Bitemporal stamps (api/domain/graph.py:108-117). valid_* = event
  // time ("when it was true"); tx_* = transaction time ("when we learned
  // it"). null upper bound = "still valid" / "still current". Read-only
  // here — surfaced by the §2.5 temporal-history block in NodeDrawer.
  valid_from: string | null;
  valid_to: string | null;
  tx_from: string | null;
  tx_to: string | null;
};

export type Edge = {
  id: Id;
  graph_variant_id: Id;
  type: EdgeType;
  source_node_id: Id;
  target_node_id: Id;
  weight: number | null;
  relation: string | null;
  explanation: string | null;
  provenance: Provenance[];
  attributes: Record<string, unknown>;
  // Bitemporal stamps (api/domain/graph.py:136-143), same axes as Node.
  valid_from: string | null;
  valid_to: string | null;
  tx_from: string | null;
  tx_to: string | null;
  // §2.4 invalidation provenance: present when this edge was superseded
  // by a later ingestion. Surfaced in InvalidationPanel (revert target).
  invalidation?: EdgeInvalidation | null;
};

export type VariantStateSummary = {
  variant_id: Id;
  version: number;
  node_count: number;
  edge_count: number;
  nodes_by_layer: Partial<Record<Layer, number>>;
  edges_by_type: Partial<Record<EdgeType, number>>;
};

// ---- curation (api/domain/curation.py) ----

export type JournalOp =
  | "merge_nodes"
  | "split_node"
  | "retype_node"
  | "move_to_community"
  | "edit_edge"
  | "delete_edge"
  | "delete_node"
  | "add_edge"
  | "set_summary"
  | "update_node_name";

export type JournalEntry = {
  id: Id;
  graph_variant_id: Id;
  op: JournalOp;
  payload: Record<string, unknown>;
  actor: string;
  parent_entry_id: Id | null;
  created_at: string;
};

export type SuggestionAction =
  | "merge"
  | "split"
  | "retype"
  | "move"
  | "delete"
  | "edit_relation";

export type SuggestionStatus = "pending" | "accepted" | "rejected" | "expired";

export type Suggestion = {
  id: Id;
  graph_variant_id: Id;
  agent: string;
  action: SuggestionAction;
  target_node_ids: Id[];
  target_edge_ids: Id[];
  payload: Record<string, unknown>;
  confidence: number;
  rationale: string;
  evidence: Provenance[];
  cost_estimate_tokens: number | null;
  status: SuggestionStatus;
  created_at: string;
  decided_at: string | null;
  resulting_journal_entry_id: Id | null;
};

// ---- runs + tools (api/domain/run.py) ----

export type ToolInvocation = {
  id: Id;
  node_id: Id;
  tool: string;
  arguments: Record<string, unknown>;
  result: Record<string, unknown>;
  cost_tokens: number | null;
  created_at: string;
  expires_at: string | null;
};

// ---- strategies (api/strategies/descriptor.py) ----

export type Kind =
  | "builder"
  | "cleaner"
  | "clusterer"
  | "summarizer"
  | "projector"
  | "reasoner"
  | "agent"
  | "tool"
  | "aggregator"
  | "ranker";

export type StrategyDescriptor = {
  kind: Kind;
  name: string;
  summary: string;
  description: string;
  requires_layers: Layer[];
  produces_layers: Layer[];
  params_schema: Record<string, unknown>;
  cost_hint: "cheap" | "moderate" | "expensive" | null;
  references: string[];
};

// ---- EDA (api/eda/report.py) ----

export type DocumentStats = {
  document_count: number;
  total_chars: number;
  mean_chars: number;
  median_chars: number;
  p95_chars: number;
};

export type EntityFrequency = { lemma: string; type: string; count: number };

export type NodeTypeRecommendation = {
  name: string;
  label: string;
  evidence_count: number;
  suggested_color: string | null;
};

export type Recommendation = {
  builder: string;
  cleaner_chain: string[];
  clusterer: string;
  summarizer: string | null;
  node_types: NodeTypeRecommendation[];
  rationale: string;
};

export type EdaReport = {
  id: Id;
  corpus_id: Id;
  created_at: string;
  document_stats: DocumentStats;
  entity_density_per_1k_chars: number;
  morphological_dispersion: number;
  top_entities: EntityFrequency[];
  recommendation: Recommendation;
};

// ---- reason / MoE (api/strategies/protocols.py + api/moe.py) ----

export type ReasonResult = {
  text: string;
  evidence_node_ids: Id[];
  evidence_edge_ids: Id[];
  confidence: number | null;
  cost_tokens: number;
  metadata: Record<string, unknown>;
};

export type ExpertResult = {
  variant_id: Id;
  reasoner: string;
  result: ReasonResult;
  error: string | null;
};

export type MoEResult = {
  answer: ReasonResult;
  experts: ExpertResult[];
  aggregator: string;
};

export type ReasonMode = "single" | "moe";

// ---- API request bodies ----

export type LLMOverride = {
  /** Optional for local OpenAI-compatible servers (Ollama, llama.cpp). */
  api_key?: string;
  base_url: string;
  model: string;
};

export type BuildVariantRequest = {
  name: string;
  builder: string;
  cleaner_chain?: string[];
  clusterer?: string | null;
  builder_params?: Record<string, unknown>;
  cleaner_params?: Record<string, Record<string, unknown>>;
  clusterer_params?: Record<string, unknown>;
  /** Post-clusterer stage that derives intra-layer co-occurrence edges
   * via PMI + disparity filter. `null` skips this stage. */
  projector?: string | null;
  projector_params?: Record<string, unknown>;
  seed?: number | null;
  /** Language used by the pipeline to normalise entity names and
   * generate summaries. Backend default is "ru". */
  output_language?: "ru" | "en";
  /** Bring-your-own-token: when set, the pipeline uses this endpoint
   * for LLM calls instead of the server default. Not persisted. */
  llm_override?: LLMOverride | null;
};

export type ReasonRequest = {
  mode: ReasonMode;
  query: string;
  variant_ids: Id[];
  reasoner?: string;
  reasoner_params?: Record<string, unknown>;
  aggregator?: string;
  aggregator_params?: Record<string, unknown>;
};

export type JournalAppendRequest = {
  op: JournalOp;
  payload: Record<string, unknown>;
  expected_version: number;
  actor: string;
};

export type JournalAppendResult = {
  variant: GraphVariant;
  entry: JournalEntry;
  affected: { node_ids: Id[]; edge_ids: Id[]; community_ids: Id[] };
  /** Wall-clock (ms) of apply + affected-set recompute. Always present
   * and >= 0 so the §2.3 latency badge never reads undefined. */
  recompute_ms: number;
};

// ---- temporal (bitemporal timeline + diff, api contract §2.1/§2.4) ----

/** Which time axis the scrubber walks. `tx` = transaction time
 * (ingested_at, "when did we learn it"); `valid` = valid / event time
 * (event_time, "when was it true"). ADR-0002 distinction. */
export type TimeAxis = "tx" | "valid";

export type IngestionEvent = {
  id: Id;
  corpus_id: Id;
  graph_variant_id: Id | null;
  label: string;
  /** ISO-8601 UTC Z. */
  event_time: string;
  /** ISO-8601 UTC Z. */
  ingested_at: string;
  source_uri: string | null;
  kind: string;
  /** Number of underlying source events in this bucket (activity histogram). */
  event_count: number;
  metadata: Record<string, unknown>;
};

/** GET /at — the set of facts live at instant t under the chosen axis. */
export type AtSnapshot = {
  variant_id: Id;
  axis: TimeAxis;
  t: string;
  node_ids: Id[];
  edge_ids: Id[];
};

export type EdgeInvalidation = {
  ingestion_event_id: Id;
  /** ISO-8601 UTC Z. */
  at: string;
  reason: string;
  superseded_by_edge_id: Id | null;
  auto: boolean;
};

export type DeltaItemKind = "node" | "edge";
export type DeltaItemState =
  | "born"
  | "dead"
  | "persisted"
  | "moved_community"
  | "invalidated";

export type DeltaItem = {
  id: Id;
  kind: DeltaItemKind;
  state: DeltaItemState;
  /** Present only for moved_community. */
  from_community_id?: Id;
  to_community_id?: Id;
  /** Present only for invalidated. */
  invalidation?: EdgeInvalidation;
};

/** GET /diff — every id maps 1:1 to a §0 grammar color. `dead` =
 * vanished without provenance; `invalidated` = vanished WITH an
 * EdgeInvalidation record (§2.4 revert candidates, disjoint from dead). */
export type TemporalDiff = {
  variant_id: Id;
  axis: TimeAxis;
  t_a: string;
  t_b: string;
  born: DeltaItem[];
  dead: DeltaItem[];
  persisted: DeltaItem[];
  moved_community: DeltaItem[];
  invalidated: DeltaItem[];
  counts: {
    born: number;
    dead: number;
    persisted: number;
    moved_community: number;
    invalidated: number;
  };
};

/** POST /api/reason/delta — deterministic evidence highlight (§2.2). */
export type QueryDeltaResponse = {
  moe: MoEResult;
  variant_id: Id;
  evidence_node_ids: Id[];
  evidence_edge_ids: Id[];
  total_node_ids: Id[];
  total_edge_ids: Id[];
};

/** GET /projection-importance — ranking of latent two-mode projections. */
export type ProjectionStat = {
  name: string;
  n_nodes: number;
  n_pairs: number;
  total_weight: number;
  unique_pair_fraction: number;
  distinctiveness_overlap: number;
  von_neumann_entropy: number | null;
  distinctiveness_jsd: number | null;
};

export type ProjectionImportanceResult = {
  variant_id: Id;
  projections: ProjectionStat[];
  most_redundant_pair: string[] | null;
  spectral_computed: boolean;
  note: string | null;
};

export type GraphLayout = {
  positions: Record<string, [number, number]>;
  owner: "self" | "global";
};

// On-the-fly two-mode layer-pair projection (#6).
export type ProjectionOption = {
  target_layer: string;
  via: string;
  neighbor_layer: string;
  label: string;
  edge_count: number;
};

export type ProjectionEdge = {
  source_node_id: Id;
  target_node_id: Id;
  weight: number;
  raw_count: number;
};

export type ProjectionResult = {
  target_layer: string;
  via: string;
  neighbor_layer: string;
  normalization: string;
  edges: ProjectionEdge[];
};

// Conversational curation assistant — free-text instructions over a variant.
export type AssistantChatMessage = {
  role: "user" | "assistant";
  content: string;
};

export type AssistantRequest = {
  message: string;
  selected_node_ids?: string[];
  slice_node_ids?: string[];
  highlighted_node_ids?: string[];
  history?: AssistantChatMessage[];
  expected_version: number;
  actor?: string;
};

export type AppliedOp = {
  op: string;
  payload: Record<string, unknown>;
  ok: boolean;
  error?: string | null;
};

export type AssistantResponse = {
  message: string;
  applied: AppliedOp[];
  highlight: string[];
  variant: GraphVariant;
  recompute_ms: number;
};
