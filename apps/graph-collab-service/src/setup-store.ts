import type { CorpusProfile, RankedScenario } from "@graphcraft/core";

/** A note in the setup-flow assistant dock — either the human or the agent
 *  (/graphcraft over MCP). The agent "leads": it analyzes, recommends a
 *  scenario and prefills steps; the human confirms in the UI. */
export interface AssistantNote {
  by: string;
  at: string;
  text: string;
  /** the stepper step this message belongs to → interleaves chat with steps. */
  step?: number;
}

/** Live, per-project state of the AI-led graph setup flow (pre-graph). Held in
 *  memory: a setup is a short-lived conversation that ends when the graph is
 *  built. Both the UI and the MCP agent read/patch the same session. */
export interface SetupSession {
  projectId: string;
  goal: string;
  graphName: string;
  profile: CorpusProfile | null;
  scenarios: RankedScenario[];
  selectedScenarioId: string | null;
  /** entity kinds confirmed by the human (chips); seeded from the profile. */
  confirmedTypes: string[];
  extractor: "keyless" | "lightrag";
  communities: boolean;
  axis: "tx" | "valid";
  /** current stepper position (1..7). */
  step: number;
  status: "idle" | "analyzing" | "ready" | "building" | "done";
  assistantNotes: AssistantNote[];
  builtGraphId?: string;
  updatedAt: string;
}

const PATCHABLE = [
  "goal", "graphName", "selectedScenarioId", "confirmedTypes",
  "extractor", "communities", "axis", "step",
] as const;
type PatchKey = (typeof PATCHABLE)[number];
export type SetupPatch = Partial<Pick<SetupSession, PatchKey>>;

export class SetupStore {
  private sessions = new Map<string, SetupSession>();

  get(projectId: string): SetupSession | null {
    return this.sessions.get(projectId) ?? null;
  }

  ensure(projectId: string): SetupSession {
    let s = this.sessions.get(projectId);
    if (!s) {
      s = {
        projectId,
        goal: "",
        graphName: "",
        profile: null,
        scenarios: [],
        selectedScenarioId: null,
        confirmedTypes: [],
        extractor: "keyless",
        communities: true,
        axis: "tx",
        step: 1,
        status: "idle",
        assistantNotes: [],
        updatedAt: new Date().toISOString(),
      };
      this.sessions.set(projectId, s);
    }
    return s;
  }

  set(session: SetupSession): SetupSession {
    session.updatedAt = new Date().toISOString();
    this.sessions.set(session.projectId, session);
    return session;
  }

  patch(projectId: string, partial: SetupPatch): SetupSession {
    const s = this.ensure(projectId);
    for (const k of PATCHABLE) {
      if (partial[k] !== undefined) (s as unknown as Record<string, unknown>)[k] = partial[k];
    }
    return this.set(s);
  }

  addNote(projectId: string, by: string, text: string, step?: number): SetupSession {
    const s = this.ensure(projectId);
    s.assistantNotes.push({ by, at: new Date().toISOString(), text, step: step ?? s.step });
    return this.set(s);
  }
}
