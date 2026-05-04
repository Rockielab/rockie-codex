#!/usr/bin/env bash
# UserPromptSubmit hook: scan the most recent tool_use / tool_result
# history for loop patterns (OpenHands-style) and emit a prompt-context nudge
# if the agent looks stuck.
#
# Four detectors (condensation-loop dropped — OpenHands-specific):
#   1. repeat-tool-args: same tool + same args, N≥4 in window
#   2. repeat-error:     same tool + same error text, N≥4 in window
#   3. monologue:        N≥4 consecutive assistant turns with no tool_use
#   4. alternating:      A→B→A→B alternating pattern for ≥3 cycles
#
# Fail-open: errors exit 0; hook never blocks the session.
set +e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="$ROOT/memory/workflow.db"
LOG="$ROOT/memory/hook.log"
SQLITE=/usr/bin/sqlite3

bash "$ROOT/scripts/rotate_hook_log.sh" 2>/dev/null
echo "[$(date -Iseconds)] stuck-detector: fired" >> "$LOG"

INPUT=$(cat)
TRANSCRIPT=$(echo "$INPUT" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("transcript_path",""))' 2>/dev/null)
[ -z "$TRANSCRIPT" ] && exit 0
[ ! -f "$TRANSCRIPT" ] && exit 0

PROJECT=$(basename "$(dirname "$ROOT")")

python3 - "$TRANSCRIPT" "$DB" "$PROJECT" "$SQLITE" "$LOG" <<'PYEOF'
import json, sys, pathlib, subprocess, datetime, hashlib
from collections import Counter, deque

transcript_path, db, project, sqlite_bin, log_path = sys.argv[1:6]
WINDOW = 30            # look at the last 30 tool-use/assistant events
REPEAT_THRESHOLD = 4   # same action/error ≥4 times = stuck
MONOLOGUE_THRESHOLD = 4
ALTERNATE_THRESHOLD = 3  # A→B→A→B→A→B = 3 cycles

def log(msg):
    with open(log_path, 'a') as f:
        f.write(f"[{datetime.datetime.now().isoformat()}] stuck-detector: {msg}\n")

def canon_tool_use(block):
    """Canonical fingerprint of a tool call: (name, hash(inputs))."""
    name = block.get("name", "")
    inp = block.get("input", {}) or {}
    # Normalize: stable JSON, truncate long strings so near-dup args still match
    try:
        s = json.dumps(inp, sort_keys=True, default=str)
    except Exception:
        s = repr(inp)
    if len(s) > 2000:
        s = s[:2000]
    return (name, hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()[:16])

def error_signature(result_block):
    """Hash of tool_result error text, or None if not an error."""
    content = result_block.get("content", "")
    if isinstance(content, list):
        content = " ".join(
            (b.get("text", "") if isinstance(b, dict) else str(b))
            for b in content
        )
    s = str(content)
    low = s.lower()
    is_err = (
        result_block.get("is_error") is True
        or "error" in low[:200] or "exception" in low[:200]
        or "traceback" in low[:200]
    )
    if not is_err:
        return None
    # First 400 chars as the signature (truncate to catch same-kind-different-arg errors too)
    return hashlib.sha1(s[:400].encode("utf-8","replace")).hexdigest()[:16]

try:
    lines = pathlib.Path(transcript_path).read_text().splitlines()
    # Parse events in order, collect: (role, tool_uses:[canon], tool_results:[sig|None], had_text:bool)
    # We walk oldest→newest and keep only the tail.
    events = []  # list of dicts per assistant/user entry
    for line in lines:
        line = line.strip()
        if not line: continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        etype = entry.get("type")
        if etype not in ("assistant", "user"):
            continue
        content = entry.get("message", {}).get("content", [])
        if isinstance(content, str):
            events.append({"role": etype, "tool_uses": [], "tool_results": [], "had_text": bool(content.strip())})
            continue
        tu, tr, had_text = [], [], False
        for b in (content or []):
            if not isinstance(b, dict): continue
            t = b.get("type")
            if t == "text" and b.get("text","").strip():
                had_text = True
            elif t == "tool_use":
                tu.append(canon_tool_use(b))
            elif t == "tool_result":
                tr.append(error_signature(b))
        events.append({"role": etype, "tool_uses": tu, "tool_results": tr, "had_text": had_text})

    if len(events) < 4:
        sys.exit(0)

    # Keep only the last WINDOW events
    events = events[-WINDOW:]

    # Flatten recent assistant tool_uses and their paired tool_results.
    # Pair each tool_use with the NEXT tool_result in stream order.
    flat_actions = []  # list of (tool_canon, error_sig_or_None)
    pending = deque()
    for ev in events:
        for tu in ev["tool_uses"]:
            pending.append(tu)
            flat_actions.append([tu, None])
        for tr in ev["tool_results"]:
            # attach to most recent un-paired action
            for pair in reversed(flat_actions):
                if pair[1] is None and pair[0] is not None:
                    pair[1] = tr
                    break
    # Keep last 20 actions for detectors
    recent = flat_actions[-20:]

    messages = []   # stderr nudges to emit

    # ── Detector 1: repeat-tool-args ─────────────────────────────────────
    if recent:
        tc = Counter(a[0] for a in recent)
        for (tool, arghash), cnt in tc.most_common(3):
            if cnt >= REPEAT_THRESHOLD:
                messages.append(
                    f"repeat-tool-args: tool '{tool}' with identical args "
                    f"called {cnt}× in last {len(recent)} actions. "
                    f"Change approach or inspect why the call isn't moving state forward."
                )
                break

    # ── Detector 2: repeat-error ────────────────────────────────────────
    err_pairs = [(a[0][0], a[1]) for a in recent if a[1]]
    if err_pairs:
        ec = Counter(err_pairs)
        for (tool, esig), cnt in ec.most_common(3):
            if cnt >= REPEAT_THRESHOLD:
                messages.append(
                    f"repeat-error: tool '{tool}' errored with the same signature "
                    f"{cnt}× in the window. Diagnose root cause instead of retrying."
                )
                break

    # ── Detector 3: monologue ───────────────────────────────────────────
    # Count trailing assistant turns with had_text=True and tool_uses empty.
    mono = 0
    for ev in reversed(events):
        if ev["role"] != "assistant":
            break
        if ev["tool_uses"]:
            break
        if ev["had_text"]:
            mono += 1
        else:
            break
    if mono >= MONOLOGUE_THRESHOLD:
        messages.append(
            f"monologue: {mono} consecutive assistant turns with text but no tool use. "
            f"If you're stuck planning, take a concrete action or ask the user."
        )

    # ── Detector 4: alternating cycle of period P ∈ {2,3,4} ────────────
    # Catches ABAB, ABCABC, ABCDABCD patterns over the last K actions.
    # A pattern of period P needs K >= 2*P actions to confirm one full
    # repeat. We try P=2,3,4 and emit the first one that fits.
    detected_cycle = None
    for P in (2, 3, 4):
        K = P * 2
        if len(recent) < K:
            continue
        tail = [a[0] for a in recent[-K:]]
        # Require the period-P pattern to be genuine (not all identical,
        # since repeat-tool-args already handles that).
        if len(set(tail)) < 2:
            continue
        if all(tail[i] == tail[i % P] for i in range(K)):
            detected_cycle = (P, tail[:P])
            break
    if detected_cycle:
        P, seq = detected_cycle
        pretty = " → ".join(f"'{name}'" for name, _ in seq)
        messages.append(
            f"alternating: last {P*2} actions cycle with period {P}: {pretty}. "
            f"Break the cycle."
        )

    if not messages:
        sys.exit(0)

    header = "[stuck-detector] Possible loop(s) detected in recent activity:"
    print(header)
    for m in messages:
        print(f"  ⚠ {m}")
        log(m)

    # Also capture as a [LEARN]-adjacent side-signal (not in learnings table —
    # this is per-event noise, not a durable rule). We just log it.
except Exception as e:
    log(f"error: {type(e).__name__}: {e}")

sys.exit(0)
PYEOF
exit 0
