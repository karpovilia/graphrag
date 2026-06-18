#!/usr/bin/env bash
# Spawned by the hub (ASSIST_CMD) on a state change OR a RAG console message.
# Runs a headless Claude that reads the context from env and acts via the
# graphcraft MCP: curation suggestions, RAG questions, answering, find/highlight.
#
# IMPORTANT: uses `claude -p` (a FRESH, isolated session) — NOT `-c`. `-c`
# resumes the most-recent session in this folder, which is the human's live
# Claude Code session → recursion/interference. Each trigger is self-contained
# (full context is in the prompt + MCP), so no cross-run memory is needed. For
# optional continuity set ASSIST_SESSION to a fixed uuid (uses --resume).
exec >> /tmp/assist.log 2>&1
echo "=== $(date +%T) assist  graph=$GC_GRAPH  panel=$GC_PANEL  nodes=$GC_NODES  qid=${GC_QID:-} ==="
cd /home/ki/repos/graphcraft || exit 1
MODEL="${ASSIST_MODEL:-haiku}"     # light + fast by default
TOOLS="mcp__graphcraft__get_slice,mcp__graphcraft__search_nodes,mcp__graphcraft__god_nodes,mcp__graphcraft__propose,mcp__graphcraft__suggest_questions,mcp__graphcraft__get_presence,mcp__graphcraft__focus_view,mcp__graphcraft__answer_question"
# a fresh -p session must be told which MCP servers to load + trust
MCP="--mcp-config /home/ki/repos/graphcraft/.mcp.json --strict-mcp-config"
claude -p "$GC_ASSIST_PROMPT" --model "$MODEL" $MCP --allowedTools "$TOOLS" \
  ${ASSIST_SESSION:+--session-id "$ASSIST_SESSION"} \
  || echo "!! claude failed $?"
echo "=== done $(date +%T) ==="
