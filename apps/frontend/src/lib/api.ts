export interface RenderNode {
  id: string;
  name: string;
  x: number;
  y: number;
  data: {
    color: string;
    size: number;
    borderColor?: string;
    tags: string[];
    pinned?: boolean;
    _matched?: boolean | null;
    _deltaStatus?: string;
  };
}
export interface RenderLink {
  source: string;
  target: string;
  data: { id: string; relation?: string | null; confidence: string; tags: string[]; color: string };
}
export interface RenderGraph {
  name: string;
  version: number;
  graph: { nodes: RenderNode[]; links: RenderLink[]; legends: unknown; settings: { alwaysLabelVisible: boolean } };
}

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) throw new Error(`${res.status} ${path}: ${await res.text()}`);
  return (res.status === 204 ? null : await res.json()) as T;
}

export const api = {
  listGraphs: () => j<{ id: string; name: string }[]>("/api/graphs"),
  getGraph: (id: string) => j<RenderGraph>(`/api/graph/${id}`),
  journal: (id: string) => j<unknown[]>(`/api/graphs/${id}/journal`),
  suggestions: (id: string) => j<unknown[]>(`/api/graphs/${id}/suggestions`),
  applyOp: (id: string, op: string, payload: Record<string, unknown>, actor: string) =>
    j(`/api/graphs/${id}/ops`, { method: "POST", body: JSON.stringify({ op, payload, actor }) }),
  revert: (id: string, actor: string) =>
    j(`/api/graphs/${id}/revert`, { method: "POST", body: JSON.stringify({ actor }) }),
  runAgent: (id: string, name: "dedup" | "orphans") =>
    j(`/api/graphs/${id}/agents/${name}/run`, { method: "POST" }),
  resolveDecision: (
    id: string,
    did: string,
    choice: string,
    actor: string,
    editedPayload?: Record<string, unknown>,
  ) =>
    j(`/api/graphs/${id}/decisions/${did}/resolve`, {
      method: "POST",
      body: JSON.stringify({ choice, actor, editedPayload }),
    }),
  pin: (id: string, nodeIds: string[], pinned: boolean) =>
    j(`/api/graphs/${id}/pin`, { method: "POST", body: JSON.stringify({ nodeIds, pinned }) }),
  compileSkill: (id: string, body: Record<string, unknown>) =>
    j(`/api/graphs/${id}/skills/compile`, { method: "POST", body: JSON.stringify(body) }),
};
