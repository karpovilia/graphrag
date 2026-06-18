# GraphCraft

**Multi-user, agent-driven knowledge-graph curation.**

GraphCraft is a live, collaborative workspace where humans and AI agents curate a
knowledge graph *together*. Instead of building a graph as an opaque one-shot
pipeline — where small extraction errors cascade into wrong answers — GraphCraft
makes the graph a shared, editable artifact: an agent reads a slice, focuses the
human's canvas on a problem, proposes edits, and requests an **interactive
decision** that blocks until the human accepts / rejects / edits / pins it. Repeated
manual fixes compile into reusable **skills** that run cheaply over the whole corpus,
with provenance back to the source chunks.

> Companion academic paper: [`docs/paper.tex`](docs/paper.tex) (CIKM '26 demo).

---

## Features

- **Live collaborative canvas** — WebSocket presence, multi-cursor, "see what they
  see" (adopt another participant's selection, scene, layout & camera).
- **Agent as a first-class participant** — agents join rooms over MCP, read graph
  slices, focus the canvas, propose edits and open blocking human decisions.
- **Interactive decision loop** — accept / reject / edit / pin, end-to-end with
  journal + revert.
- **Curation tooling** — entity dedup/merge (alias-preserving), type fixes, noise
  pruning, node splitting, bi-temporal stamps (mention-time vs fact-time).
- **RAG / ToG over the graph** — provenance to source chunks, reasoning chains and
  relevant-node highlighting. Pluggable LLMs (DeepSeek, OpenAI-compatible, GLM/ZAI,
  Anthropic, or a Claude subscription).
- **Skill compiler** — turn N repeated manual edits into a 3-tier reusable skill.
- **Bilingual** — works on Russian and English graphs; RU/EN UI.

---

## Architecture

```
┌──────────────┐    WS + HTTP    ┌──────────────────────┐
│  frontend     │ ──────────────▶ │ graph-collab-service  │  Fastify + ws hub
│  (Vue 3 +     │  /api  /ws      │  rooms · presence ·    │  :4001
│   canvas)     │ ◀────────────── │  decisions · RAG       │
└──────────────┘                 └──────────┬────────────┘
        ▲                                    │ reads/writes
        │ MCP (stdio)                        ▼
┌──────────────┐                 ┌──────────────────────┐
│  mcp-service  │ ──────────────▶ │  per-graph stores      │  graphs/<id>/
│  (agent API)  │                 │  (portable JSON)       │
└──────────────┘                 └──────────────────────┘
```

### Monorepo layout

| Path | What |
|------|------|
| `packages/graph-core` | Domain model, journal, applier engine, temporal diff, skill compiler, LLM adapters, agents |
| `packages/shared` | Wire protocol & auth shared by services and frontend |
| `apps/graph-collab-service` | Fastify + WebSocket collaboration hub (rooms, presence, decisions, RAG/ToG) |
| `apps/mcp-service` | MCP (stdio) server — the agent/tool surface |
| `apps/frontend` | Vue 3 + Vite + `@krainovsd/graph` canvas, vue-i18n (RU/EN) |
| `scripts/` | Graph-building & ingestion helpers (examples; adjust paths) |
| `skill/` | `/graphcraft` skill definition |
| `docs/` | Paper, plan, demo script |

---

## Quick start (local dev)

Requirements: **Node ≥ 20** and **pnpm 9** (`corepack enable`).

```bash
pnpm install
cp .env.example .env          # then fill in what you need (see below)
pnpm dev                      # turbo runs all dev tasks
```

- Frontend: http://127.0.0.1:5173
- Collab hub: http://127.0.0.1:4001

Run a single service:

```bash
pnpm --filter @graphcraft/collab-service dev
pnpm --filter @graphcraft/frontend dev
```

Tests / typecheck:

```bash
pnpm test
pnpm typecheck
```

### Connect an agent (MCP)

The repo ships an `.mcp.json` for Claude Code / any MCP client that starts the
`@graphcraft/mcp-service` over stdio. Point its `cwd` at your checkout and the
agent gets the full GraphCraft tool surface (slice, focus, propose, request
decision, compile skill, RAG, …).

---

## Configuration

All configuration is via environment variables — see [`.env.example`](.env.example)
for the full, commented list. Highlights:

| Var | Purpose |
|-----|---------|
| `COLLAB_PORT` (4001) | Hub port |
| `GRAPHS_DIR` (`./graphs`) | Where per-graph stores live |
| `REDIS_URL` | Optional; enables multi-process / restart-safe session state |
| `DEEPSEEK_API_KEY` / `OPENAI_*` / `ZAI_*` / `ANTHROPIC_API_KEY` / `LLM_*` | Pluggable LLM (auto-detected). T1 curation + keyless graph build need none |
| `AGENT_SERVICE_TOKEN` | Static token the agent uses to join rooms |
| `JWT_SECRET`, `OAUTH_*` | Auth (GitLab/GitHub OAuth) |

> **The LLM builder and tier-3 skill compiler are the only parts that need an API
> key.** Tier-1 curation and the keyless graph builder run with no key at all.

---

## Deployment

Container deployment (Docker Compose: hub + nginx-served frontend) is documented in
**[DEPLOYMENT.md](DEPLOYMENT.md)**.

```bash
cp .env.example .env          # set secrets
docker compose up -d --build
```

---

## Security

- **Never commit secrets.** `.env` is git-ignored; only `.env.example` (with empty
  values) is tracked. Bring your own keys.
- **No data ships in this repo.** Ingested corpora (`projects/`, `data/`,
  `graphs/`, `data_test/`) are git-ignored — they may contain PII / internal links.
  Build your own from your sources.
- Rotate any key that has ever been pasted into a tracked file.

---

## License

See repository settings. The accompanying paper is the canonical description of the
system and its evaluation.
