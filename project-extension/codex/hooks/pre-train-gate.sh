#!/usr/bin/env bash
# PreToolUse(Bash) hook: if the command looks like a long-running training
# launch (runs a .py script that matches TRAIN_* / run_* / train* patterns),
# require a valid dry-run sentinel. Bypass: prefix with DRY_RUN_BYPASS=1.
#
# The sentinel invalidates on any change to the script or to adjacent
# requirements.txt / pyproject.toml / environment.yml. Re-run the
# dry-run smoke test to regenerate it.
set +e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
bash "$ROOT/scripts/rotate_hook_log.sh" 2>/dev/null

INPUT=$(cat)
CMD=$(echo "$INPUT" | python3 -c '
import sys,json
d=json.load(sys.stdin)
print(d.get("tool_input",{}).get("command",""))' 2>/dev/null)

# Strip `#` shell-comments so `python3 train.py # --smoke` can't bypass
# the real-training check by putting flags in a comment (security M-2).
CMD_NO_COMMENT="${CMD%%#*}"

# Fast path: must match a training-launch pattern. Broadened vs prior
# `python3?` — that missed `python3.11`, `python3.12`, etc. (security M-2).
echo "$CMD_NO_COMMENT" | grep -qE '(python[0-9]*(\.[0-9]+)?|accelerate|torchrun|deepspeed)[[:space:]].*\.py' || exit 0

# Extract the .py target from the command. Prefer the last .py token — handles
# "torchrun --nproc-per-node 8 src/train.py --arg X" layouts.
SCRIPT_PATH=$(echo "$CMD_NO_COMMENT" | grep -oE '[[:graph:]]+\.py' | tail -1)
[ -z "$SCRIPT_PATH" ] && exit 0

# Smoke-test exceptions — check the comment-stripped string so a `# --smoke`
# tail can't smuggle a real training command through.
if echo "$CMD_NO_COMMENT" | grep -qE '(--smoke|--dry[-_]?run|--test|--quick)'; then
  exit 0
fi

# Scope: only enforce inside the repo that owns this hook.
OWN_REPO="$(cd "$ROOT/.." 2>/dev/null && pwd -P)"
CWD_JSON=$(echo "$INPUT" | python3 -c '
import sys,json
d=json.load(sys.stdin)
print(d.get("cwd") or d.get("tool_input",{}).get("cwd",""))' 2>/dev/null)
TARGET_REPO=$(cd "${CWD_JSON:-$PWD}" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$TARGET_REPO" ] || [ "$TARGET_REPO" != "$OWN_REPO" ]; then
  exit 0
fi

# Bypass: env var or inline
if echo "$CMD" | grep -qE '(^|[;&|[:space:]])DRY_RUN_BYPASS=1\b' || [ "${DRY_RUN_BYPASS:-}" = "1" ]; then
  echo "[pre-train-gate] DRY_RUN_BYPASS=1 — allowing" >&2
  exit 0
fi

# Resolve script path relative to cwd
RESOLVED="${CWD_JSON:-$PWD}/$SCRIPT_PATH"
[ ! -f "$RESOLVED" ] && { RESOLVED="$SCRIPT_PATH"; }

bash "$ROOT/scripts/dry_run_gate.sh" check "$RESOLVED"
EC=$?
if [ "$EC" -ne 0 ]; then
  echo "[$(date -Iseconds)] pre-train-gate: BLOCKED — script=$RESOLVED" >> "$ROOT/memory/hook.log"
  exit 2
fi
exit 0
