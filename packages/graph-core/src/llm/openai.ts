import type {
  CompletionClient,
  CompletionParams,
  EmbeddingClient,
  Message,
} from "./base.js";

/** OpenAI-compatible chat client (works with Deepseek, z.ai/GLM, Ollama,
 *  vLLM, OpenAI…). Uses global fetch — no SDK dependency. */
export class OpenAICompatClient implements CompletionClient {
  readonly provider: string;
  readonly model: string;
  private baseUrl: string;
  private apiKey: string;

  constructor(cfg: { provider: string; baseUrl: string; apiKey: string; model: string }) {
    this.provider = cfg.provider;
    this.baseUrl = cfg.baseUrl.replace(/\/$/, "");
    this.apiKey = cfg.apiKey;
    this.model = cfg.model;
  }

  async complete(
    messages: Message[],
    params: CompletionParams = {},
  ): Promise<{ text: string }> {
    const body: Record<string, unknown> = {
      model: params.model ?? this.model,
      messages,
      temperature: params.temperature ?? 0,
      max_tokens: params.maxTokens ?? 2000,
    };
    if (params.jsonObject) body.response_format = { type: "json_object" };

    const res = await fetch(`${this.baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${this.apiKey}`,
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      throw new Error(`LLM ${this.provider} ${res.status}: ${await res.text()}`);
    }
    const json = (await res.json()) as {
      choices?: { message?: { content?: string } }[];
    };
    return { text: json.choices?.[0]?.message?.content ?? "" };
  }
}

/** OpenAI-compatible embeddings client (tier-2 candidate ranking). */
export class OpenAICompatEmbeddings implements EmbeddingClient {
  readonly provider: string;
  private baseUrl: string;
  private apiKey: string;
  private model: string;

  constructor(cfg: { provider: string; baseUrl: string; apiKey: string; model: string }) {
    this.provider = cfg.provider;
    this.baseUrl = cfg.baseUrl.replace(/\/$/, "");
    this.apiKey = cfg.apiKey;
    this.model = cfg.model;
  }

  async embed(texts: string[]): Promise<number[][]> {
    const res = await fetch(`${this.baseUrl}/embeddings`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${this.apiKey}`,
      },
      body: JSON.stringify({ model: this.model, input: texts }),
    });
    if (!res.ok) {
      throw new Error(`Embeddings ${this.provider} ${res.status}: ${await res.text()}`);
    }
    const json = (await res.json()) as { data?: { embedding: number[] }[] };
    return (json.data ?? []).map((d) => d.embedding);
  }
}

type Env = Record<string, string | undefined>;

/** Provider registry with env auto-detect. Priority: an explicit LLM_*
 *  override, then Deepseek (the plan's default), then z.ai/GLM, then OpenAI.
 *  Returns null when no key is configured — callers fall back to the keyless
 *  heuristic path. */
export function createLLM(env: Env = process.env): CompletionClient | null {
  const pick = (
    provider: string,
    keyVar: string,
    baseDefault: string,
    modelDefault: string,
    baseVar = `${provider.toUpperCase()}_BASE_URL`,
    modelVar = `${provider.toUpperCase()}_MODEL`,
  ): CompletionClient | null => {
    const apiKey = env[keyVar];
    if (!apiKey) return null;
    return new OpenAICompatClient({
      provider,
      apiKey,
      baseUrl: env[baseVar] ?? baseDefault,
      model: env[modelVar] ?? modelDefault,
    });
  };

  // generic override
  if (env.LLM_API_KEY && env.LLM_BASE_URL) {
    return new OpenAICompatClient({
      provider: env.LLM_PROVIDER ?? "custom",
      apiKey: env.LLM_API_KEY,
      baseUrl: env.LLM_BASE_URL,
      model: env.LLM_MODEL ?? "default",
    });
  }
  return (
    pick("deepseek", "DEEPSEEK_API_KEY", "https://api.deepseek.com", "deepseek-chat") ??
    pick("zai", "ZAI_API_KEY", "https://api.z.ai/api/paas/v4", "glm-4-plus") ??
    pick("glm", "GLM_API_KEY", "http://localhost:8000/v1", "glm-4") ??
    pick("openai", "OPENAI_API_KEY", "https://api.openai.com/v1", "gpt-4o-mini")
  );
}

/** Embeddings registry (OpenAI-compat). Null when unconfigured. */
export function createEmbeddings(env: Env = process.env): EmbeddingClient | null {
  const apiKey = env.EMBEDDINGS_API_KEY ?? env.OPENAI_API_KEY;
  if (!apiKey) return null;
  return new OpenAICompatEmbeddings({
    provider: env.EMBEDDINGS_PROVIDER ?? "openai",
    apiKey,
    baseUrl: env.EMBEDDINGS_BASE_URL ?? "https://api.openai.com/v1",
    model: env.EMBEDDINGS_MODEL ?? "text-embedding-3-small",
  });
}
