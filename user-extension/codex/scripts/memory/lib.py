"""Shared library for the Codex memory system.

Single SQLite DB at ~/.codex/memory/memory.db. Two logical tiers stored in
one table via the `project` column:
  project = <repo-name>  → repo-local memory
  project = NULL         → global (cross-repo) memory

Promotion from repo → global is empirical: when the same normalized rule
appears in 3+ distinct repos, the consolidator promotes it and marks the
per-repo copies as superseded_by the global row.

Dedup is automatic at insert time: normalized rule text (lowercase, collapse
whitespace, strip surrounding punctuation) matched against existing rows in
the same project. If found, hit_count++ instead of a new insert.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / ".codex" / "memory" / "memory.db"

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  project TEXT,                    -- NULL = global
  category TEXT NOT NULL,
  rule TEXT NOT NULL,
  rule_normalized TEXT NOT NULL,
  mistake TEXT,
  correction TEXT,
  origin_session TEXT,
  origin_repo_path TEXT,
  hit_count INTEGER DEFAULT 1,
  last_hit TEXT,
  superseded_by TEXT,
  status TEXT DEFAULT 'active'
);

CREATE INDEX IF NOT EXISTS idx_project_category ON memories(project, category);
CREATE INDEX IF NOT EXISTS idx_rule_normalized ON memories(rule_normalized, project);
CREATE INDEX IF NOT EXISTS idx_status ON memories(status);

-- Partial UNIQUE so concurrent inserts / repromotions can't duplicate
-- active memories. COALESCE normalizes NULL project to empty string so
-- the unique constraint fires on global-tier rows too.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_memory
  ON memories(rule_normalized, COALESCE(project, ''))
  WHERE status = 'active';

CREATE TABLE IF NOT EXISTS consolidation_log (
  ts TEXT NOT NULL,
  action TEXT NOT NULL,
  from_id TEXT,
  to_id TEXT,
  reason TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  project TEXT,
  started_at TEXT,
  ended_at TEXT,
  memories_captured INTEGER DEFAULT 0
);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    _ensure_schema_version(conn)
    return conn


def _ensure_schema_version(conn: sqlite3.Connection) -> None:
    cur = conn.execute("SELECT version FROM schema_version LIMIT 1")
    row = cur.fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
        )
        conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_rule(rule: str) -> str:
    """Lowercase, collapse whitespace, strip surrounding punctuation.

    Used for dedup: two memories with the same normalized rule in the same
    project are considered duplicates.
    """
    s = rule.strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = s.strip(" .,;:!?\"'`")
    return s


def project_from_path(repo_path: str | None) -> str | None:
    """Extract a project slug from a repo path, or None for global."""
    if not repo_path:
        return None
    name = Path(repo_path).name
    # Sanitize: allow only alnum, dash, underscore, dot
    name = re.sub(r"[^a-zA-Z0-9._-]", "-", name).strip("-")
    return name or None


def new_memory_id() -> str:
    return f"mem_{uuid.uuid4().hex[:12]}"


def insert_memory(
    conn: sqlite3.Connection,
    *,
    category: str,
    rule: str,
    mistake: str | None = None,
    correction: str | None = None,
    project: str | None = None,
    origin_session: str | None = None,
    origin_repo_path: str | None = None,
) -> tuple[str, str]:
    """Insert a memory with dedup.

    Returns (memory_id, action) where action is one of:
      'inserted' — new row created
      'dedup'    — existing row had hit_count++, no new insert
      'skipped'  — empty rule or other reject
    """
    rule = rule.strip()
    if not rule:
        return ("", "skipped")
    category = (category or "uncategorized").strip().lower().replace(" ", "-")
    normalized = normalize_rule(rule)
    ts = now_iso()

    # Atomic upsert — the uniq_active_memory partial index ensures two
    # concurrent inserts on the same (rule_normalized, project) can't
    # both create rows. On conflict, bump hit_count + last_hit on the
    # existing row. Fixes the SELECT-then-INSERT race and the
    # double-promotion case the self-audit caught.
    mid = new_memory_id()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """
            INSERT INTO memories (
              id, ts, project, category, rule, rule_normalized,
              mistake, correction, origin_session, origin_repo_path,
              hit_count, last_hit, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'active')
            ON CONFLICT(rule_normalized, COALESCE(project, ''))
              WHERE status = 'active'
              DO UPDATE SET
                hit_count = hit_count + 1,
                last_hit = excluded.last_hit
              RETURNING id, (hit_count > 1) AS was_dup
            """,
            (
                mid,
                ts,
                project,
                category,
                rule,
                normalized,
                mistake,
                correction,
                origin_session,
                origin_repo_path,
                ts,
            ),
        )
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise

    # Determine if it was a fresh insert or an upsert by re-querying
    row = conn.execute(
        """
        SELECT id, hit_count FROM memories
        WHERE rule_normalized = ? AND COALESCE(project, '') = COALESCE(?, '')
          AND status = 'active'
        """,
        (normalized, project),
    ).fetchone()
    if row is None:
        # Shouldn't happen — the upsert either inserted or updated
        return ("", "skipped")
    action = "inserted" if row["id"] == mid else "dedup"
    return (row["id"], action)


def log_consolidation(
    conn: sqlite3.Connection,
    *,
    action: str,
    from_id: str | None = None,
    to_id: str | None = None,
    reason: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO consolidation_log (ts, action, from_id, to_id, reason) VALUES (?, ?, ?, ?, ?)",
        (now_iso(), action, from_id, to_id, reason),
    )
    conn.commit()


def active_memories_for_project(
    conn: sqlite3.Connection, project: str | None, limit: int = 50
) -> list[sqlite3.Row]:
    """Return top-K active memories relevant to a project.

    Scope: repo-tier for THIS project + all global-tier.
    Ordering: hit_count DESC then last_hit DESC (hot + recent first).
    """
    cur = conn.execute(
        """
        SELECT * FROM memories
        WHERE status = 'active' AND (project IS NULL OR project = ?)
        ORDER BY hit_count DESC, last_hit DESC
        LIMIT ?
        """,
        (project, limit),
    )
    return cur.fetchall()


# ─── Auto-promotion to global tier ─────────────────────────────────────────
#
# Empirical rule: when the same normalized rule text appears as an ACTIVE
# memory in 3+ distinct repos, promote it to global. Mark the repo-tier
# copies as superseded_by the new global row.
#
# Called by the consolidator (periodic/scheduled), not on every insert.

PROMOTE_THRESHOLD = 3


def promote_cross_repo(conn: sqlite3.Connection) -> list[str]:
    """Find rules that span 3+ repos and promote to global. Returns new global IDs."""
    cur = conn.execute(
        """
        SELECT rule_normalized, COUNT(DISTINCT project) AS n_projects
        FROM memories
        WHERE status = 'active' AND project IS NOT NULL
        GROUP BY rule_normalized
        HAVING COUNT(DISTINCT project) >= ?
        """,
        (PROMOTE_THRESHOLD,),
    )
    promoted: list[str] = []
    for row in cur.fetchall():
        normalized = row["rule_normalized"]
        # Pick the earliest active row as the seed for content fidelity
        seed = conn.execute(
            """
            SELECT * FROM memories
            WHERE rule_normalized = ? AND status = 'active' AND project IS NOT NULL
            ORDER BY ts ASC
            LIMIT 1
            """,
            (normalized,),
        ).fetchone()
        if seed is None:
            continue
        new_id = new_memory_id()
        ts = now_iso()
        # Atomic upsert — if a global copy exists, bump its hit_count
        # instead of double-inserting. The partial UNIQUE index enforces
        # this at the DB layer too.
        try:
            conn.execute(
                """
                INSERT INTO memories (
                  id, ts, project, category, rule, rule_normalized,
                  mistake, correction, hit_count, last_hit, status
                ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, 'active')
                ON CONFLICT(rule_normalized, COALESCE(project, ''))
                  WHERE status = 'active'
                  DO UPDATE SET
                    hit_count = hit_count + excluded.hit_count,
                    last_hit = excluded.last_hit
                """,
                (
                    new_id,
                    ts,
                    seed["category"],
                    seed["rule"],
                    seed["rule_normalized"],
                    seed["mistake"],
                    seed["correction"],
                    row["n_projects"],
                    ts,
                ),
            )
        except sqlite3.IntegrityError:
            # Defensive: partial index race (shouldn't happen with BEGIN IMMEDIATE above)
            continue
        # If we didn't actually insert (conflict path took UPDATE), skip the supersede step
        # for this rule — another promotion pass already handled it.
        actual = conn.execute(
            "SELECT id FROM memories WHERE rule_normalized = ? AND project IS NULL AND status = 'active'",
            (normalized,),
        ).fetchone()
        if actual is None or actual["id"] != new_id:
            continue
        # Supersede the repo-tier copies
        conn.execute(
            """
            UPDATE memories
            SET status = 'superseded', superseded_by = ?
            WHERE rule_normalized = ? AND project IS NOT NULL AND status = 'active'
            """,
            (new_id, normalized),
        )
        log_consolidation(
            conn,
            action="promoted_to_global",
            to_id=new_id,
            reason=f"rule appeared in {row['n_projects']} projects",
        )
        promoted.append(new_id)
    conn.commit()
    return promoted
