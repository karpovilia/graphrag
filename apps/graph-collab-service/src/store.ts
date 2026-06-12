import { promises as fs } from "node:fs";
import path from "node:path";
import {
  applyJournalOp,
  replayJournal,
  type CompiledSkill,
  type GraphMeta,
  type GraphState,
  type JournalEntry,
} from "@graphcraft/core";

export class ConcurrentEditError extends Error {
  constructor(
    public expected: number,
    public actual: number,
  ) {
    super(`concurrent edit: expected version ${expected}, got ${actual}`);
  }
}

export class NotFoundError extends Error {}

/** Overlay meta.pinnedNodeIds onto node.pinned. */
function overlayPins(state: GraphState, meta: GraphMeta): GraphState {
  const pinned = new Set(meta.pinnedNodeIds ?? []);
  if (!pinned.size) return state;
  return {
    ...state,
    nodes: state.nodes.map((n) =>
      pinned.has(n.id) ? { ...n, pinned: true } : n,
    ),
  };
}

interface Loaded {
  meta: GraphMeta;
  base: GraphState;
  current: GraphState;
}

/** Per-graph durable persistence:
 *    graphs/<id>/base.json     — immutable post-import nodes+edges
 *    graphs/<id>/journal.jsonl — append-only curation log (training data)
 *    graphs/<id>/meta.json     — name/version/counts
 *  Current state = replay(base, journal). All writes are serialized per
 *  graph and append-only where possible, so the store stays git-friendly. */
export class GraphStore {
  private cache = new Map<string, Loaded>();
  private locks = new Map<string, Promise<unknown>>();

  constructor(private graphsDir: string) {}

  private dir(id: string) {
    return path.join(this.graphsDir, id);
  }

  /** Serialize async work per graph id (single-writer guarantee). */
  private run<T>(id: string, fn: () => Promise<T>): Promise<T> {
    const prev = this.locks.get(id) ?? Promise.resolve();
    const next = prev.then(fn, fn);
    this.locks.set(
      id,
      next.then(
        () => undefined,
        () => undefined,
      ),
    );
    return next;
  }

  async listGraphs(): Promise<GraphMeta[]> {
    let entries: string[];
    try {
      entries = await fs.readdir(this.graphsDir);
    } catch {
      return [];
    }
    const metas: GraphMeta[] = [];
    for (const e of entries) {
      try {
        const raw = await fs.readFile(path.join(this.dir(e), "meta.json"), "utf8");
        metas.push(JSON.parse(raw) as GraphMeta);
      } catch {
        /* skip non-graph dirs */
      }
    }
    return metas;
  }

  /** Write a fresh graph (importer / sample generator). Overwrites. */
  async saveGraph(meta: GraphMeta, base: GraphState): Promise<void> {
    const d = this.dir(meta.id);
    await fs.mkdir(d, { recursive: true });
    const baseDump: GraphState = { nodes: base.nodes, edges: base.edges, journal: [] };
    await fs.writeFile(path.join(d, "base.json"), JSON.stringify(baseDump, null, 2));
    await fs.writeFile(path.join(d, "journal.jsonl"), "");
    await fs.writeFile(path.join(d, "meta.json"), JSON.stringify(meta, null, 2));
    this.cache.delete(meta.id);
  }

  private async load(id: string): Promise<Loaded> {
    const cached = this.cache.get(id);
    if (cached) return cached;
    const d = this.dir(id);
    let metaRaw: string;
    try {
      metaRaw = await fs.readFile(path.join(d, "meta.json"), "utf8");
    } catch {
      throw new NotFoundError(`graph ${id} not found`);
    }
    const meta = JSON.parse(metaRaw) as GraphMeta;
    const baseRaw = await fs.readFile(path.join(d, "base.json"), "utf8");
    const baseDump = JSON.parse(baseRaw) as GraphState;
    const base: GraphState = {
      nodes: baseDump.nodes,
      edges: baseDump.edges,
      journal: [],
    };
    let journal: JournalEntry[] = [];
    try {
      const jl = await fs.readFile(path.join(d, "journal.jsonl"), "utf8");
      journal = jl
        .split("\n")
        .filter((l) => l.trim())
        .map((l) => JSON.parse(l) as JournalEntry);
    } catch {
      /* no journal yet */
    }
    const current = overlayPins(replayJournal(base, journal), meta);
    const loaded: Loaded = { meta, base, current };
    this.cache.set(id, loaded);
    return loaded;
  }

  /** Pin / unpin nodes (annotation in meta; overlaid onto state.pinned).
   *  Does not bump version — a pin is not a graph edit. */
  async setPinned(id: string, nodeIds: string[], pinned: boolean): Promise<void> {
    return this.run(id, async () => {
      const loaded = await this.load(id);
      const set = new Set(loaded.meta.pinnedNodeIds ?? []);
      for (const nid of nodeIds) {
        if (pinned) set.add(nid);
        else set.delete(nid);
      }
      const meta = { ...loaded.meta, pinnedNodeIds: [...set] };
      const current = overlayPins(
        { ...loaded.current, nodes: loaded.current.nodes.map((n) => ({ ...n, pinned: false })) },
        meta,
      );
      await fs.writeFile(path.join(this.dir(id), "meta.json"), JSON.stringify(meta, null, 2));
      this.cache.set(id, { meta, base: loaded.base, current });
    });
  }

  async getMeta(id: string): Promise<GraphMeta> {
    return (await this.load(id)).meta;
  }

  // ── compiled skills (sidecar graphs/<id>/skills.json) ──

  private skillsPath(id: string) {
    return path.join(this.dir(id), "skills.json");
  }

  async listSkills(id: string): Promise<CompiledSkill[]> {
    try {
      return JSON.parse(await fs.readFile(this.skillsPath(id), "utf8")) as CompiledSkill[];
    } catch {
      return [];
    }
  }

  async saveSkill(id: string, skill: CompiledSkill): Promise<void> {
    return this.run(id, async () => {
      const skills = await this.listSkills(id);
      const i = skills.findIndex((s) => s.id === skill.id);
      if (i >= 0) skills[i] = skill;
      else skills.push(skill);
      await fs.writeFile(this.skillsPath(id), JSON.stringify(skills, null, 2));
    });
  }

  async deleteSkill(id: string, skillId: string): Promise<void> {
    return this.run(id, async () => {
      const skills = (await this.listSkills(id)).filter((s) => s.id !== skillId);
      await fs.writeFile(this.skillsPath(id), JSON.stringify(skills, null, 2));
    });
  }

  async getState(id: string): Promise<GraphState> {
    return (await this.load(id)).current;
  }

  /** Apply an entry with optimistic locking; persist (append journal line +
   *  rewrite meta). Returns the new current state + version. */
  async appendEntry(
    id: string,
    entry: JournalEntry,
    expectedVersion: number,
  ): Promise<{ current: GraphState; version: number }> {
    return this.run(id, async () => {
      const loaded = await this.load(id);
      if (expectedVersion !== loaded.meta.version) {
        throw new ConcurrentEditError(expectedVersion, loaded.meta.version);
      }
      const current = overlayPins(applyJournalOp(loaded.current, entry), loaded.meta);
      const meta: GraphMeta = {
        ...loaded.meta,
        version: loaded.meta.version + 1,
        nodeCount: current.nodes.length,
        edgeCount: current.edges.length,
      };
      const d = this.dir(id);
      await fs.appendFile(path.join(d, "journal.jsonl"), JSON.stringify(entry) + "\n");
      await fs.writeFile(path.join(d, "meta.json"), JSON.stringify(meta, null, 2));
      this.cache.set(id, { meta, base: loaded.base, current });
      return { current, version: meta.version };
    });
  }

  /** Undo the last journal entry (replay base + remaining). */
  async revertLast(
    id: string,
    expectedVersion: number,
  ): Promise<{ current: GraphState; version: number; removed: JournalEntry }> {
    return this.run(id, async () => {
      const loaded = await this.load(id);
      if (expectedVersion !== loaded.meta.version) {
        throw new ConcurrentEditError(expectedVersion, loaded.meta.version);
      }
      const journal = loaded.current.journal;
      if (!journal.length) throw new NotFoundError("journal is empty");
      const remaining = journal.slice(0, -1);
      const removed = journal[journal.length - 1]!;
      const current = overlayPins(replayJournal(loaded.base, remaining), loaded.meta);
      const meta: GraphMeta = {
        ...loaded.meta,
        version: loaded.meta.version + 1,
        nodeCount: current.nodes.length,
        edgeCount: current.edges.length,
      };
      const d = this.dir(id);
      await fs.writeFile(
        path.join(d, "journal.jsonl"),
        remaining.map((e) => JSON.stringify(e)).join("\n") + (remaining.length ? "\n" : ""),
      );
      await fs.writeFile(path.join(d, "meta.json"), JSON.stringify(meta, null, 2));
      this.cache.set(id, { meta, base: loaded.base, current });
      return { current, version: meta.version, removed };
    });
  }
}
