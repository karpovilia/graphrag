import type { Edge, Node } from "../domain/graph.js";
import type { Id } from "../domain/types.js";
import type { GraphState } from "./state.js";
import type { Axis } from "./temporal.js";

/** One bucket on the scrubber axis (mirrors graphrag's IngestionEvent §2.1):
 *  an instant where graph activity happened, with a magnitude that drives the
 *  activity heatmap. `eventCount` = births + retirements at that instant. */
export interface TimelineEvent {
  id: string;
  /** ISO instant on the chosen axis. */
  at: string;
  /** Human label (defaults to the instant; the UI formats it). */
  label: string;
  bornCount: number;
  deadCount: number;
  /** Curation ops recorded at this instant (tx axis only) — the change-log
   *  activity the paper treats as the unit of analysis. */
  opCount: number;
  /** Activity magnitude (born + dead + ops) — normalised to the busiest
   *  bucket for the heatmap intensity. */
  eventCount: number;
}

export interface Timeline {
  axis: Axis;
  /** Buckets sorted ascending by `at`. */
  events: TimelineEvent[];
  /** Elements live before the timeline begins (timeless / no from-stamp) —
   *  the scrubber's leading "⋯" genesis cell selects these. */
  genesisCount: number;
  genesisNodeIds: Id[];
  min: string | null;
  max: string | null;
}

/** Quantization unit for the activity heatmap. */
export type Bucket = "instant" | "hour" | "day" | "week" | "month" | "quarter" | "year";
/** Per-interval quantization override: instants in [from, to] use `bucket`. */
export interface QuantSegment { from?: string | null; to?: string | null; bucket: Bucket }
export interface TimelineOpts {
  /** Global quantization (default "instant" = exact stamps; "auto" picks one). */
  bucket?: Bucket | "auto";
  /** Per-interval overrides — different quantization in different intervals. */
  segments?: QuantSegment[];
  /** Target bucket count for "auto". */
  targetBuckets?: number;
}

const DAY = 86400000;
const BUCKET_MS: Record<Exclude<Bucket, "instant">, number> = {
  hour: 3600000, day: DAY, week: 7 * DAY, month: 30 * DAY, quarter: 91 * DAY, year: 365 * DAY,
};
const FINE_TO_COARSE: Exclude<Bucket, "instant">[] = ["hour", "day", "week", "month", "quarter", "year"];

/** Floor an epoch-ms to the start of its bucket (UTC). */
function floorTo(ms: number, b: Bucket): number {
  if (b === "instant") return ms;
  const d = new Date(ms);
  d.setUTCMilliseconds(0); d.setUTCSeconds(0); d.setUTCMinutes(0);
  if (b === "hour") return d.getTime();
  d.setUTCHours(0);
  if (b === "day") return d.getTime();
  if (b === "week") { const dow = (d.getUTCDay() + 6) % 7; return d.getTime() - dow * DAY; } // Monday
  d.setUTCDate(1);
  if (b === "month") return d.getTime();
  if (b === "quarter") { d.setUTCMonth(Math.floor(d.getUTCMonth() / 3) * 3); return d.getTime(); }
  d.setUTCMonth(0); // year
  return d.getTime();
}

/** Derive the activity timeline from the graph's bi-temporal stamps. On the
 *  `tx` axis a bucket forms at every txFrom/txTo; on `valid`, at every
 *  validFrom/validTo. Quantization is configurable (global + per-interval). Pure. */
export function buildTimeline(state: GraphState, axis: Axis, opts: TimelineOpts = {}): Timeline {
  const fromOf = (o: Node | Edge): string | null =>
    (axis === "tx" ? o.txFrom : o.validFrom) ?? null;
  const toOf = (o: Node | Edge): string | null =>
    (axis === "tx" ? o.txTo : o.validTo) ?? null;

  const born = new Map<string, number>();
  const dead = new Map<string, number>();
  const ops = new Map<string, number>();
  const bump = (m: Map<string, number>, k: string | null) => {
    if (k) m.set(k, (m.get(k) ?? 0) + 1);
  };
  for (const o of [...state.nodes, ...state.edges]) {
    bump(born, fromOf(o));
    bump(dead, toOf(o));
  }
  // The journal's createdAt is transaction time — fold each recorded op into
  // the tx-axis heatmap so curation activity always shows as a dated cell,
  // even when the applier re-stamps elements at import time.
  if (axis === "tx") {
    for (const e of state.journal) bump(ops, e.createdAt);
  }

  // ── quantization: resolve the default bucket (handle "auto") ──
  const rawMs = [...new Set([...born.keys(), ...dead.keys(), ...ops.keys()])]
    .map((s) => Date.parse(s)).filter((n) => !Number.isNaN(n));
  let defBucket: Bucket = opts.bucket && opts.bucket !== "auto" ? opts.bucket : "instant";
  if (opts.bucket === "auto" && rawMs.length > 1) {
    const span = Math.max(...rawMs) - Math.min(...rawMs);
    const target = opts.targetBuckets ?? 48;
    defBucket = "year";
    for (const b of FINE_TO_COARSE) if (span / BUCKET_MS[b] <= target) { defBucket = b; break; }
  }
  const segs = (opts.segments ?? []).map((s) => ({
    from: s.from ? Date.parse(s.from) : -Infinity,
    to: s.to ? Date.parse(s.to) : Infinity,
    bucket: s.bucket,
  }));
  const bucketFor = (ms: number): Bucket => {
    for (const s of segs) if (ms >= s.from && ms <= s.to) return s.bucket;
    return defBucket;
  };

  // aggregate born/dead/ops into quantized buckets
  const agg = (src: Map<string, number>, dst: Map<number, number>) => {
    for (const [at, c] of src) {
      const ms = Date.parse(at);
      if (Number.isNaN(ms)) continue;
      const k = floorTo(ms, bucketFor(ms));
      dst.set(k, (dst.get(k) ?? 0) + c);
    }
  };
  const qb = new Map<number, number>(), qd = new Map<number, number>(), qo = new Map<number, number>();
  agg(born, qb); agg(dead, qd); agg(ops, qo);
  const keys = [...new Set([...qb.keys(), ...qd.keys(), ...qo.keys()])].sort((a, b) => a - b);
  const events: TimelineEvent[] = keys.map((k) => {
    const at = new Date(k).toISOString();
    const b = qb.get(k) ?? 0, d = qd.get(k) ?? 0, o = qo.get(k) ?? 0;
    return { id: at, at, label: at, bornCount: b, deadCount: d, opCount: o, eventCount: b + d + o };
  });

  const genesisNodeIds = state.nodes.filter((n) => fromOf(n) == null).map((n) => n.id);

  return {
    axis,
    events,
    genesisCount: genesisNodeIds.length,
    genesisNodeIds,
    min: events[0]?.at ?? null,
    max: events[events.length - 1]?.at ?? null,
  };
}
