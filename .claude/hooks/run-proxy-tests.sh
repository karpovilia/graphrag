#!/usr/bin/env bash
# PostToolUse hook: after Edit/Write/MultiEdit on a frontend/ or backend/
# file, run the regression suite. For frontend files this means BOTH:
#   - pnpm vue-tsc --noEmit  (type errors don't surface in playwright)
#   - pnpm playwright test e2e/proxy.spec.ts
# For backend files: pnpm playwright test e2e/proxy.spec.ts (covers
# /api/* contracts via the dev proxy).
# Always exits 0 — non-blocking warning, not a hard stop.

set -u

payload=$(cat)
fp=$(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
ti = d.get("tool_input") or {}
tr = d.get("tool_response") or {}
print(ti.get("file_path") or tr.get("filePath") or "")
')

case "$fp" in
  */frontend/*|*/backend/*) ;;
  *) exit 0 ;;
esac

# Edits to the e2e specs themselves: don't loop.
case "$fp" in
  */e2e/*) exit 0 ;;
esac

is_frontend=0
case "$fp" in
  */frontend/*) is_frontend=1 ;;
esac

basename_fp=$(basename -- "$fp")
printf '[hook] regression after %s\n' "$basename_fp"

# 1. vue-tsc only for frontend edits — backend changes don't affect TS types.
if [ "$is_frontend" -eq 1 ]; then
  printf '[hook] vue-tsc --noEmit\n'
  if ! tsc_out=$(cd /home/ki/repos/graphrag/frontend && pnpm vue-tsc --noEmit 2>&1); then
    printf '%s\n' "$tsc_out" | tail -25
    printf '[hook] vue-tsc FAILED — fix type errors before relying on green e2e\n'
  else
    printf '[hook] vue-tsc OK\n'
  fi
fi

# 2. playwright proxy regression — covers backend contracts + frontend mount.
printf '[hook] playwright e2e/proxy.spec.ts\n'
e2e_out=$(cd /home/ki/repos/graphrag/e2e && pnpm playwright test proxy.spec.ts --reporter=line 2>&1)
e2e_status=$?
printf '%s\n' "$e2e_out" | tail -15
if [ "$e2e_status" -ne 0 ]; then
  printf '[hook] e2e FAILED (exit %s) — non-blocking\n' "$e2e_status"
fi

exit 0
