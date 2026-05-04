#!/usr/bin/env bash
# UserPromptSubmit hook — nudge the main agent when /deploy-team dashboards
# are still running.
#
# The `/deploy-team` orchestrator keeps its Express server alive after the
# team finishes so the developer can review the thread. But every unreaped
# invocation leaves a Node process holding a port. This hook surfaces the
# situation on each user prompt (throttled) so the main agent remembers to
# ask the user: "these are still running, kill them?"
#
# The hook does NOT auto-kill. The human stays in the loop.
#
# Throttle: re-nudge only when the process count CHANGES, or when 10 min+
# have passed since the last nudge — so it doesn't spam every prompt.

set -u

STATE_DIR="$HOME/.codex/.state"
STATE_FILE="$STATE_DIR/orphan-nudge"
mkdir -p "$STATE_DIR" 2>/dev/null

PIDS=$(pgrep -f "node.*teams/orchestrator/index.js" 2>/dev/null | tr '\n' ' ')
COUNT=$(echo "$PIDS" | awk '{print NF}')

if [ "$COUNT" = "0" ]; then
  rm -f "$STATE_FILE" 2>/dev/null
  exit 0
fi

NOW=$(date +%s)
LAST_COUNT=0
LAST_TS=0
if [ -f "$STATE_FILE" ]; then
  LAST_COUNT=$(awk 'NR==1' "$STATE_FILE" 2>/dev/null)
  LAST_TS=$(awk 'NR==2' "$STATE_FILE" 2>/dev/null)
  LAST_COUNT=${LAST_COUNT:-0}
  LAST_TS=${LAST_TS:-0}
fi

SINCE=$((NOW - LAST_TS))
if [ "$COUNT" = "$LAST_COUNT" ] && [ "$SINCE" -lt 600 ]; then
  exit 0
fi

echo "$COUNT" > "$STATE_FILE"
echo "$NOW" >> "$STATE_FILE"

echo ""
echo "ℹ  dashboard-orphan: $COUNT team dashboard process(es) still running from prior /deploy-team invocations."
echo "   PIDs: $PIDS"
echo ""
echo "   Main agent: ask the developer if these should be killed."
echo "   Quick kill all: pkill -f 'node.*teams/orchestrator/index.js'"
echo "   Or per-PID: kill <pid>"
echo ""
exit 0
