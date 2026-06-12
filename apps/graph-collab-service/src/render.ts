import {
  degreeMap,
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
      };
    }[];
    legends: {
      size: string;
      color: { color: string; description: string }[];
    };
    settings: { alwaysLabelVisible: boolean };
  };
}

const LAYER_COLOR: Record<Layer, string> = {
  chunk: "#9aa0a6",
  entity: "#4f86f7",
  community: "#34a853",
  topic: "#a142f4",
};

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
export function renderGraph(state: GraphState, meta: GraphMeta): RenderGraph {
  const deg = degreeMap(state);
  const maxDeg = Math.max(1, ...[...deg.values()]);

  const typeColor = new Map<string, string>();
  let ti = 0;
  const colorOfType = (t: string): string => {
    let c = typeColor.get(t);
    if (!c) {
      c = TYPE_PALETTE[ti % TYPE_PALETTE.length]!;
      typeColor.set(t, c);
      ti++;
    }
    return c;
  };

  const nodes = state.nodes.map((n) => {
    const d = deg.get(n.id) ?? 0;
    const color =
      n.layer === "entity" ? colorOfType(n.type) : LAYER_COLOR[n.layer];
    return {
      id: n.id,
      name: n.name,
      x: n.x ?? 0,
      y: n.y ?? 0,
      data: {
        color,
        size: 1 + (d / maxDeg) * 2.5,
        borderColor: n.pinned ? "#f9ab00" : undefined,
        tags: [n.layer, n.type],
        pinned: n.pinned ?? false,
      },
    };
  });

  const links = state.edges
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

  const colorLegend = [...typeColor.entries()].map(([description, color]) => ({
    color,
    description,
  }));

  return {
    name: meta.name,
    graph: {
      nodes,
      links,
      legends: { size: "degree", color: colorLegend },
      settings: { alwaysLabelVisible: false },
    },
  };
}
