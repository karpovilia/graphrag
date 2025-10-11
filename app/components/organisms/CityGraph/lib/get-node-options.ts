import type { NodeInterface, NodeOptionsInterface } from "@krainovsd/graph";
import type { ThemeName } from "@krainovsd/vue-ui";
import type { ICityGraphLinkData, ICityGraphNodeData } from "@/entities/cities";
import {
  HIGHLIGHT_COLOR,
  NODE_DARK_COLOR,
  NODE_LIGHT_COLOR,
  TEXT_DARK_COLOR,
  TEXT_LIGHT_COLOR,
} from "../city-graph.constats";

export function getNodeOptions(
  opts: Partial<NodeOptionsInterface<ICityGraphNodeData, ICityGraphLinkData>>,
  selectedNodes: id[],
  theme: ThemeName,
) {
  return (
    node: NodeInterface<ICityGraphNodeData>,
  ): NodeOptionsInterface<ICityGraphNodeData, ICityGraphLinkData> => {
    const selected = selectedNodes.includes(node.id);
    const color = theme === "dark" ? NODE_DARK_COLOR : NODE_LIGHT_COLOR;
    const textColor = theme === "dark" ? TEXT_DARK_COLOR : TEXT_LIGHT_COLOR;

    return {
      ...opts,
      borderColor: selected ? HIGHLIGHT_COLOR : "transparent",
      borderWidth: selected ? 0.5 : 0.2,
      color: node.data?.color ?? color,
      radius: 1 + (node.data?.size ?? 0),
      textFont: "Nunito",
      textColor: node.data?.color ?? textColor,
    };
  };
}
