#!/usr/bin/env bash
# repair_fts.sh — rebuild rockie's FTS5 virtual tables.
#
# Architecture audit F10: corruption of any FTS5 shadow table
# (_data / _idx / _content) can silently break every FTS-joined query.
# This script runs SQLite's documented rebuild command for each of the
# four FTS virtual tables.
#
# Usage:
#   .codex/scripts/repair_fts.sh               # rebuild everything
#   .codex/scripts/repair_fts.sh learnings     # rebuild one table
#
# Exit 0 on success, 2 if the DB doesn't exist, 3 on sqlite errors.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="$ROOT/memory/workflow.db"
SQLITE=/usr/bin/sqlite3

[ -f "$DB" ] || { echo "no workflow.db at $DB" >&2; exit 2; }

ALL_FTS="learnings_fts dead_ends_fts experiments_fts"
TARGETS="${1:-all}"

if [ "$TARGETS" = "all" ]; then
  TARGETS="$ALL_FTS"
else
  # Map short names to the _fts suffix if needed
  case "$TARGETS" in
    *_fts) : ;;
    *)     TARGETS="${TARGETS}_fts" ;;
  esac
fi

for t in $TARGETS; do
  echo "rebuilding $t ..."
  "$SQLITE" "$DB" "PRAGMA trusted_schema=1; INSERT INTO $t($t) VALUES('rebuild');" \
    || { echo "rebuild failed for $t" >&2; exit 3; }
done

echo "✓ FTS5 rebuild complete"
"$SQLITE" "$DB" "SELECT
  'learnings: '  || (SELECT count(*) FROM learnings_fts)      || '  ' ||
  'dead_ends: '  || (SELECT count(*) FROM dead_ends_fts)      || '  ' ||
  'experiments: ' || (SELECT count(*) FROM experiments_fts);"
