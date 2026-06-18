import type { Edge, Node } from "../domain/graph.js";
import type { Id } from "../domain/types.js";

/** One date-bearing fact about a node (a relationship edge, or the node's own
 *  lifespan) with any implausible-range issues and proposed boundary fixes. */
export interface DateFact {
  kind: "edge" | "node";
  id: Id;
  /** Human label, e.g. "works at → Alfa-Bank" or "Dmitry Vetrov (lifespan)". */
  label: string;
  validFrom: string | null;
  validTo: string | null;
  issues: DateIssue[];
  /** Each fix shifts ONE boundary; the human picks left or right. */
  suggestions: DateFix[];
}

export interface DateIssue {
  code: "inverted" | "future_start" | "too_long" | "before_source" | "future_end";
  message: string;
  severity: "warn" | "error";
}

export interface DateFix {
  boundary: "start" | "end";
  /** New ISO value for that boundary (null = open / "present"). */
  newValue: string | null;
  rationale: string;
}

const YEAR_MS = 365.25 * 24 * 3600 * 1000;
const yearOf = (iso: string) => new Date(iso).getUTCFullYear();
const iso = (year: number) => `${String(year).padStart(4, "0")}-01-01T00:00:00.000Z`;

/** Default plausibility bounds. `maxSpanYears` is the longest a relationship
 *  fact (a role, membership, partnership) can plausibly stay open. */
export interface AuditOpts {
  nowIso: string;
  maxSpanYears?: number;
  /** typical span to propose when shifting a boundary inward. */
  typicalSpanYears?: number;
}

function auditRange(
  validFrom: string | null,
  validTo: string | null,
  sourceBorn: string | null,
  o: Required<Pick<AuditOpts, "nowIso" | "maxSpanYears" | "typicalSpanYears">>,
): { issues: DateIssue[]; suggestions: DateFix[] } {
  const issues: DateIssue[] = [];
  const suggestions: DateFix[] = [];
  if (!validFrom && !validTo) return { issues, suggestions };

  const fromT = validFrom ? Date.parse(validFrom) : null;
  const toT = validTo ? Date.parse(validTo) : null;
  const nowT = Date.parse(o.nowIso);
  const endT = toT ?? nowT; // open-ended = "present"

  // 1) inverted range
  if (fromT != null && toT != null && fromT > toT) {
    issues.push({ code: "inverted", message: "Start is after end.", severity: "error" });
    suggestions.push({ boundary: "end", newValue: null, rationale: "Drop the end (treat as ongoing)." });
    suggestions.push({ boundary: "start", newValue: validTo, rationale: "Move start to the end date." });
    return { issues, suggestions };
  }
  // 2) start in the future
  if (fromT != null && fromT > nowT) {
    issues.push({ code: "future_start", message: "Start is in the future.", severity: "warn" });
    suggestions.push({ boundary: "start", newValue: o.nowIso, rationale: "Move start to now." });
  }
  // 3) end in the future (a fact claimed to keep going past now is fine if open;
  //    a concrete future end is suspicious)
  if (toT != null && toT > nowT) {
    issues.push({ code: "future_end", message: "End is in the future.", severity: "warn" });
    suggestions.push({ boundary: "end", newValue: null, rationale: "Make it open-ended (ongoing)." });
  }
  // 4) start before the source entity existed
  if (fromT != null && sourceBorn && fromT < Date.parse(sourceBorn)) {
    issues.push({
      code: "before_source",
      message: "Starts before the entity itself existed.",
      severity: "error",
    });
    suggestions.push({ boundary: "start", newValue: sourceBorn, rationale: "Move start to when the entity began." });
  }
  // 5) implausibly long span (e.g. "since 1933" still open today)
  if (fromT != null) {
    const spanY = (endT - fromT) / YEAR_MS;
    if (spanY > o.maxSpanYears) {
      issues.push({
        code: "too_long",
        message: `Span is ~${Math.round(spanY)} years — implausibly long.`,
        severity: "warn",
      });
      // shift LEFT boundary inward to a typical span before the end…
      suggestions.push({
        boundary: "start",
        newValue: iso(yearOf(new Date(endT).toISOString()) - o.typicalSpanYears),
        rationale: `Shift start to ~${o.typicalSpanYears}y before the end.`,
      });
      // …or cap the RIGHT boundary at a typical span after the start.
      if (toT == null) {
        suggestions.push({
          boundary: "end",
          newValue: iso(yearOf(validFrom!) + o.typicalSpanYears),
          rationale: `Cap the end ~${o.typicalSpanYears}y after the start.`,
        });
      }
    }
  }
  return { issues, suggestions };
}

/** Audit every date-bearing fact touching `node`: its incident relationship
 *  edges and its own lifespan. Returns only facts that HAVE dates (the panel
 *  shows them; issues+suggestions are empty when the range looks fine). */
export function auditNodeDates(
  node: Node,
  edges: Edge[],
  nodesById: Map<Id, Node>,
  opts: AuditOpts,
): DateFact[] {
  const o = {
    nowIso: opts.nowIso,
    maxSpanYears: opts.maxSpanYears ?? 80,
    typicalSpanYears: opts.typicalSpanYears ?? 25,
  };
  const facts: DateFact[] = [];

  // node lifespan
  if (node.validFrom || node.validTo) {
    const r = auditRange(node.validFrom ?? null, node.validTo ?? null, null, o);
    facts.push({
      kind: "node",
      id: node.id,
      label: `${node.name} (lifespan)`,
      validFrom: node.validFrom ?? null,
      validTo: node.validTo ?? null,
      issues: r.issues,
      suggestions: r.suggestions,
    });
  }

  // incident relationship edges
  for (const e of edges) {
    if (e.sourceId !== node.id && e.targetId !== node.id) continue;
    if (!e.validFrom && !e.validTo) continue; // only date-bearing facts
    const otherId = e.sourceId === node.id ? e.targetId : e.sourceId;
    const other = nodesById.get(otherId);
    const sourceBorn = nodesById.get(e.sourceId)?.validFrom ?? null;
    const r = auditRange(e.validFrom ?? null, e.validTo ?? null, sourceBorn, o);
    facts.push({
      kind: "edge",
      id: e.id,
      label: `${e.relation ?? e.type} → ${other?.name ?? otherId}`,
      validFrom: e.validFrom ?? null,
      validTo: e.validTo ?? null,
      issues: r.issues,
      suggestions: r.suggestions,
    });
  }
  return facts;
}
