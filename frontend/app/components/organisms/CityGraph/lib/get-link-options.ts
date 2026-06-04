import type { GraphCanvas, LinkOptionsInterface } from "@krainovsd/graph";
import type { ThemeName } from "@krainovsd/vue-ui";
import type { ICityGraphLink, ICityGraphLinkData, ICityGraphNodeData } from "@/entities/cities";
import { HIGHLIGHT_COLOR, LINK_DARK_COLOR, LINK_LIGHT_COLOR } from "../city-graph.constats";

const STRIKE_COLOR = "#6b7280";

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
    const fill = selected ? HIGHLIGHT_COLOR : (link.data?.color ?? color);

    return {
      ...opts,
      color: fill,
      arrowColor: fill,
      particleColor: fill,
      arrowBorderColor: fill,
      particleBorderColor: fill,
      // Native per-link alpha (sec0); defaults to 1 when unset.
      alpha: link.data?.alpha ?? 1,
      width: selected
        ? 0.3
        : ((link.data as { width?: number } | undefined)?.width ?? 0.1),
      // × mark at the link midpoint for dead / invalidated edges (§0).
      drawExtraLink(
        this: GraphCanvas<ICityGraphNodeData, ICityGraphLinkData>,
        l,
      ) {
        if (!l.data?.strike) return;
        const src = l.source;
        const tgt = l.target;
        if (typeof src !== "object" || typeof tgt !== "object") return;
        const sx = (src as { x?: number }).x;
        const sy = (src as { y?: number }).y;
        const tx = (tgt as { x?: number }).x;
        const ty = (tgt as { y?: number }).y;
        if (
          typeof sx !== "number" ||
          typeof sy !== "number" ||
          typeof tx !== "number" ||
          typeof ty !== "number"
        )
          return;
        const ctx = (
          this as unknown as { context?: CanvasRenderingContext2D | null }
        ).context;
        if (!ctx) return;
        const mx = (sx + tx) / 2;
        const my = (sy + ty) / 2;
        const s = 1.2;
        ctx.save();
        ctx.strokeStyle = STRIKE_COLOR;
        ctx.lineWidth = 0.4;
        ctx.beginPath();
        ctx.moveTo(mx - s, my - s);
        ctx.lineTo(mx + s, my + s);
        ctx.moveTo(mx + s, my - s);
        ctx.lineTo(mx - s, my + s);
        ctx.stroke();
        ctx.restore();
      },
    };
  };
}
