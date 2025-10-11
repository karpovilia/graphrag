import { isId } from "@krainovsd/js-helpers";
import type { ICityGraphLink, ICityGraphNode } from "@/entities/cities";

export function getCorrectData(initialNodes: ICityGraphNode[], initialLinks: ICityGraphLink[]) {
  const neighbors: Record<string, (string | number)[]> = {};

  const links: ICityGraphLink[] = initialLinks.map((link) => {
    const sourceId =
      typeof link.source === "object" && "id" in link.source ? link.source.id : link.source;
    const targetId =
      typeof link.target === "object" && "id" in link.target ? link.target.id : link.target;

    if (isId(sourceId) && isId(targetId)) {
      if (!neighbors[sourceId]) neighbors[sourceId] = [];
      const prevSource = neighbors[sourceId];
      prevSource.push(targetId);

      if (!neighbors[targetId]) neighbors[targetId] = [];
      const prevTarget = neighbors[targetId];
      prevTarget.push(sourceId);
    }

    return link;
  });

  const nodes: ICityGraphNode[] = initialNodes.map((node) => {
    const nodeNeighbor = neighbors[node.id] ?? [];

    node.neighbors = nodeNeighbor;
    node.linkCount = nodeNeighbor.length;
    if (node.x) {
      node.x = +node.x;
    }
    if (node.y) {
      node.y = +node.y;
    }
    // if (node?.data?.size) {
    //   node.data.size /= 250;
    // }

    return node;
  });

  return { nodes, links };
}
