import type {
  GraphCanvas,
  NodeInterface,
  NodeOptionsInterface,
} from "@krainovsd/graph";
import type { ThemeName } from "@krainovsd/vue-ui";
import type { ICityGraphLinkData, ICityGraphNodeData } from "@/entities/cities";
import {
  HIGHLIGHT_COLOR,
  NODE_DARK_COLOR,
  NODE_LIGHT_COLOR,
  TEXT_DARK_COLOR,
  TEXT_LIGHT_COLOR,
} from "../city-graph.constats";

const MOVED_CONTOUR = "#ff7f0e";
const STRIKE_COLOR = "#6b7280";

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
    const data = node.data;
    const movedContour = data?.deltaState === "moved_community";

    return {
      ...opts,
      // Selection border always wins over the delta contour.
      borderColor: selected
        ? HIGHLIGHT_COLOR
        : movedContour
          ? MOVED_CONTOUR
          : "transparent",
      borderWidth: selected ? 0.5 : movedContour ? 0.4 : 0.2,
      color: data?.color ?? color,
      // Native per-node alpha (sec0). Defaults to 1 when unset.
      alpha: data?.alpha ?? 1,
      radius: 1 + (data?.size ?? 0),
      textFont: "Nunito",
      textColor: data?.color ?? textColor,
      // §0 grammar marks the package can't express declaratively: a
      // strike-through (dead/invalidated), a halo (born/evidence), and a
      // directional lift-tick toward the new community (moved_community).
      nodeExtraDraw(this: GraphCanvas<ICityGraphNodeData, ICityGraphLinkData>, n, o) {
        if (!data) return;
        const x = n.x;
        const y = n.y;
        if (typeof x !== "number" || typeof y !== "number") return;
        const ctx = (
          this as unknown as { context?: CanvasRenderingContext2D | null }
        ).context;
        if (!ctx) return;
        const r = (o.radius ?? 1) as number;

        // Minimum SCREEN-space node size. The package draws the node circle
        // in graph coords scaled by the zoom k, so on strong zoom-out r*k
        // goes sub-pixel and the whole graph fades to nothing. Read the live
        // scale and, when a node would render below MIN_SCREEN_PX, paint a
        // floor dot of radius MIN_SCREEN_PX/k (→ constant on-screen size) so
        // the graph stays a visible cloud at any zoom.
        const k =
          (this as unknown as { areaTransform?: { k?: number } }).areaTransform
            ?.k ?? 1;
        const MIN_SCREEN_PX = 1.6;
        if (k > 0 && r * k < MIN_SCREEN_PX) {
          ctx.save();
          ctx.globalAlpha = (o.alpha as number | undefined) ?? data.alpha ?? 1;
          ctx.fillStyle = (data.color as string | undefined) ?? "#888888";
          ctx.beginPath();
          ctx.arc(x, y, MIN_SCREEN_PX / k, 0, Math.PI * 2);
          ctx.fill();
          ctx.restore();
        }

        if (data.glow) {
          ctx.save();
          ctx.globalAlpha = 0.4;
          ctx.beginPath();
          ctx.arc(x, y, r * 2.2, 0, Math.PI * 2);
          ctx.strokeStyle = data.color ?? HIGHLIGHT_COLOR;
          ctx.lineWidth = r * 0.5;
          ctx.stroke();
          ctx.restore();
        }
        if (data.strike) {
          ctx.save();
          ctx.beginPath();
          ctx.moveTo(x - r * 1.4, y + r * 1.4);
          ctx.lineTo(x + r * 1.4, y - r * 1.4);
          ctx.strokeStyle = STRIKE_COLOR;
          ctx.lineWidth = r * 0.4;
          ctx.stroke();
          ctx.restore();
        }
        if (data.liftTo) {
          const [dx, dy] = data.liftTo;
          const len = Math.hypot(dx, dy) || 1;
          const ux = dx / len;
          const uy = dy / len;
          ctx.save();
          ctx.beginPath();
          ctx.moveTo(x + ux * r * 1.4, y + uy * r * 1.4);
          ctx.lineTo(x + ux * r * 3.2, y + uy * r * 3.2);
          ctx.strokeStyle = MOVED_CONTOUR;
          ctx.lineWidth = r * 0.4;
          ctx.stroke();
          ctx.restore();
        }
      },
    };
  };
}
