// Typed thin client over the R2 FastAPI backend.
//
// All call sites go through here so endpoint paths live in one place.
// `useApi()` is the Vue composable to use from components — it picks
// up `runtimeConfig.public.apiBase` so dev/prod swap with one env var.

import { useRuntimeConfig } from "nuxt/app";

import type {
  BuildVariantRequest,
  Corpus,
  Document,
  EdaReport,
  GraphVariant,
  Id,
  JournalAppendRequest,
  JournalAppendResult,
  JournalEntry,
  Kind,
  MoEResult,
  ReasonRequest,
  StrategyDescriptor,
  Suggestion,
  SuggestionStatus,
  ToolInvocation,
  VariantStateSummary,
} from "@/entities/api";

export type ApiError = {
  status: number;
  message: string;
  body: unknown;
};

class HttpError extends Error implements ApiError {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.status = status;
    this.body = body;
    this.name = "HttpError";
  }
  get message(): string {
    return super.message;
  }
}

export type ApiClient = ReturnType<typeof createApiClient>;

export function createApiClient(baseUrl = "") {
  function url(path: string): string {
    if (baseUrl && !baseUrl.endsWith("/") && !path.startsWith("/")) {
      return `${baseUrl}/${path}`;
    }
    return `${baseUrl}${path}`;
  }

  async function request<T>(
    path: string,
    init: RequestInit = {},
  ): Promise<T> {
    const headers = new Headers(init.headers || {});
    if (init.body && !headers.has("content-type")) {
      headers.set("content-type", "application/json");
    }
    const resp = await fetch(url(path), { ...init, headers });
    if (!resp.ok) {
      let body: unknown = null;
      try {
        body = await resp.json();
      } catch {
        body = await resp.text();
      }
      const message =
        (body && typeof body === "object" && "detail" in body
          ? String((body as { detail: unknown }).detail)
          : `HTTP ${resp.status}`) ?? `HTTP ${resp.status}`;
      throw new HttpError(resp.status, message, body);
    }
    if (resp.status === 204) return undefined as unknown as T;
    return (await resp.json()) as T;
  }

  // ---- strategies ----

  const strategies = {
    listAll: () =>
      request<Record<Kind, StrategyDescriptor[]>>(`/api/strategies`),
    listKind: (kind: Kind) =>
      request<StrategyDescriptor[]>(`/api/${pluralKind(kind)}`),
    describe: (kind: Kind, name: string) =>
      request<StrategyDescriptor>(`/api/strategies/${kind}/${name}`),
  };

  // ---- corpora + documents ----

  const corpora = {
    list: () => request<Corpus[]>(`/api/corpora`),
    create: (body: { name: string; description?: string | null; language?: string }) =>
      request<Corpus>(`/api/corpora`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    get: (id: Id) => request<Corpus>(`/api/corpora/${id}`),
    listDocuments: (id: Id) =>
      request<Document[]>(`/api/corpora/${id}/documents`),
    createDocument: (
      id: Id,
      body: {
        title: string;
        text: string;
        source_uri?: string | null;
        language?: string;
      },
    ) =>
      request<Document>(`/api/corpora/${id}/documents`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    buildVariant: (id: Id, body: BuildVariantRequest) =>
      request<GraphVariant>(`/api/corpora/${id}/graphs`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
  };

  // ---- variants + curation ----

  const graphs = {
    list: (corpusId?: Id) =>
      request<GraphVariant[]>(
        corpusId ? `/api/graphs?corpus_id=${corpusId}` : `/api/graphs`,
      ),
    listNodes: (id: Id, filter: { layer?: string; limit?: number } = {}) => {
      const qs = new URLSearchParams();
      if (filter.layer) qs.set("layer", filter.layer);
      if (filter.limit !== undefined) qs.set("limit", String(filter.limit));
      const tail = qs.toString();
      return request<import("@/entities/api").Node[]>(
        `/api/graphs/${id}/nodes${tail ? `?${tail}` : ""}`,
      );
    },
    listEdges: (id: Id, filter: { type?: string; limit?: number } = {}) => {
      const qs = new URLSearchParams();
      if (filter.type) qs.set("type", filter.type);
      if (filter.limit !== undefined) qs.set("limit", String(filter.limit));
      const tail = qs.toString();
      return request<import("@/entities/api").Edge[]>(
        `/api/graphs/${id}/edges${tail ? `?${tail}` : ""}`,
      );
    },
    get: (id: Id) => request<GraphVariant>(`/api/graphs/${id}`),
    state: (id: Id) => request<VariantStateSummary>(`/api/graphs/${id}/state`),
    listJournal: (id: Id, limit?: number) =>
      request<JournalEntry[]>(
        `/api/graphs/${id}/journal${limit ? `?limit=${limit}` : ""}`,
      ),
    appendJournal: (id: Id, body: JournalAppendRequest) =>
      request<JournalAppendResult>(`/api/graphs/${id}/journal`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    undo: (id: Id, body: { expected_version: number }) =>
      request<JournalAppendResult>(`/api/graphs/${id}/undo`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    exportJournalUrl: (id: Id, format: "json" | "csv" = "json") =>
      url(`/api/graphs/${id}/journal/export?format=${format}`),
    preview: (body: {
      corpus_id?: Id;
      documents: { title: string; text: string; language?: string }[];
      builder: string;
      cleaner_chain?: string[];
      clusterer?: string | null;
      builder_params?: Record<string, unknown>;
      cleaner_params?: Record<string, Record<string, unknown>>;
      clusterer_params?: Record<string, unknown>;
    }) =>
      request<unknown>(`/api/graphs/preview`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
  };

  // ---- EDA ----

  const eda = {
    analyze: (body: {
      corpus_id?: Id;
      documents: { id?: Id; text: string }[];
    }) =>
      request<EdaReport>(`/api/eda`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
  };

  // ---- agents + suggestions ----

  const agents = {
    list: () => request<StrategyDescriptor[]>(`/api/agents`),
    run: (
      variantId: Id,
      agentName: string,
      params: Record<string, unknown> = {},
    ) =>
      request<{ agent: string; suggestions: Suggestion[] }>(
        `/api/graphs/${variantId}/agents/${agentName}/run`,
        { method: "POST", body: JSON.stringify({ params }) },
      ),
    listSuggestions: (
      variantId: Id,
      filter: { status?: SuggestionStatus; agent?: string; limit?: number } = {},
    ) => {
      const qs = new URLSearchParams();
      if (filter.status) qs.set("status", filter.status);
      if (filter.agent) qs.set("agent", filter.agent);
      if (filter.limit !== undefined) qs.set("limit", String(filter.limit));
      const tail = qs.toString();
      return request<Suggestion[]>(
        `/api/graphs/${variantId}/suggestions${tail ? `?${tail}` : ""}`,
      );
    },
    accept: (
      suggestionId: Id,
      body: { expected_variant_version: number; actor: string },
    ) =>
      request<JournalAppendResult>(`/api/suggestions/${suggestionId}/accept`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    reject: (suggestionId: Id, body: { actor: string }) =>
      request<Suggestion>(`/api/suggestions/${suggestionId}/reject`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
  };

  // ---- reason (single + MoE) ----

  const reason = {
    run: (body: ReasonRequest) =>
      request<MoEResult>(`/api/reason`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    streamUrl: () => url(`/api/reason/stream`),
  };

  // ---- node tools ----

  const nodes = {
    listTools: (variantId: Id, nodeId: Id) =>
      request<StrategyDescriptor[]>(
        `/api/nodes/${variantId}/${nodeId}/tools`,
      ),
    runTool: (
      variantId: Id,
      nodeId: Id,
      toolName: string,
      params: Record<string, unknown> = {},
    ) =>
      request<ToolInvocation>(
        `/api/nodes/${variantId}/${nodeId}/tools/${toolName}/run`,
        { method: "POST", body: JSON.stringify({ params }) },
      ),
    listToolInvocations: (
      variantId: Id,
      nodeId: Id,
      filter: { tool?: string; limit?: number } = {},
    ) => {
      const qs = new URLSearchParams();
      if (filter.tool) qs.set("tool", filter.tool);
      if (filter.limit !== undefined) qs.set("limit", String(filter.limit));
      const tail = qs.toString();
      return request<ToolInvocation[]>(
        `/api/nodes/${variantId}/${nodeId}/tool_invocations${tail ? `?${tail}` : ""}`,
      );
    },
  };

  return {
    base: baseUrl,
    request,
    strategies,
    corpora,
    graphs,
    eda,
    agents,
    reason,
    nodes,
  };
}

function pluralKind(kind: Kind): string {
  // /api/builders, /api/agents, /api/strategies routes use plural URLs.
  // 'strategy' isn't a kind we list per-kind, so fall through to s-suffix
  // for the rest.
  return `${kind}s`;
}

let _client: ApiClient | undefined;

/** Module-level singleton for places that don't have access to Vue
 * setup context (e.g. server-route handlers, tests). Components should
 * use {@link useApi} instead so the runtimeConfig is honored.
 */
export function getApiClient(baseUrl?: string): ApiClient {
  if (!_client || (baseUrl !== undefined && baseUrl !== _client.base)) {
    _client = createApiClient(baseUrl ?? "");
  }
  return _client;
}

/** Composable used inside components. Reads `runtimeConfig.public.apiBase`
 * once; subsequent calls hand back the same instance.
 */
export function useApi(): ApiClient {
  const config = useRuntimeConfig();
  return getApiClient(String(config.public.apiBase ?? ""));
}
