/** Minimal provider-agnostic LLM surface. Concrete adapters
 *  (anthropic / openai-compat for deepseek+z.ai / GLM) implement these.
 *  graph-core only depends on the interface; structural curation never
 *  needs an implementation. */

export interface Message {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface CompletionParams {
  temperature?: number;
  maxTokens?: number;
  /** Ask the provider for a JSON object response when supported. */
  jsonObject?: boolean;
  model?: string;
}

export interface CompletionClient {
  provider: string;
  complete(
    messages: Message[],
    params?: CompletionParams,
  ): Promise<{ text: string }>;
}

export interface EmbeddingClient {
  provider: string;
  embed(texts: string[]): Promise<number[][]>;
}

/** Tolerant JSON parse: handles ```json fences and leading prose a
 *  thinking model may emit. Returns null on failure. */
export function extractJson(text: string): unknown {
  if (!text) return null;
  let s = text.trim();
  if (s.startsWith("```")) {
    s = s.replace(/^```(json)?/i, "").replace(/```$/, "").trim();
  }
  try {
    return JSON.parse(s);
  } catch {
    /* fall through */
  }
  const start = s.indexOf("{");
  const end = s.lastIndexOf("}");
  if (start >= 0 && start < end) {
    try {
      return JSON.parse(s.slice(start, end + 1));
    } catch {
      return null;
    }
  }
  return null;
}
