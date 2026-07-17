#!/usr/bin/env bash
# PreToolUse(Bash) hook: if the command looks like a long-running training
# launch (runs a .py script via python/accelerate/torchrun/deepspeed), and
# the target script shows real training-framework signals, require a
# valid dry-run sentinel. Bypass: prefix with DRY_RUN_BYPASS=1.
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

# Shared launcher-word pattern: bare python (any version) or a
# distributed/GPU launcher. Extracted to a variable so the narrowing
# check below (ported from Rockielab/rockie-claude#24 bug 3) can tell
# which launcher matched without re-typing the alternation.
LAUNCHER_RE='python[0-9]*(\.[0-9]+)?|accelerate|torchrun|deepspeed'

# Fast path: must match a training-launch pattern. Broadened vs prior
# `python3?` — that missed `python3.11`, `python3.12`, etc. (security M-2).
echo "$CMD_NO_COMMENT" | grep -qE "($LAUNCHER_RE)[[:space:]].*\.py" || exit 0

# Extract the .py argument that belongs to the LAUNCHER's OWN invocation —
# not just any .py-looking token anywhere in the command. Bug (ported fix
# from Rockielab/rockie-claude, found via dogfooding): a compound command
# like
#   python3 real_train.py --help || find . -name "other_thing.py"
# used to have its LAST .py token win ("prefer the last .py token"), so an
# unrelated `find -name` pattern in a later clause could hijack extraction
# away from the script actually being launched.
#
# Fix: split the command on shell separators (; & |), then scan segments in
# order; the first segment that invokes a launcher yields the first
# .py-looking token AFTER the launcher token within that same segment. This
# also handles "torchrun --nproc-per-node 8 src/train.py --arg X" layouts,
# where the script isn't the token immediately after the launcher.
SCRIPT_PATH=""
while IFS= read -r seg; do
  echo "$seg" | grep -qE "$LAUNCHER_RE" || continue
  AFTER=$(echo "$seg" | sed -E "s/.*($LAUNCHER_RE)[[:space:]]*//")
  TOK=$(printf '%s' "$AFTER" | grep -oE "\"[^\"]*\\.py\"|'[^']*\\.py'|[^[:space:]]+\\.py" | head -1)
  if [ -n "$TOK" ]; then
    SCRIPT_PATH="$TOK"
    break
  fi
done < <(printf '%s\n' "$CMD_NO_COMMENT" | tr ';&|' '\n')

# Strip surrounding quote characters — the token may be `"train.py"` or
# 'train.py' if the launcher's argument was quoted in the shell.
SCRIPT_PATH="${SCRIPT_PATH%\"}"; SCRIPT_PATH="${SCRIPT_PATH#\"}"
SCRIPT_PATH="${SCRIPT_PATH%\'}"; SCRIPT_PATH="${SCRIPT_PATH#\'}"

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

# If neither resolution attempt points at a real file, extraction did not
# land on an actual script — a nonexistent path cannot be a training run
# being launched from this CWD. Fail OPEN narrowly for THIS reason only
# (stderr-noted, so it's visible but not alarming); a real script that
# exists but lacks a dry-run sentinel is still blocked below. This closes
# the failure mode where a malformed/mis-extracted token used to reach
# dry_run_gate.sh's "no such script: <path>" error, which reads as a hard
# block rather than "extraction produced nothing usable".
if [ ! -f "$RESOLVED" ]; then
  echo "[pre-train-gate] extracted target '$SCRIPT_PATH' is not a file on disk — not a training launch, allowing" >&2
  exit 0
fi

# Harness-internal utility scripts must never trip this gate — same
# rationale as the audit.py exemption below (ported from
# Rockielab/rockie-claude#24 bug 3), extended to the harness's own
# scripts/ dir (calibration.py, journal.py, queue.py, budget.py, etc. in
# the installed `.codex/scripts/` layout). $ROOT is derived from this
# hook's own installed location, not from user input, so this can't be
# spoofed by an attacker-named file placed elsewhere in the repo.
RESOLVED_DIR=$(cd "$(dirname "$RESOLVED")" 2>/dev/null && pwd -P)
if [ "$RESOLVED_DIR" = "$ROOT/scripts" ]; then
  exit 0
fi

# Narrow the matcher to actual training/eval entry points (ported from
# Rockielab/rockie-claude#24 bug 3). The prior matcher fired on ANY
# `python3 <file>.py`, including the harness's own lint/utility scripts
# (e.g. skills/clean/audit.py) — demanding a "forward+backward+grad
# check" dry run for a linter, which trains users to reflexively
# register sentinels and defeats the gate.
#
# Heuristic (fail-closed on ambiguity — a false BLOCK is a papercut, a
# false PASS burns real GPU money):
#   - accelerate/torchrun/deepspeed are ALWAYS enforced. No legitimate
#     utility script needs a distributed/multi-GPU launcher, so there is
#     no ambiguity to resolve in that case.
#   - A bare `python`/`pythonX.Y` invocation is exempted ONLY if the
#     target script is readable AND contains none of the standard
#     training-framework signals (torch/jax/tensorflow/transformers/
#     pytorch_lightning/deepspeed/accelerate imports, or a
#     backward()/optimizer.step()/Trainer/TrainingArguments call).
#     Unreadable, unresolved, or any doubt falls through to the existing
#     sentinel check (blocked unless already registered) — the default
#     stays fail-closed.
#
# Known blind spot: a bare-python script with no training-framework
# import that itself shells out to (or dynamically execs/imports) real
# training code — e.g. `os.system("torchrun real_train.py")` — is
# exempted here, because ITS OWN source has no training signal; the
# nested invocation never reaches this hook as a separate Bash command.
# Banning subprocess/os.system in exempted scripts would close that gap
# but reintroduces false blocks on ordinary CLI tools that shell out for
# unrelated reasons; flagging for follow-up rather than guessing.
LAUNCHER=$(echo "$CMD_NO_COMMENT" | grep -oE "$LAUNCHER_RE" | head -1)
if [ "$LAUNCHER" != "accelerate" ] && [ "$LAUNCHER" != "torchrun" ] && [ "$LAUNCHER" != "deepspeed" ]; then
  TRAIN_SIGNAL_RE='(^|[^A-Za-z0-9_])(import[[:space:]]+torch|from[[:space:]]+torch|import[[:space:]]+jax|from[[:space:]]+jax|import[[:space:]]+tensorflow|from[[:space:]]+tensorflow|import[[:space:]]+transformers|from[[:space:]]+transformers|import[[:space:]]+pytorch_lightning|import[[:space:]]+deepspeed|import[[:space:]]+accelerate|\.backward\(|optimizer\.step\(|loss\.backward|TrainingArguments|GradScaler|torch\.cuda|DistributedDataParallel)'
  if [ -f "$RESOLVED" ] && ! grep -qE "$TRAIN_SIGNAL_RE" "$RESOLVED" 2>/dev/null; then
    exit 0
  fi
fi

bash "$ROOT/scripts/dry_run_gate.sh" check "$RESOLVED"
EC=$?
if [ "$EC" -ne 0 ]; then
  echo "[$(date -Iseconds)] pre-train-gate: BLOCKED — script=$RESOLVED" >> "$ROOT/memory/hook.log"
  exit 2
fi
exit 0
