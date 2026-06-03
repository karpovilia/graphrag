import {
  GRAPH_SETTINGS,
  HIGHLIGHT_SETTINGS,
  LINK_OPTIONS,
  LINK_SETTINGS,
  NODE_OPTIONS,
  NODE_SETTINGS,
} from "@krainovsd/graph";
import type { ICityGraphSettings } from "./city-graph.types";

export const DEFAULT_SETTINGS: ICityGraphSettings = {
  forceSettings: {
    forces: true,
  },
  graphSettings: {
    ...GRAPH_SETTINGS,
    // Floor the zoom-out: below ~0.4 a big graph collapses to a speck and
    // looks like it vanished. 0.4 keeps the whole cloud on screen but legible;
    // get-node-options also floors each node's on-screen size as a backstop.
    zoomExtent: [0.4, 40],
    translateExtentCoefficient: [4.5, 4.5],
  },
  linkOptions: LINK_OPTIONS,
  linkSettings: LINK_SETTINGS,
  nodeOptions: NODE_OPTIONS,
  nodeSettings: NODE_SETTINGS,
  highlightSettings: { ...HIGHLIGHT_SETTINGS },
};
export const HIGHLIGHT_COLOR = "#000000";
export const TEXT_DARK_COLOR = "#d2d2d2";
export const TEXT_LIGHT_COLOR = "#21252D";
export const LINK_DARK_COLOR = "#C5C5C5FF";
export const LINK_LIGHT_COLOR = "#BBBBBB";
export const NODE_DARK_COLOR = "#21252D";
export const NODE_LIGHT_COLOR = "#21252D";
