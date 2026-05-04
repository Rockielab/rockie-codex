#!/usr/bin/env bash
# PreToolUse(Bash) hook: intercept `git commit` and require a valid /clean sentinel.
# Bypass: prefix command with CLEAN_BYPASS=1 (or set env var).
set +e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
bash "$ROOT/scripts/rotate_hook_log.sh" 2>/dev/null

INPUT=$(cat)
CMD=$(echo "$INPUT" | python3 -c '
import sys,json
d=json.load(sys.stdin)
print(d.get("tool_input",{}).get("command",""))
' 2>/dev/null)

# Fast path: not a git commit
echo "$CMD" | grep -qE '(^|[;&|[:space:]])git[[:space:]]+commit([[:space:]]|$)' || exit 0

echo "[$(date -Iseconds)] pre-commit-gate: fired" >> "$ROOT/memory/hook.log"

# Scope: only enforce when the git command targets the repo that owns this
# hook. The hook is registered via this repo's hooks.json but Codex
# Code fires it on every Bash tool call regardless of cwd — so commits in
# other repos would be blocked by a sentinel they don't know about. Skip
# unless we're in our own repo.
CMD_CWD=$(echo "$INPUT" | python3 -c '
import sys,json
d=json.load(sys.stdin)
print(d.get("cwd") or d.get("tool_input",{}).get("cwd",""))
' 2>/dev/null)
PROBE_CWD="${CMD_CWD:-$PWD}"
OWN_REPO="$(cd "$ROOT/.." 2>/dev/null && pwd -P)"
# Resolve target repo root from cwd of the command.
# ONLY enforce when TARGET_REPO is our own repo. Empty (no git repo at
# all) or a different repo both skip — previous logic was "enforce if
# TARGET_REPO is empty OR matches own", which blocked commits run from
# non-git directories (architecture audit F2).
TARGET_REPO=$(cd "$PROBE_CWD" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$TARGET_REPO" ] || [ "$TARGET_REPO" != "$OWN_REPO" ]; then
  echo "[$(date -Iseconds)] pre-commit-gate: skipped (repo=${TARGET_REPO:-<none>} != own=$OWN_REPO)" >> "$ROOT/memory/hook.log"
  exit 0
fi

# Bypass via command-inline env var OR shell env
if echo "$CMD" | grep -qE '(^|[;&|[:space:]])CLEAN_BYPASS=1\b' || [ "$CLEAN_BYPASS" = "1" ]; then
  echo "[pre-commit-gate] CLEAN_BYPASS=1 — allowing" >&2
  echo "[$(date -Iseconds)] pre-commit-gate: bypass" >> "$ROOT/memory/hook.log"
  exit 0
fi

HASH=$(cd "$PROBE_CWD" 2>/dev/null && bash "$ROOT/scripts/compute_clean_hash.sh" 2>/dev/null)
if [ -z "$HASH" ] || [ "$HASH" = "no-changes" ]; then
  exit 0
fi

SENTINEL="$ROOT/.state/clean-ok-$HASH"
if [ -f "$SENTINEL" ]; then
  exit 0
fi

{
  echo "[pre-commit-gate] BLOCKED: no valid /clean sentinel for the current staged set."
  echo "[pre-commit-gate] Expected: .codex/.state/clean-ok-$HASH"
  echo "[pre-commit-gate] Run: python3 .agents/skills/clean/audit.py --scope staged"
  echo "[pre-commit-gate] Or bypass: prefix commit with  CLEAN_BYPASS=1"
} >&2
exit 2
