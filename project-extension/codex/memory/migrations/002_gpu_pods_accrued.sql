-- Migration 002: track actual accrued cost per pod so budget enforcement
-- can be against reality, not create-time estimates.
--
-- accrued_dollars is SET (not added) by gpu.py reconcile on each call.
-- last_reconciled_at records when it was last refreshed; callers can use
-- this for staleness checks.

ALTER TABLE gpu_pods ADD COLUMN accrued_dollars REAL NOT NULL DEFAULT 0;
ALTER TABLE gpu_pods ADD COLUMN last_reconciled_at TEXT;
