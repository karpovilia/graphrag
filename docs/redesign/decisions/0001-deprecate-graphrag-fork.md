# ADR 0001 — Deprecate the in-tree Microsoft GraphRAG fork

- **Status:** accepted
- **Date:** 2026-05-04
- **Phase:** R2 / Phase 0.6
- **Decision-makers:** ki (lead), GraphRAG Explorer team

## Context

The repository carried a modified copy of Microsoft GraphRAG at
`backend/graphrag/` (≈30k LOC, full vendor copy of the upstream package
with local edits). Two local edits in particular mattered:

- `backend/graphrag/graphrag/index/operations/cluster_graph.py:123-146`
  added a Bayan clusterer (via `bayanpy`) alongside the upstream Leiden;
- `backend/api/graphrag_processing.py:33-72` injected language-aware
  instructions (Russian by default) into the upstream system prompts at
  call time.

Everything else in the fork tracked upstream Microsoft GraphRAG.

The R2 redesign (see `docs/redesign/requirements.md` and
`docs/redesign/plan.md`) makes alternative builders/cleaners/clusterers
first-class plugins behind our own protocols. In that world the
in-tree fork is a liability:

1. Each upstream release widens the diff we have to review and rebase.
2. Our domain model (`backend/api/domain/`) and registries
   (Phase 1) talk to the fork only through a future `MicrosoftBuilder`
   adapter — patching upstream internals is no longer the right
   surface.
3. Bayan and the language-prompt edits aren't actually "Microsoft
   GraphRAG fixes" — they're our own strategy plugins that happen to
   reuse upstream as one of several backends.

User decision (2026-05-04): "можно полностью удалить" — full deletion
preferred over leaving the fork in place but unworkspaced.

## Decision

Delete `backend/graphrag/` from the working tree entirely. Add
`graphrag>=1.0.0` as a regular PyPI dependency in
`backend/api/pyproject.toml`. Carry no patches against upstream.

The local edits move out:

- **Bayan clusterer** → re-implemented as
  `BayanRecluster` plugin in Phase 1.3 against our own
  `ClustererProtocol`. The standalone `bayanpy` library remains a
  workspace dependency.
- **Language-aware prompts** → shipped as our own prompt set under
  `backend/api/prompts/` (created in Phase 1) and threaded through the
  `MicrosoftBuilder` adapter via a `prompt_overrides` argument.

The old API endpoints (`/api/prompt`, `/api/graph/{id}`, etc.) that
lived in `backend/api/__main__.py` and depended on the fork are
retired in this same change. `__main__.py` is replaced with a minimal
R2 stub that registers LLM clients and exposes `/api/health`. The real
endpoints come back in Phase 1 over the new domain model.

## Consequences

### Positive
- −30k LOC in the repo. No more vendor sync churn.
- One source of truth for upstream behavior — the published package.
- Our edits become reviewable plugins instead of patches against
  someone else's internals.
- License story simplifies (no embedded MIT-licensed third-party tree).

### Negative
- Until Phase 1.2 lands `MicrosoftBuilder`, no GraphRAG-style queries
  work. The legacy demo at `https://graph-rag.apsolutions.ru` will
  read from a previously committed snapshot or stay offline during
  the R2 build-up. (User opted for local-only deploy in Q10, so
  this is acceptable.)
- Pinned to upstream API surface. A breaking change in `graphrag`
  upstream forces an adapter-level fix. Mitigation: `graphrag>=1.0.0`
  pin uses upper bound none for now; a tighter pin lands when Phase
  1.2 actually exercises the API.
- Bayan re-implementation in Phase 1.3 is real work. Mitigation: the
  existing fork code in git history serves as the reference.

### Neutral
- `bayanpy`, `igraph`, `leidenalg`, `networkx`, `polars` stay as
  workspace dev deps. We'll need `igraph`/`leidenalg`/`networkx`
  again in Phase 1 for reimplementing clusterers; keeping them avoids
  a churn.

## Alternatives considered

1. **Keep the fork, just remove from the workspace.** Less destructive
   but leaves us paying review tax on upstream changes without any
   practical benefit. Rejected.
2. **Keep the fork, lift only the entry point onto PyPI graphrag.**
   Same review tax; rejected.
3. **Vendor only the cluster_graph module.** Smaller surface but still
   a fork. Rejected — the right home for Bayan is our plugin
   registry, not somebody else's `index/operations/`.

## Rollback

If Phase 1.2 reveals a blocker that the upstream package doesn't
solve, the fork is recoverable from git history (commit
`f877c77` and earlier). Rollback procedure:

```
git restore --source=2176888~1 -- backend/graphrag/
# add 'graphrag' back to backend/pyproject.toml [tool.uv.workspace]
# remove 'graphrag>=1.0.0' from backend/api/pyproject.toml deps
uv sync --all-packages
```

This recovery is documented as an option but not expected.

## References

- Phase 0.6 in `docs/redesign/plan.md`
- Q1 resolution in `docs/redesign/plan.md` § 10
- Memory: `~/.claude/projects/-home-ki-repos-graphrag/memory/project_redesign_r2.md`
- Vendored fork removal commit on branch `refactor/r2-phase-0`
