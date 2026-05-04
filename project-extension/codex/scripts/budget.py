#!/usr/bin/env python3
"""Budget controller — track and enforce ceilings on long autonomous runs.

Ports the PaperQA2 `settings.py` pattern (Apache-2.0) — centralized
limits, every subsystem reads from one place. rockie-specific:
ceilings live in `.codex/budget.toml`, cumulative usage in workflow.db
(`budget_usage` table), and a PreToolUse hook aborts when any ceiling
is crossed.

Usage is scoped by (session, project) with distinct keys per combo;
reset clears only the current session's or current project's rows,
never another project's.

Config file format (`.codex/budget.toml`):

    [session]
    tokens        = 5_000_000    # optional; 0 or missing = unlimited
    wallclock_s   = 28_800       # 8 hours
    tool_calls    = 2000

    [project]
    dollars       = 50.00        # cumulative across all sessions

Usage:
    budget.py status             # show all budgets vs usage
    budget.py add <metric> <n>   # add to cumulative (session + project)
    budget.py check              # exit 0 if OK, exit 2 with reason if over
    budget.py reset <scope>      # scope: 'session' | 'project'
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sqlite3
import sys
from typing import Any

try:
    import tomllib  # py311+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

HARNESS_ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = HARNESS_ROOT / "memory" / "workflow.db"
CFG = HARNESS_ROOT / "budget.toml"

VALID_METRICS = {"tokens", "wallclock_s", "tool_calls", "dollars"}


def project_name() -> str:
    env = os.environ.get("PROJECT")
    if env: return env
    return pathlib.Path(__file__).resolve().parents[2].name


def session_id() -> str:
    # The Codex hook system passes session_id in the hook payload; for
    # CLI use, fall back to the env var or "cli".
    #
    # An empty CLAUDE_SESSION_ID would previously generate the key
    # `session::tokens`, which silently bypassed any ceilings (security
    # audit M-1). Reject empty strings → fall through to "cli".
    s = os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("SESSION_ID")
    if s and s.strip():
        return s.strip()
    return "cli"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA trusted_schema=1")
    conn.row_factory = sqlite3.Row
    return conn


def read_cfg() -> dict[str, Any]:
    if not CFG.exists():
        return {"session": {}, "project": {}}
    with CFG.open("rb") as f:
        return tomllib.load(f)


def _key(scope: str, metric: str) -> str:
    if scope == "session":
        return f"session:{session_id()}:{metric}"
    if scope == "project":
        return f"project:{project_name()}:{metric}"
    raise ValueError(f"bad scope {scope!r}")


def get_usage(conn: sqlite3.Connection, scope: str, metric: str) -> float:
    row = conn.execute(
        "SELECT value FROM budget_usage WHERE key=?", (_key(scope, metric),)
    ).fetchone()
    return row["value"] if row else 0.0


def add_usage(conn: sqlite3.Connection, metric: str, amount: float) -> None:
    """Add to both session and project cumulative counters."""
    for scope in ("session", "project"):
        key = _key(scope, metric)
        conn.execute(
            """
            INSERT INTO budget_usage (key, project, session_id, metric, value)
            VALUES (?,?,?,?,?)
            ON CONFLICT(key) DO UPDATE SET
              value = value + excluded.value,
              updated_at = datetime('now')
            """,
            (key, project_name(), session_id(), metric, amount),
        )
    conn.commit()


def cmd_add(args) -> int:
    if args.metric not in VALID_METRICS:
        print(f"metric must be one of {VALID_METRICS}", file=sys.stderr)
        return 2
    conn = connect()
    add_usage(conn, args.metric, float(args.amount))
    print(f"[budget] +{args.amount} {args.metric}")
    return 0


def cmd_status(_args) -> int:
    cfg = read_cfg()
    conn = connect()
    hdr = f"{'scope':9} {'metric':12} {'used':>14} {'ceiling':>14} {'pct':>6}"
    print(hdr); print("─" * len(hdr))
    any_row = False
    for scope in ("session", "project"):
        ceilings = cfg.get(scope, {}) or {}
        for metric, ceiling in ceilings.items():
            if metric not in VALID_METRICS:
                continue
            used = get_usage(conn, scope, metric)
            if ceiling > 0:
                pct = f"{used/ceiling*100:5.1f}%"
            else:
                pct = "    —"
            print(f"{scope:9} {metric:12} {used:14.2f} {float(ceiling):14.2f} {pct}")
            any_row = True
        # Also show metrics used but not capped
        rows = conn.execute(
            "SELECT metric, value FROM budget_usage WHERE key LIKE ? ",
            (f"{scope}:%",),
        ).fetchall()
        for r in rows:
            if r["metric"] not in (ceilings or {}) and r["metric"] in VALID_METRICS:
                print(f"{scope:9} {r['metric']:12} {r['value']:14.2f} {'—':>14} {'—':>6}")
                any_row = True
    if not any_row:
        print("(no usage yet; no ceilings configured — edit .codex/budget.toml)")
    return 0


def cmd_check(_args) -> int:
    cfg = read_cfg()
    conn = connect()
    violations: list[str] = []
    for scope in ("session", "project"):
        ceilings = cfg.get(scope, {}) or {}
        for metric, ceiling in ceilings.items():
            if metric not in VALID_METRICS:
                continue
            if ceiling <= 0:
                continue
            used = get_usage(conn, scope, metric)
            if used > ceiling:
                violations.append(f"{scope}.{metric}: {used:.2f} > ceiling {float(ceiling):.2f}")
    if violations:
        print("[budget-check] CEILING CROSSED:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        print("  Pause or raise ceilings in .codex/budget.toml to continue.", file=sys.stderr)
        return 2
    return 0


def _state_dir() -> pathlib.Path:
    d = HARNESS_ROOT / ".state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cmd_tick_wallclock(_args) -> int:
    """Refresh session wallclock_s counter to 'now - session_start_ts'.

    SessionStart hook stamps .state/session_start_<sid>. This command,
    called by the Stop hook, reads that timestamp and SETS the
    wallclock_s counter (monotonic, per-session) to the elapsed seconds.
    """
    import time
    sid = session_id()
    stamp = _state_dir() / f"session_start_{sid}"
    if not stamp.exists():
        return 0  # nothing to tick
    try:
        start = int(stamp.read_text().strip())
    except Exception:
        return 0
    now = int(time.time())
    elapsed = max(0, now - start)
    conn = connect()
    key = _key("session", "wallclock_s")
    conn.execute(
        """
        INSERT INTO budget_usage (key, project, session_id, metric, value)
        VALUES (?, ?, ?, 'wallclock_s', ?)
        ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = datetime('now')
        """,
        (key, project_name(), sid, float(elapsed), float(elapsed)),
    )
    conn.commit()
    return 0


def cmd_tick_tokens(args) -> int:
    """Estimate session tokens from the transcript file size and update counter.

    Rough proxy: 1 token ≈ 4 bytes of utf-8 assistant/user text. Called
    by the Stop hook with --transcript <path>. SETS (not ADDS) the
    session counter so it always reflects the current transcript size.
    """
    p = pathlib.Path(args.transcript)
    if not p.exists():
        return 0
    try:
        nbytes = p.stat().st_size
    except OSError:
        return 0
    est_tokens = int(nbytes / 4)
    conn = connect()
    key = _key("session", "tokens")
    conn.execute(
        """
        INSERT INTO budget_usage (key, project, session_id, metric, value)
        VALUES (?, ?, ?, 'tokens', ?)
        ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = datetime('now')
        """,
        (key, project_name(), session_id(), float(est_tokens), float(est_tokens)),
    )
    conn.commit()
    return 0


def cmd_reset(args) -> int:
    if args.scope not in ("session", "project"):
        print("scope must be 'session' or 'project'", file=sys.stderr)
        return 2
    conn = connect()
    # Scope to the CURRENT session/project, not all rows with that prefix.
    # Earlier implementation LIKE 'project:%' wiped every project's counters.
    if args.scope == "session":
        like = f"session:{session_id()}:%"
    else:
        like = f"project:{project_name()}:%"
    n = conn.execute(
        "DELETE FROM budget_usage WHERE key LIKE ?", (like,)
    ).rowcount
    conn.commit()
    print(f"[budget] reset {args.scope} ({like}) — {n} row(s)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("check").set_defaults(func=cmd_check)
    ap = sub.add_parser("add"); ap.add_argument("metric"); ap.add_argument("amount"); ap.set_defaults(func=cmd_add)
    rp = sub.add_parser("reset"); rp.add_argument("scope"); rp.set_defaults(func=cmd_reset)
    sub.add_parser("tick-wallclock").set_defaults(func=cmd_tick_wallclock)
    tt = sub.add_parser("tick-tokens"); tt.add_argument("--transcript", required=True); tt.set_defaults(func=cmd_tick_tokens)
    args = p.parse_args()
    if not args.cmd:
        return cmd_status(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
