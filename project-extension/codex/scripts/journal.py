#!/usr/bin/env python3
"""Experiments journal — the canonical tree of every run.

Each experiment is a node with optional parent, stage, status, hypothesis,
metric, and post-run analysis. This is the structured replacement for
EXPERIMENT_LOG.md as the source of truth; the log becomes a rendered view.

Usage:
    journal.py add --stage draft --hypothesis "..." [--parent N] [--run-id RID]
    journal.py start <id>                    # pending → running
    journal.py close <id> --metric NAME=VAL --is-buggy 0|1 \\
                         [--failure-class bug|bad-hyperparam|bad-hypothesis] \\
                         [--lower-is-better 0|1] [--analysis "..."] [--code-path PATH]
    journal.py kill <id> --reason "..."      # terminates a branch
    journal.py tree [--project P]            # ASCII tree
    journal.py best [--metric NAME]          # best-so-far per metric
    journal.py leaves                        # open leaves (work to do)
    journal.py status                        # roll-up counts
    journal.py render [--out EXPERIMENT_LOG.md]  # render tree to markdown

The stages are 'draft' | 'debug' | 'improve' | 'baseline-tune' | 'creative'
| 'ablation'. 'debug' increments debug_depth from the parent; others reset
to 0. The search policy (A4) reads this tree to pick the next action.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sqlite3
import sys
from collections import defaultdict
from typing import Optional

DB_PATH = pathlib.Path(__file__).resolve().parent.parent / "memory" / "workflow.db"
# Node stages: the 4 user-level stages from stage.py (imported from the
# same file so they stay in sync) plus 2 search-policy sub-modes that live
# inside the tree (debug/improve). See stage.py's doc for the split.
try:
    # stage.py lives alongside this file in scripts/
    _here = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(_here))
    from stage import VALID_STAGES as _USER_STAGES  # type: ignore
    sys.path.pop(0)
except Exception:
    _USER_STAGES = ["draft", "baseline-tune", "creative", "ablation"]
STAGES = set(_USER_STAGES) | {"debug", "improve"}
STATUSES = {"pending", "running", "done", "killed"}
FAILURE_CLASSES = {"bug", "bad-hyperparam", "bad-hypothesis"}


def project_name() -> str:
    env = os.environ.get("PROJECT")
    if env:
        return env
    return pathlib.Path(__file__).resolve().parents[2].name


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA trusted_schema=1")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


# ─── add / start / close / kill ────────────────────────────────────────────


def cmd_add(args) -> int:
    if args.stage not in STAGES:
        print(f"invalid stage: {args.stage}. choose from {sorted(STAGES)}", file=sys.stderr)
        return 2
    conn = connect()
    parent_depth = 0
    if args.parent:
        row = conn.execute(
            "SELECT debug_depth, project FROM experiments WHERE id = ?", (args.parent,)
        ).fetchone()
        if not row:
            print(f"no such parent: {args.parent}", file=sys.stderr)
            return 2
        parent_depth = row["debug_depth"]

    # debug_depth: debug increments from parent, anything else resets
    if args.stage == "debug":
        depth = parent_depth + 1
    else:
        depth = 0

    cur = conn.execute(
        """
        INSERT INTO experiments
          (project, run_id, parent_id, stage, status, hypothesis, code_path, debug_depth, lower_is_better)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            project_name(),
            args.run_id,
            args.parent,
            args.stage,
            "pending",
            args.hypothesis,
            args.code_path,
            depth,
            1 if args.lower_is_better is None else args.lower_is_better,
        ),
    )
    conn.commit()
    print(f"[journal] added experiment #{cur.lastrowid} (stage={args.stage}, depth={depth})")
    return 0


def cmd_start(args) -> int:
    conn = connect()
    n = conn.execute(
        "UPDATE experiments SET status='running' WHERE id = ? AND status='pending'",
        (args.id,),
    ).rowcount
    conn.commit()
    if n == 0:
        print(f"no pending experiment #{args.id}", file=sys.stderr)
        return 2
    print(f"[journal] started #{args.id}")
    return 0


def _parse_metric(s: str) -> tuple[str, float]:
    if "=" not in s:
        raise SystemExit(f"--metric must be NAME=VAL, got {s!r}")
    name, val = s.split("=", 1)
    try:
        return name.strip(), float(val)
    except ValueError as e:
        raise SystemExit(f"metric value not a number: {val!r}") from e


def cmd_close(args) -> int:
    if args.failure_class and args.failure_class not in FAILURE_CLASSES:
        print(f"invalid failure-class; choose from {sorted(FAILURE_CLASSES)}", file=sys.stderr)
        return 2
    metric_name, metric_value = (None, None)
    if args.metric:
        metric_name, metric_value = _parse_metric(args.metric)

    conn = connect()
    row = conn.execute(
        "SELECT id, status FROM experiments WHERE id = ?", (args.id,)
    ).fetchone()
    if not row:
        print(f"no such experiment #{args.id}", file=sys.stderr)
        return 2
    if row["status"] == "done":
        print(f"#{args.id} already closed", file=sys.stderr)
        return 2

    fields = {
        "status": "done",
        "closed_at": None,  # datetime('now') below
        "is_buggy": args.is_buggy,
        "failure_class": args.failure_class,
        "metric_name": metric_name,
        "metric_value": metric_value,
        "analysis": args.analysis,
        "code_path": args.code_path,
    }
    if args.lower_is_better is not None:
        fields["lower_is_better"] = args.lower_is_better

    set_sql = "closed_at=datetime('now'), " + ", ".join(
        f"{k}=?" for k in fields if k != "closed_at"
    )
    params = [v for k, v in fields.items() if k != "closed_at"]
    params.append(args.id)
    conn.execute(f"UPDATE experiments SET {set_sql} WHERE id = ?", params)
    conn.commit()

    # If this close indicates a bug, auto-emit a [LEARN]-ish hint for the agent
    if args.is_buggy == 1 and args.analysis:
        print(
            f"[journal] #{args.id} closed as BUG. Consider emitting [LEARN] or [DEAD-END].",
            file=sys.stderr,
        )
    print(f"[journal] closed #{args.id}")
    return 0


def cmd_kill(args) -> int:
    conn = connect()
    n = conn.execute(
        "UPDATE experiments SET status='killed', closed_at=datetime('now'), analysis=? WHERE id = ?",
        (args.reason, args.id),
    ).rowcount
    conn.commit()
    if n == 0:
        print(f"no experiment #{args.id}", file=sys.stderr)
        return 2
    print(f"[journal] killed #{args.id}")
    return 0


# ─── views ─────────────────────────────────────────────────────────────────


def cmd_tree(args) -> int:
    conn = connect()
    proj = args.project or project_name()
    rows = conn.execute(
        "SELECT * FROM experiments WHERE project = ? ORDER BY id", (proj,)
    ).fetchall()
    if not rows:
        print("(no experiments)")
        return 0

    children = defaultdict(list)
    byid = {}
    roots = []
    for r in rows:
        byid[r["id"]] = r
        if r["parent_id"] is None:
            roots.append(r["id"])
        else:
            children[r["parent_id"]].append(r["id"])

    GREEN = "\033[32m"; RED = "\033[31m"; YELLOW = "\033[33m"; DIM = "\033[2m"; RESET = "\033[0m"

    def render_row(r) -> str:
        buggy = r["is_buggy"]
        status = r["status"]
        mark = "?"
        color = ""
        if buggy == 0 and status == "done": mark, color = "✓", GREEN
        elif buggy == 1: mark, color = "✗", RED
        elif status == "running": mark, color = "▶", YELLOW
        elif status == "killed": mark, color = "×", DIM
        elif status == "pending": mark, color = "•", ""
        metric = ""
        if r["metric_name"] and r["metric_value"] is not None:
            metric = f"  {r['metric_name']}={r['metric_value']:g}"
        hyp = (r["hypothesis"] or "")[:68]
        tag = f"[{r['stage']}"
        if r["debug_depth"]: tag += f",d{r['debug_depth']}"
        tag += "]"
        return f"{color}{mark}{RESET} #{r['id']:3d} {tag:18} {hyp}{metric}"

    def walk(node_id: int, prefix: str, is_last: bool):
        r = byid[node_id]
        connector = "└── " if is_last else "├── "
        print(prefix + connector + render_row(r))
        kids = children[node_id]
        new_prefix = prefix + ("    " if is_last else "│   ")
        for i, k in enumerate(kids):
            walk(k, new_prefix, i == len(kids) - 1)

    for i, rid in enumerate(roots):
        walk(rid, "", i == len(roots) - 1)
    return 0


def cmd_best(args) -> int:
    conn = connect()
    sql = "SELECT * FROM best_so_far WHERE project = ?"
    params: list = [project_name()]
    if args.metric:
        sql += " AND metric_name = ?"
        params.append(args.metric)
    rows = conn.execute(sql + " ORDER BY metric_name", params).fetchall()
    if not rows:
        print("(no best-so-far)")
        return 0
    for r in rows:
        arrow = "↓" if r["lower_is_better"] else "↑"
        print(f"#{r['id']:3d} [{r['stage']}] {r['metric_name']} {arrow} {r['metric_value']:g}  "
              f"{(r['hypothesis'] or '')[:60]}")
    return 0


def cmd_leaves(args) -> int:
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM open_leaves WHERE project = ? ORDER BY id", (project_name(),)
    ).fetchall()
    if not rows:
        print("(no open leaves — tree has no work queued)")
        return 0
    for r in rows:
        print(f"#{r['id']:3d} [{r['stage']:15}] {r['status']:8} {(r['hypothesis'] or '')[:65]}")
    return 0


def cmd_status(args) -> int:
    conn = connect()
    proj = project_name()
    total = conn.execute("SELECT COUNT(*) FROM experiments WHERE project=?", (proj,)).fetchone()[0]
    if not total:
        print("(no experiments yet)")
        return 0
    by_status = dict(conn.execute(
        "SELECT status, COUNT(*) FROM experiments WHERE project=? GROUP BY status", (proj,)
    ).fetchall())
    by_stage = dict(conn.execute(
        "SELECT stage, COUNT(*) FROM experiments WHERE project=? GROUP BY stage", (proj,)
    ).fetchall())
    by_fail = dict(conn.execute(
        "SELECT failure_class, COUNT(*) FROM experiments "
        "WHERE project=? AND failure_class IS NOT NULL GROUP BY failure_class", (proj,)
    ).fetchall())

    print(f"project:  {proj}")
    print(f"total:    {total}")
    print(f"status:   " + "  ".join(f"{k}={v}" for k, v in sorted(by_status.items())))
    print(f"stage:    " + "  ".join(f"{k}={v}" for k, v in sorted(by_stage.items())))
    if by_fail:
        print(f"failures: " + "  ".join(f"{k}={v}" for k, v in sorted(by_fail.items())))
    return 0


def cmd_render(args) -> int:
    """Render the experiments tree to a markdown document."""
    conn = connect()
    proj = project_name()
    rows = conn.execute(
        "SELECT * FROM experiments WHERE project=? ORDER BY created_at", (proj,)
    ).fetchall()

    out_lines = [
        f"# Experiment Log — {proj}",
        "",
        f"_Auto-rendered from `.codex/memory/workflow.db` via `journal.py render`._",
        f"_{len(rows)} experiment(s) total._",
        "",
    ]
    if not rows:
        out_lines.append("_(no experiments yet)_")
    else:
        out_lines.extend(["## Best-so-far", ""])
        best = conn.execute("SELECT * FROM best_so_far WHERE project=?", (proj,)).fetchall()
        if best:
            for b in best:
                arrow = "↓" if b["lower_is_better"] else "↑"
                out_lines.append(
                    f"- #{b['id']} · {b['metric_name']} {arrow} **{b['metric_value']:g}** · {b['hypothesis'] or ''}"
                )
        else:
            out_lines.append("_(no closed non-buggy experiments yet)_")
        out_lines.extend(["", "## All experiments", ""])
        for r in rows:
            parent = f" ↪ parent #{r['parent_id']}" if r["parent_id"] else ""
            metric = ""
            if r["metric_name"] and r["metric_value"] is not None:
                arrow = "↓" if r["lower_is_better"] else "↑"
                metric = f" · **{r['metric_name']} {arrow} {r['metric_value']:g}**"
            buggy = ""
            if r["is_buggy"] == 1:
                buggy = f" · BUG ({r['failure_class'] or 'unclassified'})"
            elif r["is_buggy"] == 0:
                buggy = " · clean"
            out_lines.append(f"### #{r['id']} — [{r['stage']}] {r['status']}{parent}{metric}{buggy}")
            if r["hypothesis"]:
                out_lines.append(f"> {r['hypothesis']}")
            if r["analysis"]:
                out_lines.append("")
                out_lines.append(r["analysis"])
            if r["code_path"]:
                out_lines.append(f"\n_code: `{r['code_path']}`_")
            if r["run_id"]:
                out_lines.append(f"_run: `{r['run_id']}`_")
            out_lines.append("")

    text = "\n".join(out_lines) + "\n"
    if args.out:
        pathlib.Path(args.out).write_text(text)
        print(f"rendered to {args.out}")
    else:
        sys.stdout.write(text)
    return 0


# ─── arg parsing ───────────────────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd")

    ap = sub.add_parser("add", help="Create a new experiment node")
    ap.add_argument("--stage", required=True, choices=sorted(STAGES))
    ap.add_argument("--hypothesis")
    ap.add_argument("--parent", type=int)
    ap.add_argument("--run-id")
    ap.add_argument("--code-path")
    ap.add_argument("--lower-is-better", type=int, choices=[0, 1])
    ap.set_defaults(func=cmd_add)

    sp = sub.add_parser("start", help="Mark a pending experiment as running")
    sp.add_argument("id", type=int)
    sp.set_defaults(func=cmd_start)

    cp = sub.add_parser("close", help="Close a running experiment with results")
    cp.add_argument("id", type=int)
    cp.add_argument("--metric", help="NAME=VALUE")
    cp.add_argument("--is-buggy", type=int, choices=[0, 1])
    cp.add_argument("--failure-class", choices=sorted(FAILURE_CLASSES))
    cp.add_argument("--lower-is-better", type=int, choices=[0, 1])
    cp.add_argument("--analysis")
    cp.add_argument("--code-path")
    cp.set_defaults(func=cmd_close)

    kp = sub.add_parser("kill", help="Kill an experiment")
    kp.add_argument("id", type=int)
    kp.add_argument("--reason", required=True)
    kp.set_defaults(func=cmd_kill)

    tp = sub.add_parser("tree", help="ASCII tree")
    tp.add_argument("--project")
    tp.set_defaults(func=cmd_tree)

    bp = sub.add_parser("best", help="Best-so-far by metric")
    bp.add_argument("--metric")
    bp.set_defaults(func=cmd_best)

    lp = sub.add_parser("leaves", help="Open leaves (actionable nodes)")
    lp.set_defaults(func=cmd_leaves)

    stp = sub.add_parser("status", help="Summary counts")
    stp.set_defaults(func=cmd_status)

    rp = sub.add_parser("render", help="Render tree to markdown")
    rp.add_argument("--out")
    rp.set_defaults(func=cmd_render)

    args = p.parse_args()
    if not args.cmd:
        p.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
