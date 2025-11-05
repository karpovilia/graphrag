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
};
export type ICityGraphLinkData = { explanation: string; color: string; id: number };
export type ICityGraphLink = LinkInterface<ICityGraphNodeData, ICityGraphLinkData>;
export type ICityGraphNode = NodeInterface<ICityGraphNodeData>;
export type ICityGraphText = {
  pid: number;
  text: string;
};
