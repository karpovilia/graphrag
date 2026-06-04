// Sec0 delta grammar — the single source of truth for "what changed".
//
// Sibling of alpha.ts. Where alpha.ts answers "which LAYER is in focus",
// delta.ts answers "what HAPPENED to this id" along whatever axis the
// host is exploring: time (timeline scrub / diff), query (evidence vs
// complement), or edit (cascade ripple). The same five-encoding grammar
// renders all three — that one-grammar-three-sources claim is the §0
// contribution, so this function is deliberately axis-agnostic and pure
// (unit-testable, no Vue, no canvas).
//
// Encodings (one row per state):
//   born            green fill, halo, full alpha
//   dead            grey fill, strike-through, dimmed alpha
//   invalidated     grey fill, strike-through, dimmed alpha (revert candidate)
//   persisted       base color, full alpha (unchanged carry-over)
//   moved_community orange contour + directional lift-tick toward new community
//   evidence        base color, full saturation/alpha, halo (query row)
//   dimmed          base color, very low alpha (the complement of evidence)

export type DeltaState =
  | "born"
  | "changed"
  | "dead"
  | "persisted"
  | "moved_community"
  | "invalidated"
  | "evidence"
  | "dimmed"
  | null;

/** Where the current delta overlay comes from. Legend label only — the
 * grammar itself does not branch on this. */
export type DeltaSource = "time" | "query" | "edit" | null;

export const DELTA_COLORS: Record<NonNullable<DeltaState>, string | null> = {
  born: "#2ca02c",
  changed: "#1f77b4", // a persisted entity whose facts changed in the window
  dead: "#6b7280",
  invalidated: "#6b7280",
  persisted: null, // keep base color
  moved_community: "#ff7f0e", // used as contour, not fill
  evidence: null, // keep base color at full saturation
  dimmed: null, // keep base color, only alpha drops
};

export const DELTA_ALPHA: Record<NonNullable<DeltaState>, number> = {
  born: 1.0,
  changed: 1.0,
  evidence: 1.0,
  persisted: 1.0,
  moved_community: 1.0,
  invalidated: 0.35,
  dead: 0.35,
  dimmed: 0.18,
};

/** Resolved visual hints for one id. `color === null` means "keep the
 * base layer color"; the compositor leaves it alone. */
export type DeltaResolved = {
  state: DeltaState;
  /** Override fill, or null to keep base. */
  color: string | null;
  /** Target alpha in [0..1] for this delta state. */
  alpha: number;
  /** Contour color (moved_community) drawn as a ring, or null. */
  border: string | null;
  /** Draw a strike-through (dead / invalidated). */
  strike: boolean;
  /** Draw a halo (born / evidence). */
  glow: boolean;
};

const NEUTRAL: DeltaResolved = {
  state: null,
  color: null,
  alpha: 1.0,
  border: null,
  strike: false,
  glow: false,
};

/** Resolve the §0 grammar for a single id given the delta index. Pure.
 * An id missing from the index resolves to NEUTRAL (no override). */
export function resolveDelta(
  id: string,
  deltaIndex: Map<string, DeltaState> | null | undefined,
): DeltaResolved {
  if (!deltaIndex) return NEUTRAL;
  const state = deltaIndex.get(id) ?? null;
  if (state === null) return NEUTRAL;
  return {
    state,
    color: DELTA_COLORS[state],
    alpha: DELTA_ALPHA[state],
    border: state === "moved_community" ? DELTA_COLORS.moved_community : null,
    strike: state === "dead" || state === "invalidated",
    glow: state === "born" || state === "evidence" || state === "changed",
  };
}
