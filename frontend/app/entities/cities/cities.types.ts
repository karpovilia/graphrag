import type { LinkInterface, NodeInterface } from "@krainovsd/graph";

export type ICityGraphImportMap = {
  path: string;
  id: string;
  name: string;
};
export type ICityGraphNodeText = {
  id: number;
  text: string;
};
export type ICityGraphNodeData = {
  texts: ICityGraphNodeText[];
  color: string;
  size: number;
  /** Native per-node alpha (sec0 migration: stop baking alpha into an
   * 8-digit color). Optional so existing call sites still typecheck. */
  alpha?: number;
  /** Draw a strike-through (dead / invalidated). */
  strike?: boolean;
  /** Draw a halo (born / evidence). */
  glow?: boolean;
  /** Direction (graph-space delta) toward the node's new community —
   * drawn as a small directional tick for moved_community. */
  liftTo?: [number, number] | null;
  /** Raw §0 delta state, for hit-testing / legend grouping. */
  deltaState?: import("@/components/organisms/LayeredGraph/lib/delta").DeltaState;
};
export type ICityGraphLinkData = {
  explanation: string;
  color: string;
  id: number;
  /** Native per-link alpha (sec0). */
  alpha?: number;
  /** Draw an × mark at the link midpoint for dead / invalidated edges. */
  strike?: boolean;
};
export type ICityGraphLink = LinkInterface<ICityGraphNodeData, ICityGraphLinkData>;
export type ICityGraphNode = NodeInterface<ICityGraphNodeData>;
export type ICityGraphText = {
  pid: number;
  text: string;
};
