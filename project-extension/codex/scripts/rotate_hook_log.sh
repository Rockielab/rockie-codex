#!/usr/bin/env bash
# Rotate .codex/memory/hook.log when it exceeds MAX_LINES.
# Keeps hook.log.1 as the rotated file; older rotations are discarded.
# Intended to be called at the top of each hook (cheap — a single wc check).
set +e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$ROOT/memory/hook.log"
MAX_LINES=${HOOK_LOG_MAX_LINES:-2000}

[ ! -f "$LOG" ] && exit 0

# Fast path: stat size first, only wc -l when file is >100KB
SIZE=$(stat -f %z "$LOG" 2>/dev/null || stat -c %s "$LOG" 2>/dev/null)
[ -z "$SIZE" ] && exit 0
[ "$SIZE" -lt 102400 ] && exit 0  # <100KB, skip counting

LINES=$(wc -l < "$LOG" 2>/dev/null)
[ -z "$LINES" ] && exit 0

if [ "$LINES" -gt "$MAX_LINES" ]; then
  # Keep tail of recent entries in the new log; move full to .1
  mv "$LOG" "$LOG.1" 2>/dev/null
  tail -n 500 "$LOG.1" > "$LOG" 2>/dev/null
fi

exit 0
