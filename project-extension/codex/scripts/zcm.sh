#!/usr/bin/env bash
# zcm.sh — Zero-Cost Monitor.
#
# Polls a running training process with $0 LLM cost. Wakes the caller
# (exit 0 = normal completion, non-zero = anomaly) so the agent is only
# consulted when there's actually something to decide.
#
# Ported pattern: Deep Researcher Agent (arXiv 2604.05854). Their
# measured cost was $0.08/24h vs $1.60 for conventional polling with
# per-tick LLM calls.
#
# Exit codes:
#   0  process ended normally (zero exit code, last log line not an error)
#   1  process exited non-zero (training crashed)
#   2  process still alive but anomaly detected (NaN, OOM, plateau >N ticks)
#   3  ZCM timed out (wall clock exceeded --max-seconds)
#   4  bad invocation
#
# Usage:
#   zcm.sh --pid 12345 --log path/to/train.log [--interval 60] [--max-seconds 86400]
#          [--queue-id 42] [--notify-tier 2]
set -u

INTERVAL=60
MAX_SECONDS=86400   # 24h default ceiling
NOTIFY_TIER=2       # tier used when waking via notify.sh
PID=""; LOG=""; QUEUE_ID=""
# Regex anchored per-pattern to avoid false positives:
#   - \bnan\b / NaN catches only the token, not "nanometer" etc.
#   - "Killed" matched at line start only (real OOM-kills print it that way);
#     avoids log lines like "Killed the zombie process" mid-sentence.
ANOMALY_PATTERNS='(\b[Nn]a[Nn]\b|NaN loss|OutOfMemoryError|CUDA out of memory|RuntimeError: shape|^Killed$|^Killed: 9|\bOOM\b)'
PLATEAU_WINDOW=6    # consecutive ticks of identical step-count before flagging

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

while [ $# -gt 0 ]; do
  case "$1" in
    --pid)           PID="$2"; shift 2 ;;
    --log)           LOG="$2"; shift 2 ;;
    --interval)      INTERVAL="$2"; shift 2 ;;
    --max-seconds)   MAX_SECONDS="$2"; shift 2 ;;
    --queue-id)      QUEUE_ID="$2"; shift 2 ;;
    --notify-tier)   NOTIFY_TIER="$2"; shift 2 ;;
    *) echo "zcm: unknown arg '$1'" >&2; exit 4 ;;
  esac
done

if [ -z "$PID" ] || [ -z "$LOG" ]; then
  echo "usage: zcm.sh --pid N --log PATH [--interval S] [--max-seconds S] [--queue-id N]" >&2
  exit 4
fi

EVENTS="$ROOT/memory/zcm_events.jsonl"
mkdir -p "$(dirname "$EVENTS")"

emit_event() {
  local kind="$1" msg="$2"
  local ts
  ts=$(date -u +%FT%TZ)
  printf '{"ts":"%s","pid":%s,"queue_id":%s,"kind":"%s","msg":%s}\n' \
    "$ts" "$PID" "${QUEUE_ID:-null}" "$kind" "$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$msg")" \
    >> "$EVENTS"
}

wake() {
  local kind="$1" reason="$2"
  emit_event "$kind" "$reason"
  # If ntfy configured, push a tier-2 notice
  if [ -x "$ROOT/scripts/notify.sh" ]; then
    bash "$ROOT/scripts/notify.sh" "$NOTIFY_TIER" "zcm: $kind" \
      "pid=$PID queue_id=${QUEUE_ID:-—} reason=$reason" "zcm-${QUEUE_ID:-pid$PID}" \
      >/dev/null 2>&1 || true
  fi
}

emit_event "start" "interval=${INTERVAL}s max=${MAX_SECONDS}s log=$LOG"

START_TS=$(date +%s)
LAST_STEP=""
PLATEAU_COUNT=0

while true; do
  # Wall-clock ceiling
  NOW=$(date +%s)
  if [ $((NOW - START_TS)) -ge "$MAX_SECONDS" ]; then
    wake "timeout" "wall-clock ${MAX_SECONDS}s exceeded"
    # Best-effort stop the process so it doesn't keep burning GPU
    kill -TERM "$PID" 2>/dev/null
    exit 3
  fi

  # Liveness
  if ! kill -0 "$PID" 2>/dev/null; then
    # Reap, check exit code via /proc if available, else just inspect log
    TAIL=$(tail -n 50 "$LOG" 2>/dev/null)
    if echo "$TAIL" | grep -qE "$ANOMALY_PATTERNS"; then
      wake "died-error" "process $PID exited; anomaly in last 50 log lines"
      exit 1
    fi
    wake "died-clean" "process $PID exited; log tail clean"
    exit 0
  fi

  # Anomaly scan (only the last 200 lines — cheap)
  TAIL=$(tail -n 200 "$LOG" 2>/dev/null)
  if echo "$TAIL" | grep -qE "$ANOMALY_PATTERNS"; then
    wake "anomaly" "pattern match in log tail (still running)"
    exit 2
  fi

  # Plateau detection: same step number for PLATEAU_WINDOW consecutive polls
  STEP=$(echo "$TAIL" | grep -oE 'step[[:space:]=:]+[0-9]+' | tail -1 | grep -oE '[0-9]+$')
  if [ -n "$STEP" ]; then
    if [ "$STEP" = "$LAST_STEP" ]; then
      PLATEAU_COUNT=$((PLATEAU_COUNT + 1))
    else
      PLATEAU_COUNT=0
      LAST_STEP="$STEP"
    fi
    if [ "$PLATEAU_COUNT" -ge "$PLATEAU_WINDOW" ]; then
      wake "plateau" "step=$STEP for $PLATEAU_COUNT ticks"
      exit 2
    fi
  fi

  sleep "$INTERVAL"
done
