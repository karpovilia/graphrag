import { promises as fs } from "node:fs";
import path from "node:path";
import type { ParsedDocument, ProjectMeta } from "@graphcraft/core";

/** Persists projects (corpora): the raw/parsed source shared by graph variants.
 *  Layout: <dir>/<projectId>/{meta.json, documents.json}. Graphs stay flat in
 *  the graph store but carry meta.projectId. */
export class ProjectStore {
  constructor(private dirRoot: string) {}

  private dir(id: string) {
    return path.join(this.dirRoot, id);
  }

  async create(meta: ProjectMeta, documents: ParsedDocument[]): Promise<ProjectMeta> {
    const d = this.dir(meta.id);
    await fs.mkdir(d, { recursive: true });
    const full = { ...meta, documentCount: documents.length };
    await fs.writeFile(path.join(d, "meta.json"), JSON.stringify(full, null, 2));
    await fs.writeFile(path.join(d, "documents.json"), JSON.stringify(documents, null, 2));
    return full;
  }

  async list(): Promise<ProjectMeta[]> {
    let entries: string[] = [];
    try {
      entries = await fs.readdir(this.dirRoot);
    } catch {
      return [];
    }
    const out: ProjectMeta[] = [];
    for (const e of entries) {
      try {
        out.push(JSON.parse(await fs.readFile(path.join(this.dir(e), "meta.json"), "utf8")) as ProjectMeta);
      } catch {
        /* not a project dir */
      }
    }
    return out;
  }

  async delete(id: string): Promise<void> {
    await fs.rm(this.dir(id), { recursive: true, force: true });
  }

  async get(id: string): Promise<ProjectMeta | null> {
    try {
      return JSON.parse(await fs.readFile(path.join(this.dir(id), "meta.json"), "utf8")) as ProjectMeta;
    } catch {
      return null;
    }
  }

  async documents(id: string): Promise<ParsedDocument[]> {
    try {
      return JSON.parse(await fs.readFile(path.join(this.dir(id), "documents.json"), "utf8")) as ParsedDocument[];
    } catch {
      return [];
    }
  }

  /** Append new parsed documents to a project's source (day-2 stream). */
  async addDocuments(id: string, docs: ParsedDocument[]): Promise<ParsedDocument[]> {
    const existing = await this.documents(id);
    const merged = [...existing, ...docs];
    const d = this.dir(id);
    await fs.writeFile(path.join(d, "documents.json"), JSON.stringify(merged, null, 2));
    const meta = await this.get(id);
    if (meta) await fs.writeFile(path.join(d, "meta.json"), JSON.stringify({ ...meta, documentCount: merged.length }, null, 2));
    return docs;
  }
}
