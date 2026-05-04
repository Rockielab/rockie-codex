#!/usr/bin/env python3
"""Surface active memories for a project into a markdown file.

Writes <repo>/.codex/memory/rules-compiled.md with the top-K active
memories (repo-tier + global-tier), grouped by tier and category. AGENTS.md
references this file so rules load on session start.

Usage:
  surface.py --repo <absolute-repo-path> [--out <path>] [--limit N]
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import lib  # noqa: E402


def render(memories, project: str | None) -> str:
    out = []
    out.append("# Compiled Rules")
    out.append("")
    out.append(
        f"_Auto-generated from `~/.codex/memory/memory.db`. Do not edit by hand._"
    )
    out.append(f"_Last compiled: {lib.now_iso()}_")
    out.append("")

    if not memories:
        out.append(
            "_(No active memories yet. Emit `[LEARN]` blocks in your responses "
            "and they'll be captured automatically.)_"
        )
        out.append("")
        return "\n".join(out) + "\n"

    # Partition by tier
    global_mems = [m for m in memories if m["project"] is None]
    repo_mems = [m for m in memories if m["project"] is not None]

    def write_group(title: str, rows):
        if not rows:
            return
        out.append(f"## {title}")
        out.append("")
        by_cat = defaultdict(list)
        for r in rows:
            by_cat[r["category"]].append(r)
        for cat in sorted(by_cat):
            out.append(f"### {cat}")
            out.append("")
            for r in by_cat[cat]:
                hits = f" _(×{r['hit_count']})_" if r["hit_count"] > 1 else ""
                out.append(f"- **{r['rule']}**{hits}")
                if r["mistake"]:
                    out.append(f"  - *Mistake:* {r['mistake']}")
                if r["correction"]:
                    out.append(f"  - *Correction:* {r['correction']}")
            out.append("")

    write_group("Global (cross-repo)", global_mems)
    tag = project or "this project"
    write_group(f"Repo-local: {tag}", repo_mems)
    return "\n".join(out) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--repo", default=None, help="Absolute repo path (required; no cwd fallback)"
    )
    p.add_argument("--out", default=None)
    p.add_argument("--limit", type=int, default=100)
    args = p.parse_args()

    # No silent cwd fallback — explicit --repo required so surfacing can't
    # accidentally tier memories by $PWD basename.
    if not args.repo:
        print("surface: --repo is required (no cwd fallback)", file=sys.stderr)
        return 2
    project = lib.project_from_path(args.repo)
    conn = lib.connect()
    memories = lib.active_memories_for_project(conn, project, limit=args.limit)

    out_path = (
        Path(args.out)
        if args.out
        else Path(args.repo) / ".codex" / "memory" / "rules-compiled.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(memories, project))

    print(
        f"✓ surface: wrote {len(memories)} memories to {out_path} [project={project or 'GLOBAL'}]",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
