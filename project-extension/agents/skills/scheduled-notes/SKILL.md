---
name: scheduled-notes
description: Persistent notes a scheduled/recurring agent reads as its FIRST action and writes as its LAST action, so a weekly/nightly autonomous run "knows where it left off." Use inside /loop or /schedule tasks that span multiple wake-ups. Pairs with hypothesis calibration and the experiment queue.
---

# /scheduled-notes — continuity across autonomous wake-ups

Ported pattern: Cognition's "Devin can now schedule Devins" — the weekly
task hands itself a note. Without this, a scheduled run starts cold every
time and can't build on its own prior conclusions.

## Convention

At the project root, maintain `SCHEDULED_NOTES.md`. It's a single
bounded-length markdown file that the scheduled agent edits in place.

Suggested structure:

```markdown
# SCHEDULED_NOTES.md

_Last updated: <ISO timestamp>_
_Current stage: creative_

## Open threads (pick these up next)

- Line 1: one-sentence thread + pointer to relevant journal node
- Line 2: ...

## Recent conclusions (compact)

- YYYY-MM-DD: outer-product init reduces warmup loss 0.02 (closed #42)
- ...

## Blockers / decisions needed

- (empty or a short note if human input would help)
```

Keep the whole file under ~2 KB. When it grows, compact into a line of
"conclusions" and drop the oldest threads.

## Agent protocol

First action of every scheduled run:

```bash
cat SCHEDULED_NOTES.md
```

Last action before exit:

```bash
# Update timestamp + current stage + open threads + recent conclusions
# Use apply_patch.py or Edit — either is fine.
```

The natural composition is:

1. Read `SCHEDULED_NOTES.md` → know where you left off.
2. `python3 .codex/scripts/queue.py next --json` → pop next queue item.
3. Do the work (launch via autopilot_loop.sh or ad-hoc).
4. Close journal node + calibration.
5. Update `SCHEDULED_NOTES.md` (what got done, what's next).
6. Exit.

## Failure mode: silent drift

If the agent stops writing the notes, you lose continuity. The
`check-scheduled-notes` helper (below) can flag when the file's
`Last updated:` timestamp drifts from reality.

```bash
# Optional: add to an hourly /loop. Portable mtime in seconds-since-epoch
# (works on GNU coreutils and BSD/macOS).
mtime() {
  if stat -c %Y "$1" 2>/dev/null; then :;
  else stat -f %m "$1" 2>/dev/null; fi
}
if [ "$(date +%s)" -gt $(( $(mtime SCHEDULED_NOTES.md) + 86400 )) ]; then
  .codex/scripts/notify.sh 2 "scheduled-notes stale" \
    "SCHEDULED_NOTES.md not updated in >24h; something is wrong"
fi
```

## Why not just use STATE.md?

`STATE.md` is Codex's always-on context (it's referenced by AGENTS.md).
`SCHEDULED_NOTES.md` is specifically for the agent-to-its-future-self
pattern. Keeping them separate keeps `STATE.md` clean for human reading
and lets scheduled runs churn through notes aggressively.
