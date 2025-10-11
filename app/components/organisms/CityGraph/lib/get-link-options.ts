import type { LinkOptionsInterface } from "@krainovsd/graph";
import type { ThemeName } from "@krainovsd/vue-ui";
import type { ICityGraphLink, ICityGraphLinkData, ICityGraphNodeData } from "@/entities/cities";
import { HIGHLIGHT_COLOR, LINK_DARK_COLOR, LINK_LIGHT_COLOR } from "../city-graph.constats";

export function getLinkOptions(
  opts: Partial<LinkOptionsInterface<ICityGraphNodeData, ICityGraphLinkData>>,
  selectedLink: id | null,
  theme: ThemeName,
) {
  return function getLinkOptions(
    link: ICityGraphLink,
  ): LinkOptionsInterface<ICityGraphNodeData, ICityGraphLinkData> {
    const selected = selectedLink === link.data?.id;
    const color = theme === "dark" ? LINK_DARK_COLOR : LINK_LIGHT_COLOR;

    return {
      ...opts,
      color: selected ? HIGHLIGHT_COLOR : (link.data?.color ?? color),
      arrowColor: selected ? HIGHLIGHT_COLOR : (link.data?.color ?? color),
      particleColor: selected ? HIGHLIGHT_COLOR : (link.data?.color ?? color),
      arrowBorderColor: selected ? HIGHLIGHT_COLOR : (link.data?.color ?? color),
      particleBorderColor: selected ? HIGHLIGHT_COLOR : (link.data?.color ?? color),
      width: selected ? 0.3 : 0.1,
    };
  };
}
