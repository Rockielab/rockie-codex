#!/usr/bin/env bash
# Stop hook: scan the latest assistant turn for [DEAD-END] blocks and
# insert them into workflow.db's dead_ends table.
#
# Mirrors learn-capture.sh — same transcript-walking, same dedupe pattern.
#
# [DEAD-END] format:
#   [DEAD-END] <direction-slug>: <reason>
#   Evidence: <path to EXPERIMENT_LOG entry, run dir, or paper citation>
#
# Fail-open: any error exits 0 so a broken hook never blocks the session.
set +e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="$ROOT/memory/workflow.db"
LOG="$ROOT/memory/hook.log"
SQLITE=/usr/bin/sqlite3

bash "$ROOT/scripts/rotate_hook_log.sh" 2>/dev/null
echo "[$(date -Iseconds)] deadend-capture: fired" >> "$LOG"

INPUT=$(cat)
TRANSCRIPT=$(echo "$INPUT" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("transcript_path",""))' 2>/dev/null)
[ -z "$TRANSCRIPT" ] && exit 0
[ ! -f "$TRANSCRIPT" ] && exit 0

PROJECT=$(basename "$(dirname "$ROOT")")

python3 - "$TRANSCRIPT" "$DB" "$PROJECT" "$SQLITE" "$LOG" <<'PYEOF'
import json, re, sys, pathlib, datetime

transcript_path, db, project, sqlite_bin, log_path = sys.argv[1:6]

def log(msg):
    with open(log_path, 'a') as f:
        f.write(f"[{datetime.datetime.now().isoformat()}] deadend-capture: {msg}\n")

try:
    lines = pathlib.Path(transcript_path).read_text().splitlines()
    # Walk back to the last user-text turn; collect assistant text.
    last_turn_text = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        etype = entry.get('type')
        if etype == 'user':
            content = entry.get('message', {}).get('content', [])
            if isinstance(content, str):
                break
            has_text = any(
                isinstance(b, dict) and b.get('type') == 'text'
                for b in (content or [])
            )
            if has_text:
                break
            continue
        if etype == 'assistant':
            content = entry.get('message', {}).get('content', [])
            for block in (content or []):
                if isinstance(block, dict) and block.get('type') == 'text':
                    last_turn_text.insert(0, block.get('text', ''))
    text = '\n\n'.join(last_turn_text)
    if not text:
        sys.exit(0)

    # [DEAD-END] <direction>: <reason>   [optional]\nEvidence: <path>
    pattern = re.compile(
        r'\[DEAD-?END\]\s*([\w][\w\s\-/\.]*?)\s*:\s*(.+?)'
        r'(?:\n\s*Evidence:\s*(.+?))?'
        r'(?=\n\s*\[DEAD-?END\]|\n\s*\[LEARN\]|\n\s*\n|\Z)',
        re.DOTALL | re.IGNORECASE,
    )
    matches = pattern.findall(text)
    if not matches:
        sys.exit(0)

    # Parameterized insert via sqlite3 bindings — avoids any SQL injection
    # from assistant-generated text (same reasoning as learn-capture.sh).
    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA trusted_schema=1")
    inserted, duplicates = 0, 0
    for direction, reason, evidence in matches:
        direction = direction.strip()
        reason = reason.strip().split('\n')[0].strip()
        evidence = (evidence or '').strip() or None
        if not direction or not reason:
            continue
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO dead_ends "
                "(project, direction, reason, evidence_path, source) "
                "VALUES (?, ?, ?, ?, 'codex')",
                (project, direction, reason, evidence),
            )
            if cur.rowcount == 1:
                inserted += 1
                log(f"captured: [{direction}] {reason[:80]}")
            else:
                duplicates += 1
        except sqlite3.Error as e:
            log(f"insert failed: {e}")
    conn.commit()
    conn.close()

    if inserted:
        print(f"[deadend-capture] {inserted} dead-end(s) captured"
              + (f" ({duplicates} duplicate)" if duplicates else ""),
              file=sys.stderr)

except Exception as e:
    log(f"error: {type(e).__name__}: {e}")

sys.exit(0)
PYEOF
exit 0
