#!/usr/bin/env python3
"""Deep consolidation pass — promote cross-repo rules, log stats.

Runs auto-promotion (3+ repos → global tier) and prints a summary. Safe to
run on a schedule (daily) or manually.

Usage:
  consolidate.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import lib  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    conn = lib.connect()

    # Stats before
    active = conn.execute(
        "SELECT COUNT(*) FROM memories WHERE status = 'active'"
    ).fetchone()[0]
    by_project = conn.execute(
        """
        SELECT COALESCE(project, '[global]') AS proj, COUNT(*) AS n
        FROM memories WHERE status = 'active'
        GROUP BY project ORDER BY n DESC
        """
    ).fetchall()

    print(f"Active memories: {active}")
    for r in by_project:
        print(f"  {r['proj']:30s} {r['n']}")

    if args.dry_run:
        # Just show what WOULD promote
        candidates = conn.execute(
            """
            SELECT rule_normalized, COUNT(DISTINCT project) AS n
            FROM memories
            WHERE status = 'active' AND project IS NOT NULL
            GROUP BY rule_normalized
            HAVING COUNT(DISTINCT project) >= ?
            """,
            (lib.PROMOTE_THRESHOLD,),
        ).fetchall()
        print(
            f"\nWould promote {len(candidates)} rules to global (threshold: {lib.PROMOTE_THRESHOLD} repos):"
        )
        for r in candidates:
            print(f"  • [{r['n']} repos] {r['rule_normalized'][:100]}")
        return 0

    promoted = lib.promote_cross_repo(conn)
    if promoted:
        print(f"\n✓ promoted {len(promoted)} rules to global tier")
    else:
        print("\n✓ nothing to promote (threshold not met)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
