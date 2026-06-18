import {
  degreeMap,
  layerRegistry,
  materializeAt,
  multiProjection,
  type Axis,
  type GraphMeta,
  type GraphState,
  type Layer,
} from "@graphcraft/core";

/** The wire shape consumed by @krainovsd/graph (the friend's engine). */
export interface RenderGraph {
  name: string;
  graph: {
    nodes: {
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
        _deltaStatus?: string;
      };
    }[];
    links: {
      source: string;
      target: string;
      data: {
        id: string;
        relation?: string | null;
        explanation?: string | null;
        confidence: string;
        tags: string[];
        color: string;
        /** Batagelj projection (derived 2nd-order) edge markers. */
        derived?: boolean;
        from?: string;
        to?: string;
      };
    }[];
    /** Communities are NOT nodes — they're groups (drawn as hulls behind
     *  their member entities). */
    groups: { id: string; name: string; color: string; summary: string | null; memberIds: string[] }[];
    legends: {
      size: string;
      color: { color: string; description: string }[];
      /** Non-entity layers present (chunk/topic/emergent), with live counts. */
      layers: { layer: Layer; color: string; count: number; active: boolean }[];
      /** Entity kinds (node.type) present, with counts — the layer panel's
       *  detail for the entity layer. */
      types: { type: string; color: string; count: number; active: boolean }[];
    };
    settings: { alwaysLabelVisible: boolean };
  };
}

/** View controls applied before serialization. */
export interface RenderOpts {
  /** Visible non-entity layers; empty/undefined = all. */
  layers?: Layer[];
  /** Visible entity kinds (node.type); empty/undefined = all. */
  types?: string[];
  /** ISO instant to time-travel to; undefined/null = current ("live"). */
  asOf?: string | null;
  /** Temporal axis for asOf (default tx = transaction/recorded time). */
  axis?: Axis;
  /** Overlay Batagelj same-layer projections (co-chunk / co-community) as
   *  2nd-order derived edges; mark the nodes they assemble. */
  projections?: boolean;
  /** Time window [from, to]: keep only nodes whose birth (validFrom for the
   *  valid axis, txFrom for tx) falls inside it. Hides everything else. */
  from?: string | null;
  to?: string | null;
}

const LAYER_COLOR: Record<string, string> = {
  chunk: "#9aa0a6",
  entity: "#4f86f7",
  community: "#34a853",
  topic: "#a142f4",
};
// Canonical strata coloured by layer; entity & emergent strata coloured by type.
const COLORED_BY_LAYER = new Set(["chunk", "community", "topic"]);

/** Deterministic colour for an emergent layer with no registry colour. */
function hashColor(s: string): string {
  let h = 0;
  for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return `hsl(${h % 360} 55% 55%)`;
}

// Stable palette for entity types (by first-seen order).
const TYPE_PALETTE = [
  "#4f86f7",
  "#ea4335",
  "#fbbc05",
  "#34a853",
  "#a142f4",
  "#00acc1",
  "#ff7043",
  "#9e9d24",
  "#ec407a",
  "#5c6bc0",
];

const CONFIDENCE_COLOR: Record<string, string> = {
  extracted: "#5f6368",
  inferred: "#b0863a",
  ambiguous: "#c5221f",
};

/** Serialize the current graph state to the render engine's shape. Colors
 *  encode layer/type; `tags` drive the engine's search/filter; size scales
 *  with degree. */
export function renderGraph(
  state: GraphState,
  meta: GraphMeta,
  opts: RenderOpts = {},
): RenderGraph {
  // 1) time-slice (live = no asOf)
  const axis: Axis = opts.axis ?? "tx";
  const timed = opts.asOf ? materializeAt(state, opts.asOf, axis) : state;

  const isEntityLevel = (layer: Layer) => !COLORED_BY_LAYER.has(layer);

  // 2) communities → GROUPS (not nodes). memberIds via member_of edges.
  const communities = timed.nodes.filter((n) => n.layer === "community");
  const membersByComm = new Map<string, string[]>();
  for (const e of timed.edges) {
    if (e.type !== "member_of") continue;
    (membersByComm.get(e.targetId) ?? membersByComm.set(e.targetId, []).get(e.targetId)!).push(e.sourceId);
  }

  // 3) availability counts (before filters): layers (non-community) + types.
  const layerCount = new Map<Layer, number>();
  const typeCount = new Map<string, number>();
  for (const n of timed.nodes) {
    if (n.layer === "community") continue;
    layerCount.set(n.layer, (layerCount.get(n.layer) ?? 0) + 1);
    if (isEntityLevel(n.layer)) typeCount.set(n.type, (typeCount.get(n.type) ?? 0) + 1);
  }

  // stable type colours (sorted, so legend ↔ nodes match)
  const typeColor = new Map<string, string>();
  [...typeCount.keys()].sort().forEach((t, i) => typeColor.set(t, TYPE_PALETTE[i % TYPE_PALETTE.length]!));
  const colorOfType = (t: string) => typeColor.get(t) ?? hashColor(t);

  // 4) filters: layers (non-entity layers) + types (entity kinds). Communities
  //    never render as nodes.
  const activeLayers = opts.layers && opts.layers.length ? new Set<Layer>(opts.layers) : null;
  const activeTypes = opts.types && opts.types.length ? new Set<string>(opts.types) : null;
  const winFrom = opts.from ? Date.parse(opts.from) : null;
  const winTo = opts.to ? Date.parse(opts.to) : null;
  const inWindow = (n: (typeof timed.nodes)[number]): boolean => {
    if (winFrom == null && winTo == null) return true;
    const b = axis === "valid" ? n.validFrom : n.txFrom;
    const t = b ? Date.parse(b) : NaN;
    if (Number.isNaN(t)) return false; // timeless nodes drop out of a window
    if (winFrom != null && t < winFrom) return false;
    if (winTo != null && t > winTo) return false;
    return true;
  };
  const visNodes = timed.nodes.filter((n) => {
    // chunks = provenance (drill-down only), communities = groups: not canvas nodes
    if (n.layer === "community" || n.layer === "chunk") return false;
    if (activeLayers && !activeLayers.has(n.layer)) return false;
    if (activeTypes && isEntityLevel(n.layer) && !activeTypes.has(n.type)) return false;
    if (!inWindow(n)) return false;
    return true;
  });
  const keep = new Set(visNodes.map((n) => n.id));

  const view: GraphState = {
    nodes: visNodes,
    edges: timed.edges.filter(
      (e) => e.type !== "member_of" && keep.has(e.sourceId) && keep.has(e.targetId),
    ),
    journal: state.journal,
  };

  // groups restricted to visible members
  const groups = communities
    .map((c) => ({
      id: c.id,
      name: c.name,
      color: hashColor(c.id),
      summary: c.summary ?? null,
      memberIds: (membersByComm.get(c.id) ?? []).filter((m) => keep.has(m)),
    }))
    .filter((g) => g.memberIds.length > 0);

  const deg = degreeMap(view);
  const maxDeg = Math.max(1, ...[...deg.values()]);

  const nodes = view.nodes.map((n) => {
    const d = deg.get(n.id) ?? 0;
    // canonical chunk/community/topic → layer colour; entity & emergent
    // entity-level strata → colour by type.
    const color = COLORED_BY_LAYER.has(n.layer)
      ? (LAYER_COLOR[n.layer] ?? hashColor(n.layer))
      : colorOfType(n.type);
    return {
      id: n.id,
      name: n.name,
      x: n.x ?? 0,
      y: n.y ?? 0,
      data: {
        color,
        size: 1 + (d / maxDeg) * 2.5,
        borderColor: n.verified ? "#1e8e3e" : n.pinned ? "#f9ab00" : undefined,
        tags: [n.layer, n.type],
        pinned: n.pinned ?? false,
        verified: !!n.verified,
      },
    };
  });

  const links: RenderGraph["graph"]["links"] = view.edges
    .filter((e) => !e.invalidation)
    .map((e) => ({
      source: e.sourceId,
      target: e.targetId,
      data: {
        id: e.id,
        relation: e.relation ?? null,
        explanation: e.explanation ?? null,
        confidence: e.confidence,
        tags: [e.type, e.confidence],
        color: CONFIDENCE_COLOR[e.confidence] ?? "#5f6368",
      },
    }));

  // ── Batagelj multipart projection overlay (same-layer 2nd-order edges) ──
  if (opts.projections) {
    const visible = new Set(nodes.map((n) => n.id));
    // project over the FULL time-sliced state (chunks/communities = the
    // intermediaries), then keep only edges between visible canvas nodes.
    const derived = multiProjection(timed.nodes, timed.edges).filter((e) => visible.has(e.sourceId) && visible.has(e.targetId));
    const QUASI = "#a142f4"; // violet — the projection / quasi-variable colour
    const assembled = new Set<string>();
    for (const e of derived) {
      assembled.add(e.sourceId);
      assembled.add(e.targetId);
      links.push({
        source: e.sourceId,
        target: e.targetId,
        data: {
          id: e.id,
          relation: e.relation ?? null,
          explanation: null,
          confidence: "inferred",
          tags: ["derived", "inferred"],
          color: QUASI,
          derived: true,
          from: e.sourceId,
          to: e.targetId,
        },
      });
    }
    // mark nodes assembled through quasi-variables with a violet ring
    for (const n of nodes) if (assembled.has(n.id)) n.data.borderColor = QUASI;
  }

  const colorLegend = [...typeColor.entries()].map(([description, color]) => ({
    color,
    description,
  }));

  // Layer chips: non-entity, non-community layers (chunk/topic/emergent).
  const layerLegend = layerRegistry(meta.layers, layerCount.keys())
    .filter((d) => d.name !== "community" && d.name !== "chunk" && !isEntityLevel(d.name) && (layerCount.get(d.name) ?? 0) > 0)
    .map((d) => ({
      layer: d.name,
      color: d.color ?? LAYER_COLOR[d.name] ?? hashColor(d.name),
      count: layerCount.get(d.name) ?? 0,
      active: !activeLayers || activeLayers.has(d.name),
    }));

  // Type chips: the entity-layer detail (PERSON / ORG / …).
  const typeLegend = [...typeCount.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([type, count]) => ({
      type,
      color: colorOfType(type),
      count,
      active: !activeTypes || activeTypes.has(type),
    }));

  return {
    name: meta.name,
    graph: {
      nodes,
      links,
      groups,
      legends: { size: "degree", color: colorLegend, layers: layerLegend, types: typeLegend },
      settings: { alwaysLabelVisible: false },
    },
  };
}
