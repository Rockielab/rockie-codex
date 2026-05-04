#!/usr/bin/env bash
# SessionStart hook — runs once at the beginning of every Codex session.
#
# Three jobs:
#   1. Ensure the memory DB exists + schema is applied.
#   2. One-shot migrate any legacy JSONL/team-MD corrections from the
#      invoking repo into SQLite (source files are renamed *.migrated so
#      this is idempotent).
#   3. Surface top-K active memories (repo-tier + global-tier) into
#      <repo>/.codex/memory/rules-compiled.md so AGENTS.md can reference
#      them and the rules load into context.
#
# Exits silently if the repo has no .codex/ dir or we're not in a git repo.

set -u

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "")"
if [ -z "$REPO_ROOT" ]; then
  exit 0
fi

SCRIPTS="$HOME/.codex/scripts/memory"

# 1. Ensure DB exists (lib.connect() runs the schema DDL idempotently).
python3 -c "import sys; sys.path.insert(0, '$SCRIPTS'); import lib; lib.connect()" 2>/dev/null || true

# 2. Migrate legacy JSONL/team-MD if any remain (no-op after first run).
python3 "$SCRIPTS/migrate-jsonl.py" --repo "$REPO_ROOT" 2>&1 | sed 's/^/  /' || true

# 3. Surface active memories into the repo's rules-compiled.md.
python3 "$SCRIPTS/surface.py" --repo "$REPO_ROOT" 2>&1 | sed 's/^/  /' || true

exit 0
