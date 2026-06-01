// Alpha-channel helpers for the opacity-focus layered effect.
//
// Phase 6.6.1 decision (memory: project_redesign_r2.md item 8):
// 2.5D / 3D rendering is OFF the table. Layered effect is built by
// dimming inactive layers via the alpha channel of every per-node and
// per-edge color. The wrapper computes a target alpha per layer based
// on whether it equals `activeLayer`, then patches the existing
// `data.color` / `data.borderColor` / link color the @krainovsd/graph
// renderer reads from.

import type { Layer } from "@/entities/api";

export const LAYER_COLORS: Record<Layer, string> = {
  chunk: "#94a3b8",
  entity: "#1f77b4",
  community: "#2ca02c",
  topic: "#ff7f0e",
};

export const LAYER_ORDER: Layer[] = ["chunk", "entity", "community", "topic"];

export const ACTIVE_ALPHA = 1.0;
export const INACTIVE_ALPHA = 0.2;

/** Hex (#RRGGBB or #RRGGBBAA) → 6-digit base color (no alpha). Falls
 * back to the input string when it isn't a hex literal — packages
 * sometimes hand back named CSS colors and we don't want to break those.
 */
export function stripAlpha(color: string): string {
  if (!color.startsWith("#")) return color;
  if (color.length === 9) return color.slice(0, 7);
  return color;
}

/** Encode a [0..1] alpha into the 2-digit hex suffix expected by canvas
 * renderers. Caller is responsible for passing a 6-digit base color.
 */
export function withAlpha(color: string, alpha: number): string {
  if (!color.startsWith("#") || color.length < 7) {
    // Not a hex base — return verbatim. The renderer will use the
    // global opacity it was given for inactive layers (best-effort).
    return color;
  }
  const a = Math.max(0, Math.min(1, alpha));
  const suffix = Math.round(a * 255).toString(16).padStart(2, "0");
  return `${color.slice(0, 7)}${suffix}`;
}

/** Alpha to apply for `layer` given the user's active layer. `null`
 * activeLayer means "show everything full" (slice mode off). */
export function alphaFor(layer: Layer, activeLayer: Layer | null): number {
  if (activeLayer === null) return ACTIVE_ALPHA;
  return layer === activeLayer ? ACTIVE_ALPHA : INACTIVE_ALPHA;
}

/** Resolve final alpha for `layer` honoring per-layer overrides from
 * the LayerMap sliders + sliceMode (hide non-active layers entirely).
 * Per-layer override always wins when present; sliceMode hides
 * non-active layers regardless of any override. */
export function resolveAlpha(
  layer: Layer,
  activeLayer: Layer | null,
  perLayerAlpha: Partial<Record<Layer, number>> = {},
  sliceMode = false,
): number {
  if (sliceMode && activeLayer !== null && layer !== activeLayer) return 0;
  const override = perLayerAlpha[layer];
  if (override !== undefined) return Math.max(0, Math.min(1, override));
  return alphaFor(layer, activeLayer);
}

/** Color picker for a node — defers to `attributes.color` when the
 * builder set one (e.g. type-driven palette), otherwise falls back to
 * the layer accent.
 */
export function colorForLayer(layer: Layer, override?: string | null): string {
  if (override) return stripAlpha(override);
  return LAYER_COLORS[layer];
}

/** Categorical palette for community-map coloring. Tableau10 + 2 extra
 * okabe-ito colors so we have 12 distinguishable hues; communities map
 * into it by stable hash. With thousands of communities we can't make
 * them all distinct — neighbours in the graph layout will sometimes
 * share a hue. Good enough for the "what's the structure?" question.
 */
export const COMMUNITY_PALETTE: readonly string[] = [
  "#4e79a7",
  "#f28e2b",
  "#e15759",
  "#76b7b2",
  "#59a14f",
  "#edc948",
  "#b07aa1",
  "#ff9da7",
  "#9c755f",
  "#bab0ac",
  "#0072b2",
  "#cc79a7",
];

/** Stable string hash (FNV-1a 32-bit). Pure function — same id always
 * maps to the same palette index across re-renders and across split-view
 * panes. */
function hashString(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = (h * 16777619) >>> 0;
  }
  return h >>> 0;
}

/** Pick a palette color for a community id deterministically. */
export function colorForCommunity(communityId: string | null | undefined): string {
  if (!communityId) return LAYER_COLORS.community;
  return COMMUNITY_PALETTE[hashString(communityId) % COMMUNITY_PALETTE.length]!;
}
