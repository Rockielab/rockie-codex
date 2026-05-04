#!/usr/bin/env python3
"""Experiment queue — the autonomous-operation heart.

Pattern ported: arXiv 2604.13018 (AiScientist) File-as-Bus +
Prioritization Specialist, hardened with atomic pop semantics. A
well-formed queue item is the unit of continuous work: when the GPU
goes idle, `queue.py next` pops the top pending item, and the agent
turns it into a journal node + run.

CLI:
    queue.py add --hypothesis "..." --metric val_loss \\
                 [--predicted-delta -0.05] [--priority 3] \\
                 [--minutes 45] [--stage creative]
    queue.py next             # pop highest-priority, atomic claim
    queue.py status           # counts by status + target-fill report
    queue.py list [--status pending|claimed|done|dropped]
    queue.py done  <id>       # mark claimed → done
    queue.py drop  <id> --reason "..."
    queue.py release <id>     # undo a claim (claimed → pending)
    queue.py refill-needed    # exit 0 if queue has enough pending items,
                              # else exit 1 (script triggers /queue-refill)

Target-fill model: the harness wants a minimum number of pending items
at all times (default 5). `refill-needed` checks this. ZCM supervisor
can call it every hour to decide whether to wake the brainstormer.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sqlite3
import sys

DB = pathlib.Path(__file__).resolve().parent.parent / "memory" / "workflow.db"
TARGET_PENDING = int(os.environ.get("ROCKIE_QUEUE_TARGET", "5"))
VALID_STATUS = {"pending", "claimed", "done", "dropped"}


def project_name() -> str:
    env = os.environ.get("PROJECT")
    if env: return env
    return pathlib.Path(__file__).resolve().parents[2].name


def session_id() -> str:
    return (os.environ.get("CLAUDE_SESSION_ID")
            or os.environ.get("SESSION_ID") or "cli")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB, isolation_level=None)  # autocommit
    conn.execute("PRAGMA trusted_schema=1")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def cmd_add(args) -> int:
    conn = connect()
    cur = conn.execute(
        """
        INSERT INTO experiment_queue
          (project, priority, hypothesis, metric_name, predicted_delta,
           lower_is_better, estimated_minutes, suggested_stage,
           parent_experiment_id, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            project_name(),
            args.priority,
            args.hypothesis,
            args.metric,
            args.predicted_delta,
            1 if args.lower_is_better is None else args.lower_is_better,
            args.minutes,
            args.stage,
            args.parent,
            args.notes,
        ),
    )
    print(f"[queue] added item #{cur.lastrowid} (priority={args.priority})")
    return 0


def cmd_next(args) -> int:
    """Atomic claim of the highest-priority pending item."""
    conn = connect()
    # SQLite lacks SELECT ... FOR UPDATE, so we do it in a single UPDATE with
    # a subquery and RETURNING. This is atomic under SQLite's write lock.
    row = conn.execute(
        """
        UPDATE experiment_queue
        SET status = 'claimed',
            claimed_at = datetime('now'),
            claimed_by = ?
        WHERE id = (
            SELECT id FROM experiment_queue
            WHERE project = ? AND status = 'pending'
            ORDER BY priority ASC, id ASC
            LIMIT 1
        )
        RETURNING id, priority, hypothesis, metric_name, predicted_delta,
                  lower_is_better, estimated_minutes, suggested_stage, parent_experiment_id
        """,
        (session_id(), project_name()),
    ).fetchone()

    if not row:
        print("(queue empty for this project)", file=sys.stderr)
        return 1

    out = {
        "id": row["id"],
        "priority": row["priority"],
        "hypothesis": row["hypothesis"],
        "metric_name": row["metric_name"],
        "predicted_delta": row["predicted_delta"],
        "lower_is_better": row["lower_is_better"],
        "estimated_minutes": row["estimated_minutes"],
        "suggested_stage": row["suggested_stage"],
        "parent_experiment_id": row["parent_experiment_id"],
    }
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"[queue] claimed #{out['id']}: {out['hypothesis']}")
        print(f"  metric={out['metric_name']}  pred_delta={out['predicted_delta']}  "
              f"stage={out['suggested_stage']}  minutes≈{out['estimated_minutes']}")
    return 0


def cmd_done(args) -> int:
    conn = connect()
    n = conn.execute(
        "UPDATE experiment_queue SET status='done', done_at=datetime('now') "
        "WHERE id = ? AND status IN ('claimed','pending')",
        (args.id,),
    ).rowcount
    if n == 0:
        print(f"no claimable queue item #{args.id}", file=sys.stderr)
        return 2
    print(f"[queue] #{args.id} marked done")
    return 0


def cmd_drop(args) -> int:
    conn = connect()
    n = conn.execute(
        "UPDATE experiment_queue SET status='dropped', dropped_reason=?, done_at=datetime('now') "
        "WHERE id = ? AND status != 'done'",
        (args.reason, args.id),
    ).rowcount
    if n == 0:
        print(f"no droppable queue item #{args.id}", file=sys.stderr)
        return 2
    print(f"[queue] #{args.id} dropped: {args.reason}")
    return 0


def cmd_release(args) -> int:
    conn = connect()
    # Only the original claimant (or an admin with --force) can release;
    # otherwise a concurrent session could disrupt another's run.
    if args.force:
        where = "WHERE id = ? AND status='claimed'"
        params = (args.id,)
    else:
        where = "WHERE id = ? AND status='claimed' AND claimed_by = ?"
        params = (args.id, session_id())
    n = conn.execute(
        f"UPDATE experiment_queue SET status='pending', claimed_at=NULL, claimed_by=NULL {where}",
        params,
    ).rowcount
    if n == 0:
        print(
            f"no claimed item #{args.id} owned by session '{session_id()}' "
            f"(use --force to release someone else's claim)",
            file=sys.stderr,
        )
        return 2
    print(f"[queue] #{args.id} released back to pending")
    return 0


def cmd_reap(args) -> int:
    """Transition zombie 'claimed' rows older than --older-than-hours back to pending.

    When autopilot_loop dies mid-iteration (kill -9, power loss,
    preemption), the queue row is left stuck in 'claimed'. Without a
    reaper, the queue slowly fills with zombies and auto-refill's
    positive feedback makes it worse.
    """
    cutoff_hours = args.older_than_hours
    conn = connect()
    rows = conn.execute(
        """
        UPDATE experiment_queue
        SET status='pending',
            claimed_at=NULL,
            claimed_by=NULL,
            notes = coalesce(notes || char(10), '') ||
                    'reaped at ' || datetime('now') ||
                    ' (zombie claim > ' || ? || 'h)'
        WHERE project = ?
          AND status = 'claimed'
          AND claimed_at IS NOT NULL
          AND (julianday('now') - julianday(claimed_at)) * 24.0 > ?
        RETURNING id
        """,
        (cutoff_hours, project_name(), cutoff_hours),
    ).fetchall()
    if not rows:
        print(f"[queue-reap] no zombies older than {cutoff_hours}h")
        return 0
    ids = ", ".join(f"#{r['id']}" for r in rows)
    print(f"[queue-reap] released {len(rows)} zombie claim(s) back to pending: {ids}")
    return 0


def cmd_list(args) -> int:
    conn = connect()
    sql = "SELECT * FROM experiment_queue WHERE project = ?"
    params: list = [project_name()]
    if args.status:
        sql += " AND status = ?"; params.append(args.status)
    sql += " ORDER BY priority ASC, id ASC LIMIT 50"
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        print("(empty)")
        return 0
    for r in rows:
        marker = {"pending": "•", "claimed": "▶", "done": "✓", "dropped": "×"}.get(r["status"], "?")
        pred = f"{r['predicted_delta']:+.3f}" if r["predicted_delta"] is not None else "   —"
        print(f"{marker} #{r['id']:3d} p={r['priority']} [{r['status']:7}] "
              f"{r['metric_name'] or '':>10} {pred}  "
              f"{(r['hypothesis'] or '')[:60]}")
    return 0


def cmd_status(_args) -> int:
    conn = connect()
    proj = project_name()
    by_status = dict(conn.execute(
        "SELECT status, COUNT(*) FROM experiment_queue WHERE project=? GROUP BY status",
        (proj,),
    ).fetchall())
    pending = by_status.get("pending", 0)
    print(f"project:  {proj}")
    print(f"pending:  {pending}  (target ≥ {TARGET_PENDING})")
    print(f"claimed:  {by_status.get('claimed', 0)}")
    print(f"done:     {by_status.get('done', 0)}")
    print(f"dropped:  {by_status.get('dropped', 0)}")
    if pending < TARGET_PENDING:
        print(f"\n  ⚠  queue under target — run /queue-refill to generate "
              f"{TARGET_PENDING - pending} more item(s)")
    return 0


def cmd_refill_needed(_args) -> int:
    conn = connect()
    pending = conn.execute(
        "SELECT COUNT(*) FROM experiment_queue WHERE project=? AND status='pending'",
        (project_name(),),
    ).fetchone()[0]
    if pending >= TARGET_PENDING:
        return 0
    print(f"pending={pending} target={TARGET_PENDING}", file=sys.stderr)
    return 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd")

    ap = sub.add_parser("add", help="Add a new queue item")
    ap.add_argument("--hypothesis", required=True)
    ap.add_argument("--metric")
    ap.add_argument("--predicted-delta", type=float)
    ap.add_argument("--priority", type=int, default=3)
    ap.add_argument("--minutes", type=int)
    ap.add_argument("--stage")
    ap.add_argument("--parent", type=int, help="Parent experiment id")
    ap.add_argument("--lower-is-better", type=int, choices=[0, 1])
    ap.add_argument("--notes")
    ap.set_defaults(func=cmd_add)

    np = sub.add_parser("next", help="Atomically claim the top pending item")
    np.add_argument("--json", action="store_true")
    np.set_defaults(func=cmd_next)

    dp = sub.add_parser("done", help="Mark a claimed item as done")
    dp.add_argument("id", type=int); dp.set_defaults(func=cmd_done)

    drp = sub.add_parser("drop", help="Drop a pending/claimed item")
    drp.add_argument("id", type=int); drp.add_argument("--reason", required=True)
    drp.set_defaults(func=cmd_drop)

    rp = sub.add_parser("release", help="Release a claim back to pending")
    rp.add_argument("id", type=int)
    rp.add_argument("--force", action="store_true",
                    help="Release a claim owned by a different session")
    rp.set_defaults(func=cmd_release)

    rep = sub.add_parser("reap", help="Release zombie claims older than N hours")
    rep.add_argument("--older-than-hours", type=float, default=2.0)
    rep.set_defaults(func=cmd_reap)

    lp = sub.add_parser("list", help="List items")
    lp.add_argument("--status", choices=sorted(VALID_STATUS))
    lp.set_defaults(func=cmd_list)

    sub.add_parser("status", help="Roll-up").set_defaults(func=cmd_status)
    sub.add_parser("refill-needed", help="Exit 0 if queue at target, else 1") \
        .set_defaults(func=cmd_refill_needed)

    args = p.parse_args()
    if not args.cmd:
        return cmd_status(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
