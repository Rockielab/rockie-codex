#!/usr/bin/env bash
# Idempotent: creates workflow.db from schema.sql if missing, applies
# schema.sql + any pending migrations to an existing DB.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="$ROOT/memory/workflow.db"
SCHEMA="$ROOT/memory/schema.sql"
MIGRATIONS="$ROOT/memory/migrations"
# Pin to /usr/bin/sqlite3 — some distros ship a sqlite3 on PATH without
# FTS5. /usr/bin/sqlite3 on macOS has FTS5 compiled in.
SQLITE=/usr/bin/sqlite3

# Safer corruption probe: instead of "zero-sized file ⇒ delete",
# actually query sqlite_master. A valid SQLite DB in WAL mode can have
# a 0-byte main file while all data lives in .db-wal — the old check
# would wipe an active transaction's WAL. Now we only remove the DB
# if sqlite3 itself can't open + query sqlite_master.
if [ -f "$DB" ]; then
  if ! "$SQLITE" "$DB" "SELECT 1 FROM sqlite_master LIMIT 1;" >/dev/null 2>&1; then
    echo "db: unreadable $DB — removing and reinitializing" >&2
    rm -f "$DB" "$DB-wal" "$DB-shm"
  fi
fi

"$SQLITE" "$DB" < "$SCHEMA"

# If this is a brand-new DB (user_version still 0 after baseline), set it
# to 1 — schema.sql IS version 1 baseline.
CUR=$("$SQLITE" "$DB" "PRAGMA user_version;")
if [ "$CUR" -eq 0 ]; then
  "$SQLITE" "$DB" "PRAGMA user_version = 1;"
  CUR=1
fi

# Apply numbered migrations in order, bumping user_version after each.
if [ -d "$MIGRATIONS" ]; then
  while IFS= read -r f; do
    base=$(basename "$f")
    n="${base%%_*}"
    n=$((10#$n))                # strip leading zeros safely (avoid octal)
    if [ "$n" -gt "$CUR" ]; then
      echo "applying migration $base (→ user_version=$n)"
      "$SQLITE" "$DB" < "$f"
      "$SQLITE" "$DB" "PRAGMA user_version = $n;"
      CUR="$n"
    fi
  done < <(find "$MIGRATIONS" -maxdepth 1 -type f -name '*.sql' -print | sort)
fi

echo "db initialized: $DB"
VER=$("$SQLITE" "$DB" "PRAGMA user_version;")
"$SQLITE" "$DB" "SELECT
  'schema v$VER · ' ||
  (SELECT count(*) FROM learnings)              || ' learnings, ' ||
  (SELECT count(*) FROM dead_ends)              || ' dead-ends, ' ||
  (SELECT count(*) FROM experiments)            || ' experiments, ' ||
  (SELECT count(*) FROM code_pool)              || ' pool-entries, ' ||
  (SELECT count(*) FROM hypothesis_calibration) || ' predictions, ' ||
  (SELECT count(*) FROM sessions)               || ' sessions, ' ||
  (SELECT count(*) FROM notifications)          || ' notifications';"
