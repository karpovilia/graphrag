import type {
  ForceSettingsInterface,
  GraphSettingsInterface,
  HighlightSettingsInterface,
  LinkOptionsInterface,
  LinkSettingsInterface,
  NodeOptionsInterface,
  NodeSettingsInterface,
} from "@krainovsd/graph";
import type {
  ICityGraphLink,
  ICityGraphLinkData,
  ICityGraphNode,
  ICityGraphNodeData,
} from "@/entities/cities";

export type ICityGraphSettings = {
  forceSettings: Partial<ForceSettingsInterface<ICityGraphNodeData, ICityGraphLinkData>>;
  graphSettings: Partial<GraphSettingsInterface<ICityGraphNodeData>>;
  linkOptions: Partial<LinkOptionsInterface<ICityGraphNodeData, ICityGraphLinkData>>;
  nodeOptions: Partial<NodeOptionsInterface<ICityGraphNodeData, ICityGraphLinkData>>;
  linkSettings: Partial<LinkSettingsInterface<ICityGraphNodeData, ICityGraphLinkData>>;
  nodeSettings: Partial<NodeSettingsInterface<ICityGraphNodeData, ICityGraphLinkData>>;
  highlightSettings: Partial<HighlightSettingsInterface>;
};
export type ICityGraph = {
  nodes: ICityGraphNode[];
  links: ICityGraphLink[];
};
