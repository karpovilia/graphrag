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
    zoomExtent: [0.2, 10],
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
