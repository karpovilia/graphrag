import type { Id } from "./types.js";

/** A project owns a raw SOURCE (a stream of documents) and the PARSING config
 *  that turns it into a shared corpus. Multiple graph variants are built over
 *  the same parsed corpus (corpus → variants, like graphrag). */
export type SourceFormat = "plain" | "chat";

export interface ParseConfig {
  format: SourceFormat;
  /** chunk window (chars) used when graphs are built over the corpus. */
  chunkSize: number;
  chunkOverlap: number;
  /** chat: split each file into per-message documents (time + author). */
  perMessage?: boolean;
}

export const DEFAULT_PARSE: ParseConfig = {
  format: "plain",
  chunkSize: 1200,
  chunkOverlap: 100,
  perMessage: true,
};

export interface ProjectMeta {
  id: Id;
  name: string;
  createdAt: string;
  parse: ParseConfig;
  /** human description of where the source came from (dir, paste, …). */
  source?: string | null;
  documentCount: number;
}

/** A parsed unit of the corpus: a whole file (plain) or one chat message. */
export interface ParsedDocument {
  id: Id;
  uri: string;
  text: string;
  /** event time (chat message timestamp) → feeds valid-time. */
  validFrom?: string | null;
  author?: string | null;
}

export interface RawFile {
  uri: string;
  text: string;
}

// "2025-11-10 14:31:58 Author Name" — a mattermost/chat message header line.
const MSG_HEAD = /^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})\s+(.+?)\s*$/;

function tsToIso(date: string, time: string): string {
  return `${date}T${time}.000Z`;
}

/** Split one chat file into messages (timestamp + author + text). Lines until
 *  the next header belong to the current message; a leading "text:" is dropped. */
export function parseChat(uri: string, text: string): ParsedDocument[] {
  const out: ParsedDocument[] = [];
  let cur: { ts: string; author: string; lines: string[] } | null = null;
  let i = 0;
  const flush = () => {
    if (!cur) return;
    const body = cur.lines.join("\n").replace(/^\s*text:\s*/i, "").trim();
    if (body) out.push({ id: `${uri}#${i++}`, uri, text: body, validFrom: cur.ts, author: cur.author });
    cur = null;
  };
  for (const line of text.split(/\r?\n/)) {
    const m = line.match(MSG_HEAD);
    if (m) {
      flush();
      cur = { ts: tsToIso(m[1]!, m[2]!), author: m[3]!.trim(), lines: [] };
    } else if (cur) {
      cur.lines.push(line);
    }
  }
  flush();
  return out;
}

/** Turn raw files into the parsed corpus per the project's parse config. */
export function parseDocuments(files: RawFile[], cfg: ParseConfig): ParsedDocument[] {
  if (cfg.format === "chat" && cfg.perMessage !== false) {
    return files.flatMap((f) => {
      const msgs = parseChat(f.uri, f.text);
      // a file with no recognizable messages falls back to a single document
      return msgs.length ? msgs : [{ id: f.uri, uri: f.uri, text: f.text }];
    });
  }
  return files.map((f) => ({ id: f.uri, uri: f.uri, text: f.text }));
}
