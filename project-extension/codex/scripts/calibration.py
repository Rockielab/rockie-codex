#!/usr/bin/env python3
"""Hypothesis calibration report over workflow.db.

Shows how well the agent's predicted metric deltas track reality.
Higher sign-correctness = agent's priors are pointing the right way.
Lower mean-abs-error = agent's priors are well-calibrated.

Usage:
    python3 calibration.py                              # full scorecard
    python3 calibration.py report [--open]              # same, with flag
    python3 calibration.py add RUN_ID HYPOTHESIS METRIC PREDICTED_DELTA
    python3 calibration.py close RUN_ID HYPOTHESIS ACTUAL_DELTA

The harness's post-run review hook should normally --close predictions
automatically; this CLI is for manual inspection and bootstrapping.
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys

DB_PATH = pathlib.Path(__file__).resolve().parent.parent / "memory" / "workflow.db"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA trusted_schema=1")
    conn.row_factory = sqlite3.Row
    return conn


def project_name() -> str:
    import os
    env = os.environ.get("PROJECT")
    if env:
        return env
    return pathlib.Path(__file__).resolve().parents[2].name


def cmd_report(only_open: bool) -> int:
    conn = connect()
    where = "WHERE project = ?" + (" AND actual_delta IS NULL" if only_open else "")
    rows = conn.execute(
        f"""
        SELECT run_id, hypothesis, metric_name, predicted_delta, actual_delta,
               sign_correct, abs_error, created_at, closed_at
        FROM calibration_scorecard
        {where}
        ORDER BY created_at DESC
        LIMIT 50
        """,
        (project_name(),),
    ).fetchall()

    if not rows:
        print("(no predictions yet)")
        return 0

    print(f"{'run':22} {'metric':12} {'pred':>8} {'actual':>8} {'abs_err':>8} sign  hypothesis")
    print("─" * 100)
    for r in rows:
        actual = f"{r['actual_delta']:+.4f}" if r["actual_delta"] is not None else "    —"
        abs_err = f"{r['abs_error']:.4f}" if r["abs_error"] is not None else "    —"
        sign = "✓" if r["sign_correct"] == 1 else ("✗" if r["sign_correct"] == 0 else "—")
        hyp = (r["hypothesis"] or "")[:48]
        print(
            f"{r['run_id']:22} {r['metric_name']:12} "
            f"{r['predicted_delta']:+.4f} {actual:>8} {abs_err:>8} "
            f"  {sign}   {hyp}"
        )

    # Roll-up
    closed = conn.execute(
        """
        SELECT AVG(sign_correct * 1.0) AS sign_acc,
               AVG(abs_error) AS mae,
               COUNT(*) AS n
        FROM calibration_scorecard
        WHERE project = ? AND actual_delta IS NOT NULL
        """,
        (project_name(),),
    ).fetchone()
    if closed and closed["n"]:
        print("─" * 100)
        print(
            f"  closed predictions: {closed['n']:>4}  "
            f"sign-correct: {closed['sign_acc']*100:.1f}%  "
            f"mean abs-error: {closed['mae']:.4f}"
        )
    return 0


def cmd_add(run_id: str, hypothesis: str, metric: str, predicted_delta: float) -> int:
    conn = connect()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO hypothesis_calibration
              (project, run_id, hypothesis, metric_name, predicted_delta)
            VALUES (?,?,?,?,?)
            """,
            (project_name(), run_id, hypothesis, metric, predicted_delta),
        )
        conn.commit()
        print(f"[calibration] added prediction: {run_id} / {hypothesis[:60]}")
        return 0
    except sqlite3.Error as e:
        print(f"add failed: {e}", file=sys.stderr)
        return 2


def cmd_close(run_id: str, hypothesis: str, actual_delta: float) -> int:
    conn = connect()
    n = conn.execute(
        """
        UPDATE hypothesis_calibration
        SET actual_delta = ?, closed_at = datetime('now')
        WHERE project = ? AND run_id = ? AND hypothesis = ?
        """,
        (actual_delta, project_name(), run_id, hypothesis),
    ).rowcount
    conn.commit()
    if n == 0:
        print(
            f"close failed: no open prediction found for run={run_id!r} hypothesis={hypothesis!r}",
            file=sys.stderr,
        )
        return 2
    print(f"[calibration] closed {n} prediction(s) for {run_id}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd")

    rp = sub.add_parser("report", help="Show calibration scorecard (default)")
    rp.add_argument("--open", action="store_true", dest="only_open",
                    help="Only show predictions with no actual yet")

    ap = sub.add_parser("add", help="Record a predicted delta for a run")
    ap.add_argument("run_id")
    ap.add_argument("hypothesis")
    ap.add_argument("metric")
    ap.add_argument("predicted_delta", type=float)

    cp = sub.add_parser("close", help="Fill in the actual delta for a run")
    cp.add_argument("run_id")
    cp.add_argument("hypothesis")
    cp.add_argument("actual_delta", type=float)

    # Default command is 'report' if bare invocation
    args = p.parse_args()
    cmd = args.cmd or "report"

    if cmd == "report":
        return cmd_report(getattr(args, "only_open", False))
    if cmd == "add":
        return cmd_add(args.run_id, args.hypothesis, args.metric, args.predicted_delta)
    if cmd == "close":
        return cmd_close(args.run_id, args.hypothesis, args.actual_delta)
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
