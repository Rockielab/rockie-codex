-- Migration 004: preemption_events log.
--
-- Written by gpu.py's poll_once loop (and the autopilot monitor) when a
-- pod transitions from RUNNING to PREEMPTED/EXITED before its expected
-- runtime. Read by gpu.py's create-router as a cooldown filter:
-- (provider, gpu_type) pairs with a recent preemption are skipped or
-- pushed to the back of the rank for an exponential-backoff window
-- (10–60 min) so we don't immediately re-bid into the same hot market.
--
-- Lightweight log; no foreign keys to gpu_pods so we can record events
-- for pods we don't own (e.g. observed via reconcile, not via create).

CREATE TABLE IF NOT EXISTS preemption_events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  pod_id      TEXT,                                          -- nullable: some adapters may have lost it
  provider    TEXT NOT NULL,                                 -- opaque adapter slug
  gpu_type    TEXT NOT NULL,
  ts          TEXT NOT NULL DEFAULT (datetime('now')),
  reason      TEXT                                           -- e.g. "actual=exited intended=running"
);

CREATE INDEX IF NOT EXISTS idx_preemption_events_lookup
  ON preemption_events(provider, gpu_type, ts);
