-- Learnings DB — adapted from rohitg00/pro-workflow
-- Two tables + FTS5. Queryable via recency and full-text search.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Schema version is tracked via PRAGMA user_version, NOT set here —
-- init_db.sh owns the version so re-applying schema.sql on an already-
-- migrated DB doesn't roll the version back. If user_version is 0 after
-- schema.sql runs, init_db sets it to 1 (this file is baseline v1).

CREATE TABLE IF NOT EXISTS learnings (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  project       TEXT,
  category      TEXT NOT NULL,
  rule          TEXT NOT NULL,
  mistake       TEXT,
  correction    TEXT,
  source        TEXT,                -- 'codex', 'seed', 'manual'
  times_applied INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_learnings_category  ON learnings(category);
CREATE INDEX IF NOT EXISTS idx_learnings_project   ON learnings(project);
CREATE INDEX IF NOT EXISTS idx_learnings_created   ON learnings(created_at);

-- UNIQUE on (project, category, rule) — atomic dedupe via INSERT OR IGNORE.
-- COALESCE(project, '') so rows with NULL project still participate.
CREATE UNIQUE INDEX IF NOT EXISTS idx_learnings_unique
  ON learnings(COALESCE(project,''), category, rule);

CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(
  category, rule, mistake, correction,
  content=learnings, content_rowid=id,
  tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS learnings_ai AFTER INSERT ON learnings BEGIN
  INSERT INTO learnings_fts(rowid, category, rule, mistake, correction)
  VALUES (new.id, new.category, new.rule, new.mistake, new.correction);
END;

CREATE TRIGGER IF NOT EXISTS learnings_ad AFTER DELETE ON learnings BEGIN
  INSERT INTO learnings_fts(learnings_fts, rowid, category, rule, mistake, correction)
  VALUES ('delete', old.id, old.category, old.rule, old.mistake, old.correction);
END;

CREATE TRIGGER IF NOT EXISTS learnings_au AFTER UPDATE ON learnings BEGIN
  INSERT INTO learnings_fts(learnings_fts, rowid, category, rule, mistake, correction)
  VALUES ('delete', old.id, old.category, old.rule, old.mistake, old.correction);
  INSERT INTO learnings_fts(rowid, category, rule, mistake, correction)
  VALUES (new.id, new.category, new.rule, new.mistake, new.correction);
END;

CREATE TABLE IF NOT EXISTS sessions (
  id                 TEXT PRIMARY KEY,
  project            TEXT,
  started_at         TEXT NOT NULL DEFAULT (datetime('now')),
  ended_at           TEXT,
  edit_count         INTEGER NOT NULL DEFAULT 0,
  corrections_count  INTEGER NOT NULL DEFAULT 0,
  prompts_count      INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project, started_at);

-- Notifications sent via notify.sh — tracked so autopilot can reference by id
-- when matching responses and avoid re-notifying about the same thing.
CREATE TABLE IF NOT EXISTS notifications (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  sent_at     TEXT NOT NULL DEFAULT (datetime('now')),
  tier        INTEGER NOT NULL,      -- 1=critical, 2=review, 3=info
  title       TEXT,
  body        TEXT NOT NULL,
  topic       TEXT,
  ntfy_id     TEXT,                  -- message id returned by ntfy
  correlation TEXT,                  -- e.g. 'blog-draft-round9', 'queue-refill'
  acked_at    TEXT,
  response    TEXT                   -- user's reply text if any
);

CREATE INDEX IF NOT EXISTS idx_notif_sent ON notifications(sent_at);
CREATE INDEX IF NOT EXISTS idx_notif_corr ON notifications(correlation);

-- ─── Dead-end registry (Port A1, see docs/PORTS.md) ───────────────────────
-- Captures research directions that have been killed so brainstorm agents
-- don't re-propose them. Populated by [DEAD-END] blocks in assistant output
-- (parsed by hooks/deadend-capture.sh) and auto-injected into prompts by
-- hooks/load-relevant-deadends.sh. Pipeline parallels the learnings table.
CREATE TABLE IF NOT EXISTS dead_ends (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  killed_at      TEXT NOT NULL DEFAULT (datetime('now')),
  project        TEXT,
  direction      TEXT NOT NULL,         -- short name ('matrix-only at 288K params')
  reason         TEXT NOT NULL,         -- why it died, as specific as possible
  evidence_path  TEXT,                  -- path to EXPERIMENT_LOG entry, run dir, or paper
  source         TEXT                   -- 'codex', 'seed', 'manual'
);

CREATE INDEX IF NOT EXISTS idx_deadends_project ON dead_ends(project);
CREATE INDEX IF NOT EXISTS idx_deadends_killed  ON dead_ends(killed_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_deadends_unique
  ON dead_ends(COALESCE(project,''), direction);

CREATE VIRTUAL TABLE IF NOT EXISTS dead_ends_fts USING fts5(
  direction, reason, evidence_path,
  content=dead_ends, content_rowid=id,
  tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS dead_ends_ai AFTER INSERT ON dead_ends BEGIN
  INSERT INTO dead_ends_fts(rowid, direction, reason, evidence_path)
  VALUES (new.id, new.direction, new.reason, new.evidence_path);
END;

CREATE TRIGGER IF NOT EXISTS dead_ends_ad AFTER DELETE ON dead_ends BEGIN
  INSERT INTO dead_ends_fts(dead_ends_fts, rowid, direction, reason, evidence_path)
  VALUES ('delete', old.id, old.direction, old.reason, old.evidence_path);
END;

CREATE TRIGGER IF NOT EXISTS dead_ends_au AFTER UPDATE ON dead_ends BEGIN
  INSERT INTO dead_ends_fts(dead_ends_fts, rowid, direction, reason, evidence_path)
  VALUES ('delete', old.id, old.direction, old.reason, old.evidence_path);
  INSERT INTO dead_ends_fts(rowid, direction, reason, evidence_path)
  VALUES (new.id, new.direction, new.reason, new.evidence_path);
END;

-- ─── Hypothesis calibration (Port A2, see docs/PORTS.md) ──────────────────
-- Every experiment logs a predicted metric delta; after the run, the actual
-- delta is diffed. A rolling calibration score surfaces whether the agent's
-- priors are getting better or drifting.
--
-- Populated by the pre-experiment checklist and closed out by the post-run
-- review hook. A calibration report is queryable via scripts/calibration.py.
CREATE TABLE IF NOT EXISTS hypothesis_calibration (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  project         TEXT,
  run_id          TEXT NOT NULL,         -- experiment-runs/<dir> basename
  hypothesis      TEXT NOT NULL,         -- one-sentence statement
  metric_name     TEXT NOT NULL,         -- 'val_loss', 'bpb', 'f1', ...
  baseline_value  REAL,                  -- optional starting metric
  predicted_delta REAL NOT NULL,         -- signed; interpret per lower_is_better
  lower_is_better INTEGER NOT NULL DEFAULT 1,
  actual_delta    REAL,                  -- NULL until run completes
  closed_at       TEXT,                  -- timestamp when actual_delta was filled
  notes           TEXT                   -- optional free-form narrative
);

CREATE INDEX IF NOT EXISTS idx_calib_project ON hypothesis_calibration(project);
CREATE INDEX IF NOT EXISTS idx_calib_run     ON hypothesis_calibration(run_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_calib_unique
  ON hypothesis_calibration(COALESCE(project,''), run_id, hypothesis);

-- ─── Experiments journal tree (Port B1, see docs/PORTS.md) ───────────────
-- AIDE-style node tree. Every experiment is a node with an optional parent,
-- a stage (draft | debug | improve | baseline-tune | creative | ablation),
-- a status (pending | running | done | killed), and after the run a
-- metric + analysis + is_buggy + failure_class (C4).
--
-- The EXPERIMENT_LOG.md doc becomes a rendered view of this table.
-- experiment-runs/<run_id>/ still archives the exact script; the tree
-- points at it via run_id.
CREATE TABLE IF NOT EXISTS experiments (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  closed_at       TEXT,
  project         TEXT,
  run_id          TEXT,
  parent_id       INTEGER REFERENCES experiments(id),
  stage           TEXT NOT NULL DEFAULT 'draft',
  status          TEXT NOT NULL DEFAULT 'pending',
  hypothesis      TEXT,
  code_path       TEXT,
  is_buggy        INTEGER,                     -- NULL=unset, 1=bug, 0=clean
  failure_class   TEXT,                        -- bug | bad-hyperparam | bad-hypothesis
  metric_name     TEXT,
  metric_value    REAL,
  lower_is_better INTEGER NOT NULL DEFAULT 1,
  debug_depth     INTEGER NOT NULL DEFAULT 0,  -- distance from a non-debug ancestor
  analysis        TEXT
);

CREATE INDEX IF NOT EXISTS idx_experiments_parent  ON experiments(parent_id);
CREATE INDEX IF NOT EXISTS idx_experiments_project ON experiments(project);
CREATE INDEX IF NOT EXISTS idx_experiments_status  ON experiments(status);
CREATE INDEX IF NOT EXISTS idx_experiments_stage   ON experiments(stage);
CREATE INDEX IF NOT EXISTS idx_experiments_run     ON experiments(run_id);
-- Speeds up good-leaf / best-so-far queries
CREATE INDEX IF NOT EXISTS idx_experiments_good    ON experiments(project, metric_name, is_buggy, metric_value);

CREATE VIRTUAL TABLE IF NOT EXISTS experiments_fts USING fts5(
  hypothesis, analysis,
  content=experiments, content_rowid=id,
  tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS experiments_ai AFTER INSERT ON experiments BEGIN
  INSERT INTO experiments_fts(rowid, hypothesis, analysis)
  VALUES (new.id, coalesce(new.hypothesis,''), coalesce(new.analysis,''));
END;
CREATE TRIGGER IF NOT EXISTS experiments_ad AFTER DELETE ON experiments BEGIN
  INSERT INTO experiments_fts(experiments_fts, rowid, hypothesis, analysis)
  VALUES ('delete', old.id, coalesce(old.hypothesis,''), coalesce(old.analysis,''));
END;
CREATE TRIGGER IF NOT EXISTS experiments_au AFTER UPDATE ON experiments BEGIN
  INSERT INTO experiments_fts(experiments_fts, rowid, hypothesis, analysis)
  VALUES ('delete', old.id, coalesce(old.hypothesis,''), coalesce(old.analysis,''));
  INSERT INTO experiments_fts(rowid, hypothesis, analysis)
  VALUES (new.id, coalesce(new.hypothesis,''), coalesce(new.analysis,''));
END;

-- Best-so-far node per (project, metric_name). Direction respects lower_is_better.
CREATE VIEW IF NOT EXISTS best_so_far AS
  SELECT e.*
  FROM experiments e
  JOIN (
    SELECT project, metric_name,
           MIN(CASE WHEN lower_is_better=1 THEN metric_value END) AS lo,
           MAX(CASE WHEN lower_is_better=0 THEN metric_value END) AS hi
    FROM experiments
    WHERE is_buggy = 0 AND status = 'done' AND metric_value IS NOT NULL
    GROUP BY project, metric_name
  ) g
  ON e.project = g.project AND e.metric_name = g.metric_name
  AND e.is_buggy = 0 AND e.status = 'done'
  AND ((e.lower_is_better=1 AND e.metric_value = g.lo)
    OR (e.lower_is_better=0 AND e.metric_value = g.hi));

-- Open leaves ready for the search-policy to operate on.
CREATE VIEW IF NOT EXISTS open_leaves AS
  SELECT e.*
  FROM experiments e
  WHERE e.status IN ('pending','running')
    AND NOT EXISTS (SELECT 1 FROM experiments c WHERE c.parent_id = e.id);

-- ─── Budget tracking (Port B4, see docs/PORTS.md) ────────────────────────
-- Cumulative usage counters. The budget-gate hook reads these and aborts
-- the session when any ceiling is crossed. Per-session, per-project, and
-- lifetime rows all coexist; the gate reads by key.
CREATE TABLE IF NOT EXISTS budget_usage (
  key          TEXT PRIMARY KEY,       -- 'session:<id>:tokens', 'project:<name>:wallclock_s', ...
  project      TEXT,
  session_id   TEXT,
  metric       TEXT NOT NULL,          -- 'tokens' | 'wallclock_s' | 'dollars' | 'tool_calls'
  value        REAL NOT NULL DEFAULT 0,
  updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─── Experiment queue (continuous-operation core) ────────────────────────
-- Forward-looking queue of experiments the agent should run next.
-- Populated by /queue-refill (brainstorm agent reads recent [LEARN],
-- recent dead-ends, best-so-far, and produces 5 well-scoped items).
-- Consumed by /queue-pop when a GPU is free (zero-cost monitor calls it).
CREATE TABLE IF NOT EXISTS experiment_queue (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at            TEXT NOT NULL DEFAULT (datetime('now')),
  project               TEXT,
  priority              INTEGER NOT NULL DEFAULT 3,        -- 1=urgent, 5=nice-to-have
  hypothesis            TEXT NOT NULL,
  metric_name           TEXT,
  predicted_delta       REAL,
  lower_is_better       INTEGER NOT NULL DEFAULT 1,
  estimated_minutes     INTEGER,                           -- GPU wall time guess
  suggested_stage       TEXT,                              -- journal stage this would belong to
  parent_experiment_id  INTEGER REFERENCES experiments(id),
  status                TEXT NOT NULL DEFAULT 'pending',   -- pending | claimed | done | dropped
  claimed_at            TEXT,
  claimed_by            TEXT,                              -- session id
  done_at               TEXT,
  dropped_reason        TEXT,
  notes                 TEXT
);

CREATE INDEX IF NOT EXISTS idx_queue_project_status ON experiment_queue(project, status);
CREATE INDEX IF NOT EXISTS idx_queue_priority      ON experiment_queue(status, priority);

-- ─── Best-so-far code pool (Port C3, see docs/PORTS.md) ───────────────────
-- AgentLab-style size-K pool. Populated on admission by journal CLI;
-- displaces worst-scoring entry when a new node beats it.
CREATE TABLE IF NOT EXISTS code_pool (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  admitted_at     TEXT NOT NULL DEFAULT (datetime('now')),
  project         TEXT,
  experiment_id   INTEGER REFERENCES experiments(id),
  score           REAL NOT NULL,                 -- canonicalized (always higher=better)
  code_path       TEXT NOT NULL,
  reflection      TEXT                            -- LLM reflection on admission
);
CREATE INDEX IF NOT EXISTS idx_pool_project ON code_pool(project, score);

-- ─── gpu_pods — provider-provisioned compute, tracked for budget reconcile ─
-- Lifted from runpod.py:_db() (lazy-create) into the baseline so migrations
-- 002+003 (which ALTER this table) apply cleanly on fresh DBs. Without this,
-- init_db.sh aborts during migration 002 because gpu_pods doesn't exist
-- until something else creates it lazily — broken ordering.
CREATE TABLE IF NOT EXISTS gpu_pods (
  id           TEXT PRIMARY KEY,                  -- provider-given pod id
  provider     TEXT NOT NULL DEFAULT 'runpod',
  gpu_type     TEXT,
  gpu_count    INTEGER,
  bid_per_gpu  REAL,
  region       TEXT,
  status       TEXT,                              -- CREATED | RUNNING | STOPPED | EXITED | TERMINATED | PREEMPTED | GONE
  created_at   TEXT NOT NULL DEFAULT (datetime('now')),
  stopped_at   TEXT,
  ssh_endpoint TEXT,
  notes        TEXT
);

-- View: calibration error (absolute predicted−actual) and sign-correctness.
CREATE VIEW IF NOT EXISTS calibration_scorecard AS
SELECT
  id, project, run_id, created_at, closed_at,
  hypothesis, metric_name, predicted_delta, actual_delta,
  (actual_delta - predicted_delta) AS signed_error,
  abs(actual_delta - predicted_delta) AS abs_error,
  CASE
    WHEN actual_delta IS NULL THEN NULL
    WHEN (predicted_delta < 0 AND actual_delta < 0)
      OR (predicted_delta > 0 AND actual_delta > 0)
      OR (predicted_delta = 0 AND actual_delta = 0) THEN 1
    ELSE 0
  END AS sign_correct
FROM hypothesis_calibration;
