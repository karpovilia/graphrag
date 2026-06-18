import type { GraphState } from "../engine/state.js";
import { FACTMETA_KEY } from "./graph.js";

/** The graph's single, extensible data model — derived from the data and
 *  stored as a JSON-Schema-shaped document (per-entity-type object schemas
 *  with x-* UI hints). Drives the schema-driven dossier card. */
export interface SchemaField {
  key: string;
  title: string;
  type: "string" | "number" | "date" | "boolean" | "ref";
  icon?: string;
  /** Show in the left brief (and the in-graph compact card). */
  summary?: boolean;
  /** Repeatable (e.g. multiple phone numbers / linked entities). */
  multi?: boolean;
  /** For type=ref: the relation it materializes as. */
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

const INTERNAL_ATTRS = new Set([
  FACTMETA_KEY, "text", "descriptions", "sourceChunkIds", "mentions", "rawWeight",
  "mentionCount", "charStart", "charEnd", "length", "documentId", "algorithm",
  "size", "local_keys", "global_keys", "confidenceScore",
]);

const ICONS: Record<string, string> = {
  PERSON: "👤", ORG: "🏢", PLACE: "📍", EVENT: "📅", CONCEPT: "💡",
  OBJECT: "📦", COMMUNITY: "◎", CHUNK: "📄", MISC: "▪",
};
const DATE_RE = /^\d{4}-\d{2}-\d{2}|^\d{2}[./]\d{2}[./]\d{4}/;

function fieldType(v: unknown): SchemaField["type"] {
  if (typeof v === "number") return "number";
  if (typeof v === "boolean") return "boolean";
  if (typeof v === "string" && DATE_RE.test(v)) return "date";
  return "string";
}

/** Infer the graph's schema from the live state: group entity nodes by type,
 *  collect their attributes as scalar fields and their outgoing relations as
 *  ref sections. Heuristic but reflects the real data. */
export function deriveSchema(state: GraphState): GraphSchema {
  const byType = new Map<string, typeof state.nodes>();
  for (const n of state.nodes) {
    if (n.layer === "chunk") continue;
    (byType.get(n.type) ?? byType.set(n.type, []).get(n.type)!).push(n);
  }
  const nameByType = (id: string) => state.nodes.find((n) => n.id === id)?.type ?? "?";

  const entityTypes: Record<string, EntityTypeSchema> = {};
  for (const [type, nodes] of byType) {
    const ids = new Set(nodes.map((n) => n.id));

    // scalar fields = union of attribute keys (first-seen value sets the type)
    const fields = new Map<string, SchemaField>();
    for (const n of nodes) {
      for (const [k, v] of Object.entries(n.attributes)) {
        if (INTERNAL_ATTRS.has(k) || k.startsWith("_")) continue;
        if (!fields.has(k)) fields.set(k, { key: k, title: k, type: fieldType(v) });
      }
    }
    const fieldArr = [...fields.values()];
    if (fieldArr.length) fieldArr[0]!.summary = true; // first field into the brief

    // ref sections = distinct (relation|edgeType, targetType) on outgoing edges
    const refs = new Map<string, SchemaField>();
    for (const e of state.edges) {
      if (e.invalidation) continue;
      const out = ids.has(e.sourceId);
      const inn = ids.has(e.targetId);
      if (!out && !inn) continue;
      if (e.type === "mentioned_in") continue;
      const otherType = nameByType(out ? e.targetId : e.sourceId);
      const pred = e.relation ?? e.type;
      const key = `${pred}__${otherType}`;
      if (!refs.has(key)) {
        refs.set(key, {
          key,
          title: `${pred} · ${otherType}`,
          type: "ref",
          multi: true,
          icon: ICONS[otherType],
          ref: { entityType: otherType, edgeType: e.type, relation: e.relation ?? null },
          summary: true,
        });
      }
    }

    const sections: SchemaSection[] = [];
    if (fieldArr.length) sections.push({ key: "fields", title: "Данные", fields: fieldArr });
    if (refs.size) sections.push({ key: "relations", title: "Связи", fields: [...refs.values()] });

    entityTypes[type] = { type, title: type, icon: ICONS[type] ?? "▪", sections };
  }

  return { $schema: "https://json-schema.org/draft-07/schema#", entityTypes };
}
