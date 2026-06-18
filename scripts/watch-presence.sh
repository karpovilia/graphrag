#!/usr/bin/env bash
# Event watcher for the /loop assistant. Uses the hub's presence long-poll
# (GET /presence/wait?since=rev) so it returns within ~100ms of a real change
# instead of polling. Exits the moment the (panel + selection) signature of any
# active human differs from the baseline ($2) — which re-invokes the agent.
#   usage: watch-presence.sh <graphId> <baseline-signature> [max-seconds]
set -u
GRAPH="${1:?graphId}"
BASELINE="${2:-}"
DEADLINE=$(( $(date +%s) + ${3:-1800} ))   # default 30-min safety cap

BASE="http://127.0.0.1:4001/api/graphs/${GRAPH}"

# sig: "panel:selids" per active human (selection or panel set), sorted+joined.
# Reads {rev, participants} on stdin; prints "<rev>\t<sig>".
read_state() {
  python3 -c "
import sys,json
try: d=json.load(sys.stdin)
except Exception: print('-1\tERR'); sys.exit(0)
hs=[p for p in d.get('participants',[]) if p.get('kind')=='human' and (p.get('selection') or p.get('panel'))]
sig='||'.join(sorted(f\"{p.get('panel')}:{','.join(sorted(s['id'] for s in p.get('selection') or []))}\" for p in hs))
print(f\"{d.get('rev',-1)}\t{sig}\")
"
}

rev=-1
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  out="$(curl -s --max-time 30 "${BASE}/presence/wait?since=${rev}" | read_state)"
  rev="${out%%$'\t'*}"
  sig="${out#*$'\t'}"
  [ "$sig" = "ERR" ] && { sleep 1; continue; }
  if [ "$sig" != "$BASELINE" ]; then
    echo "CHANGED|$sig"
    exit 0
  fi
done
echo "TIMEOUT|$BASELINE"
exit 0
