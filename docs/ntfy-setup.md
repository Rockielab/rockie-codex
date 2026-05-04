# ntfy setup (optional)

rockie uses [ntfy.sh](https://ntfy.sh) for push notifications — e.g.
"experiment crashed," "draft ready for review," "autopilot blocked
and needs a decision." Free, no account needed, end-to-end encrypted
if you run your own server.

Without ntfy, `notify.sh` silently no-ops. Nothing breaks.

## One-time phone setup

1. **Install the ntfy app** — F-Droid build preferred (no Firebase
   dependency; more reliable background socket):
   - F-Droid: https://f-droid.org/en/packages/io.heckel.ntfy/
   - or Play Store: search `ntfy`

2. **Pick a topic.** Any string. Make it long and random so nobody
   else can subscribe. Example: `myname-autopilot-<16 hex chars>`.
   Use `openssl rand -hex 8` to generate.

3. **Subscribe in the app:** + → Subscribe to topic → enter your
   topic name → server `ntfy.sh` (default) → save.

4. **Whitelist from Do Not Disturb.** Settings → Notifications → DND
   → Apps → add ntfy. Without this, tier-1 critical alerts get silenced
   at night.

5. **Whitelist from battery optimization.** Settings → Battery →
   Battery optimization → ntfy → Don't optimize. Otherwise Android
   kills the background socket after ~30 min.

## Mac / shell setup

Add to your shell profile:

```bash
export NTFY_TOPIC="myname-autopilot-xxxxxxxxxxxxxxxx"
# optional:
# export NTFY_SERVER="https://ntfy.sh"  # default
```

Test:

```bash
.codex/scripts/notify.sh 2 "rockie test" "Hello from my laptop."
```

Your phone should chime within ~2 seconds.

## Bidirectional (phone → Mac)

Reply from the ntfy app: tap topic → send icon → type → send.

Then on the Mac:

```bash
.codex/scripts/ntfy_poll_responses.sh
```

That polls the topic since the last cursor and emits any user messages
as JSON (one per line). The first call primes the cursor and returns
nothing; subsequent calls return only new messages.

Autopilot's own messages are tagged `robot_face` and filtered out by
the poll script, so it never re-reads its own posts.

## Tiers

| Tier | Priority | Use |
|---|---|---|
| 1 | `max` (wakes through DND if whitelisted) | Unrecoverable halt, novel result |
| 2 | `high` (normal push) | Ready-for-review (draft, proposed experiments) |
| 3 | `low` (silent, tray only) | Informational (run completed, queue refilled) |

## Caveats

- ntfy free public topic has a **12-hour message cache.** If phone is
  offline >12h, missed messages drop. The poll script tolerates gaps —
  just advances the cursor past them.
- `notify.sh` is silent on ntfy outage — `notifications.ntfy_id` is
  `NULL` if the request failed. Acceptable for fire-and-forget, but
  callers that care should check the column.
