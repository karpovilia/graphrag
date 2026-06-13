---
name: graphcraft
description: "Use when curating, cleaning, deduplicating, or improving a knowledge graph — merging fragmented entities, fixing types, pruning noise, splitting conflated nodes, or compiling repeated edits into reusable skills. Drives a live GraphCraft collab room via MCP tools as a first-class participant: read a graph slice, focus the human's canvas on a problem, propose edits, and request an interactive human decision (accept/reject/edit/pin) that blocks until they act. Works on Russian and English graphs."
---

# /graphcraft

Curate a knowledge graph **with** the human, live. You are a participant in a
shared collab room: your focus commands move their canvas, your proposals land
in their review queue, and you can block on their decision. Every edit is
journaled and reversible; the journal is training data for reusable skills.

The MCP tools talk to a running `graph-collab-service` (default
`http://127.0.0.1:4001`, override with `COLLAB_HTTP_URL`).

## The curation loop

1. **Orient.** `list_graphs` → pick one. `get_graph` for size. `god_nodes` /
   `surprise_edges` to find hotspots; `run_agent` (`dedup` / `orphans`) to
   populate structural suggestions.
2. **Investigate a problem.** `search_nodes` to find candidates; `get_slice`
   (seeds + depth) to see the local neighbourhood before acting.
3. **Show the human.** `focus_view` centers their canvas on the nodes you're
   reasoning about — always do this before proposing, so they see what you see.
4. **Decide together.** For anything non-trivial, `request_decision` (it
   focuses the canvas and BLOCKS until a human clicks accept/reject/edit/pin).
   - `accept` → you then `apply_op` the edit.
   - `edit` → apply with their `editedPayload` instead.
   - `reject` → drop it. `pin` → the node is now protected from all agents;
     never propose on it again.
   For low-risk batches, `propose` instead (queues a suggestion they handle
   later) — never auto-apply destructive edits without a decision.
5. **Apply.** `apply_op` with the journal op + payload (see ops below).
6. **Compile.** After several similar edits, `journal` to get their ids, then
   `compile_skill` (tier `structural` = free/no-LLM, `embedding`, or `llm`).
   `run_skill` with `dryRun: true` FIRST to preview the impact, then for real.
   `revert` undoes the last change.

## Curation ops (for `apply_op`)

- `merge_nodes` `{survivorId, absorbedIds[], newName?}` — fold duplicates.
- `split_node` `{originalId, newNodes[], edgeRedirect{}}` — split a conflated node.
- `retype_node` `{nodeId, newType}` · `update_node_name` `{nodeId, name}` ·
  `set_summary` `{nodeId, summary}`.
- `delete_node` `{nodeId, reason?}` · `delete_edge` `{edgeId, reason?}` (reason
  ⇒ soft invalidation, revertable) · `edit_edge` `{edgeId, updates{}}` ·
  `add_edge` `{edge{}}` · `move_to_community` `{nodeId, toCommunityId}`.

## Rules

- **Focus before you propose.** The human should always be able to see the
  nodes a decision is about.
- **Respect pins.** A pinned node is off-limits to every agent and skill.
- **Prefer suggestions to silent edits.** Apply directly only for edits the
  human accepted, or trivially safe ones.
- **Dry-run skills first.** Show the previewed delta before a real run; big
  deletes need `confirmDestructive: true`.
- Quote RAG/graph text verbatim; speak the corpus's language with the user.

## If the backend isn't running

  cd /home/ki/repos/graphcraft && pnpm gen:sample        # a demo graph
  COLLAB_PORT=4001 GRAPHS_DIR=$PWD/graphs pnpm --filter @graphcraft/collab-service start

Then open the frontend to watch the canvas react to your focus/decisions.
